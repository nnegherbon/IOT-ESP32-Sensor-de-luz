"""API HTTP/WebSocket e integração MQTT real com um broker local (amqtt).

O broker local recebe os MESMOS payloads publicados pelo firmware, usando os
mesmos client IDs dos dispositivos, para validar o fluxo de ponta a ponta.
"""
import asyncio
import csv
import io
import json
import socket

import aiomqtt
import httpx
import pytest
import pytest_asyncio

from app import firmware as fw
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_DSN, reset_schema


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_broker(port: int):
    from amqtt.broker import Broker
    b = Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
                "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}})
    await b.start()
    return b


async def wait_for(cond, timeout=10.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if await cond():
            return True
        await asyncio.sleep(0.1)
    raise AssertionError("condição não atingida a tempo")


@pytest_asyncio.fixture
async def clean_db():
    pool = await reset_schema()
    await pool.close()


@pytest.mark.asyncio
async def test_end_to_end_mqtt_flow_and_reconnect(clean_db):
    port = free_port()
    broker = await start_broker(port)
    settings = Settings(database_url=TEST_DSN, mqtt_host="127.0.0.1", mqtt_port=port,
                        mqtt_reconnect_min_s=0.2, mqtt_reconnect_max_s=0.5, watchdog_interval_s=0.2)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        svc = app.state.service
        await wait_for(lambda: _ret(svc.broker["status"] == "conectado"))

        # Atuador publica retido (como no firmware) e sensor publica comando
        async with aiomqtt.Client("127.0.0.1", port, identifier="SensorNode01") as sensor, \
                aiomqtt.Client("127.0.0.1", port, identifier="atuador01") as atuador:
            await sensor.publish(fw.TOPIC_COMMAND, b'{"cena":"extrema"}', qos=0)
            await wait_for(lambda: _ret(svc.sensor["last_command"] is not None))
            await atuador.publish(fw.TOPIC_ACTUATOR_STATUS,
                                  b'{"device":"atuador01","estado":"extrema_executada"}', qos=0, retain=True)
            await wait_for(lambda: _ret(svc.sync_state() == "sincronizado"))
            await sensor.publish(fw.TOPIC_COMMAND, b'not json', qos=0)
            await wait_for(lambda: _ret(svc.stats["invalidas"] == 1))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            st = (await http.get("/api/state")).json()
            assert st["sync"] == "sincronizado"
            assert st["actuator"]["confirmed"]["leds"] == [True, True, True, True]
            cmds = (await http.get("/api/commands")).json()
            assert cmds["total"] == 1 and cmds["items"][0]["status"] == "confirmado"
            msgs = (await http.get("/api/messages", params={"parse_status": "invalido"})).json()
            assert msgs["total"] == 1

        # Queda do broker -> desconectado -> reconexão automática
        await broker.shutdown()
        await wait_for(lambda: _ret(svc.broker["status"] in ("desconectado", "conectando")))
        broker = await start_broker(port)
        await wait_for(lambda: _ret(svc.broker["status"] == "conectado"), timeout=15)
        # Ao reassinar, a mensagem retida chega marcada como retida e NÃO conta como confirmação nova.
        # (o amqtt não persiste retidas entre reinícios, então só verificamos eventos de conectividade)
        async with app.state.pool.acquire() as c:
            evs = [r["event"] for r in await c.fetch(
                "SELECT event FROM connectivity_events WHERE component='broker' ORDER BY id")]
        assert evs == ["conectado", "desconectado", "conectado"]
        alerts = [a async for a in _rows(app, "SELECT kind, status FROM alerts ORDER BY id")]
        assert ("broker_disconnected", "encerrado") in alerts
        assert ("scene", "aberto") in alerts
    await broker.shutdown()


@pytest.mark.asyncio
async def test_retained_status_on_subscribe(clean_db):
    port = free_port()
    broker = await start_broker(port)
    async with aiomqtt.Client("127.0.0.1", port, identifier="atuador01") as atuador:
        await atuador.publish(fw.TOPIC_ACTUATOR_STATUS, b'{"device":"atuador01","estado":"escuro_executada"}',
                              qos=1, retain=True)
    settings = Settings(database_url=TEST_DSN, mqtt_host="127.0.0.1", mqtt_port=port)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        svc = app.state.service
        await wait_for(lambda: _ret(svc.actuator["confirmed"] is not None))
        c = svc.actuator["confirmed"]
        assert c["retained"] is True and c["match_status"] == "retido_inicial"
        assert c["leds"] == [False, True, False, False]
    await broker.shutdown()


@pytest.mark.asyncio
async def test_api_rules_export_and_websocket(clean_db):
    settings = Settings(database_url=TEST_DSN, mqtt_enabled=False)
    app = create_app(settings, start_background=False)
    async with app.router.lifespan_context(app):
        svc = app.state.service
        for raw in (90, 300, 700, 1800):
            await svc.handle(fw.TOPIC_SENSOR_TELEMETRY, json.dumps({"leitura": raw}).encode())
        await svc.handle(fw.TOPIC_COMMAND, b'{"cena":"alta"}')

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            cfg = (await http.get("/api/config")).json()
            assert cfg["firmware"]["topics"]["command"] == fw.TOPIC_COMMAND
            assert "password" not in json.dumps(cfg).lower()

            s = (await http.get("/api/stats")).json()
            assert s["readings"]["min"] == 90 and s["readings"]["max"] == 1800 and s["readings"]["count"] == 4

            page = (await http.get("/api/readings", params={"limit": 2, "offset": 2})).json()
            assert page["total"] == 4 and [i["raw"] for i in page["items"]] == [300, 90]

            r = await http.get("/api/readings", params={"from": "2030-01-01T00:00:00Z", "to": "2020-01-01T00:00:00Z"})
            assert r.status_code == 422

            rules = (await http.get("/api/alert-rules")).json()
            silence = next(x for x in rules if x["kind"] == "silence")
            bad = await http.put(f"/api/alert-rules/{silence['id']}", json={"enabled": True})
            assert bad.status_code == 422
            ok = await http.put(f"/api/alert-rules/{silence['id']}",
                                json={"enabled": True, "params": {"component": "sensor", "seconds": 60}})
            assert ok.status_code == 200, ok.text
            assert ok.json()["enabled"]
            builtin_del = await http.delete(f"/api/alert-rules/{silence['id']}")
            assert builtin_del.status_code == 409

            csv_resp = await http.get("/api/export/readings", params={"format": "csv"})
            assert csv_resp.status_code == 200 and "attachment" in csv_resp.headers["content-disposition"]
            rows = list(csv.reader(io.StringIO(csv_resp.text)))
            assert rows[0][:3] == ["id", "received_at", "raw"] and len(rows) == 5

            js = (await http.get("/api/export/commands", params={"format": "json"})).json()
            assert js[0]["cena"] == "alta"
            assert (await http.get("/api/export/nada")).status_code == 404

    # WebSocket: snapshot inicial + evento em tempo real
    from starlette.testclient import TestClient
    app2 = create_app(settings, start_background=False)
    with TestClient(app2) as tc, tc.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "state" and first["data"]["sensor"]["last_reading"]["raw"] == 1800
        tc.portal.call(app2.state.service.handle, fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura":42}')
        types = set()
        for _ in range(4):
            msg = json.loads(ws.receive_text())
            types.add(msg["type"])
            if msg["type"] == "reading":
                assert msg["data"]["raw"] == 42
                break
        assert "reading" in types


async def _ret(v):
    return v


async def _rows(app, sql):
    async with app.state.pool.acquire() as c:
        for r in await c.fetch(sql):
            yield tuple(r.values())
