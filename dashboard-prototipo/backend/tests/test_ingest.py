"""Ingestão + persistência no PostgreSQL real."""
from datetime import datetime, timedelta, timezone

import pytest

from app import firmware as fw
from app import queries as q
from tests.conftest import build_service

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CMD = fw.TOPIC_COMMAND
ST = fw.TOPIC_ACTUATOR_STATUS


def cmd(cena):
    return f'{{"cena":"{cena}"}}'.encode()


def status(cena):
    return f'{{"device":"atuador01","estado":"{cena}_executada"}}'.encode()


@pytest.mark.asyncio
async def test_command_then_confirmation_is_matched(service, pool):
    r1 = await service.handle(CMD, cmd("alta"), received_at=T0)
    assert r1["command"]["status"] == "aguardando"
    assert service.sync_state() == "aguardando_confirmacao"

    r2 = await service.handle(ST, status("alta"), received_at=T0 + timedelta(milliseconds=180))
    c = r2["confirmation"]
    assert c["match_status"] == "confirmou_comando" and c["command_id"] == r1["command"]["id"]
    assert c["leds"] == [False, False, True, False]
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM scene_commands WHERE id=$1", r1["command"]["id"])
    assert row["status"] == "confirmado" and row["latency_ms"] == 180
    assert service.sync_state() == "sincronizado"
    assert {"command", "confirmation", "state"} <= set(service.hub.types())


@pytest.mark.asyncio
async def test_commanded_vs_confirmed_divergence(service):
    await service.handle(CMD, cmd("extrema"), received_at=T0)
    await service.handle(ST, status("escuro"), received_at=T0 + timedelta(seconds=1))
    # confirmação de outra cena não confirma o comando
    assert service.sensor["last_command"]["status"] == "aguardando"
    assert service.actuator["confirmed"]["match_status"] == "sem_comando_correspondente"
    assert service.sync_state() == "aguardando_confirmacao"


@pytest.mark.asyncio
async def test_retained_status_is_not_counted_as_confirmation(service):
    r = await service.handle(ST, status("ambiente"), retained=True, received_at=T0)
    assert r["confirmation"]["match_status"] == "retido_inicial"
    assert service.actuator["confirmed"]["retained"] is True


@pytest.mark.asyncio
async def test_superseded_commands(service, pool):
    a = await service.handle(CMD, cmd("alta"), received_at=T0)
    await service.handle(CMD, cmd("extrema"), received_at=T0 + timedelta(milliseconds=300))
    await service.handle(ST, status("extrema"), received_at=T0 + timedelta(milliseconds=500))
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM scene_commands WHERE id=$1", a["command"]["id"])
    assert st == "substituido"


@pytest.mark.asyncio
async def test_invalid_and_unhandled_messages_are_persisted(service, pool):
    r = await service.handle(CMD, b'{"cena": ', received_at=T0)
    assert r["status"] == "invalido"
    r = await service.handle("iot/luzambiente/atuador/servo", b'{"pos":10}', received_at=T0)
    assert r["status"] == "nao_tratado"
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT parse_status, error_reason FROM mqtt_messages ORDER BY id")
        ev = await conn.fetch("SELECT category FROM v_events")
    assert [(x["parse_status"], x["error_reason"]) for x in rows] == [
        ("invalido", "json_invalido"), ("nao_tratado", None)]
    assert [e["category"] for e in ev] == ["mensagem_invalida"]
    assert service.stats["invalidas"] == 1
    assert "message_invalid" in service.hub.types()


@pytest.mark.asyncio
async def test_state_survives_restart(service, pool):
    await service.handle(fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura":1200}', received_at=T0)
    await service.handle(CMD, cmd("extrema"), received_at=T0)
    await service.handle(ST, status("extrema"), received_at=T0 + timedelta(milliseconds=90))
    restarted = await build_service(pool)
    assert restarted.sensor["last_command"]["cena"] == "extrema"
    assert restarted.sensor["last_reading"]["raw"] == 1200
    assert restarted.actuator["confirmed"]["leds"] == [True, True, True, True]
    assert restarted.sync_state() == "sincronizado"
    assert any(a["kind"] == "scene" for a in restarted.alerts.snapshot_open())


@pytest.mark.asyncio
async def test_scene_alert_opens_and_closes(service, pool):
    await service.handle(CMD, cmd("extrema"), received_at=T0)
    assert len(service.alerts.open) == 1
    await service.handle(CMD, cmd("alta"), received_at=T0 + timedelta(minutes=2))
    assert service.alerts.open == {}
    async with pool.acquire() as conn:
        a = await conn.fetchrow("SELECT * FROM alerts")
    assert a["status"] == "encerrado" and a["closed_at"] == T0 + timedelta(minutes=2)


@pytest.mark.asyncio
async def test_rules_without_threshold_cannot_be_enabled(service):
    rule = next(r for r in service.alerts.rules.values() if r["kind"] == "raw_above")
    with pytest.raises(ValueError):
        await service.alerts.update_rule(rule["id"], name=None, enabled=True, severity=None, params=None)
    r = await service.alerts.update_rule(rule["id"], name=None, enabled=True, severity=None,
                                         params={"threshold": 2000})
    assert r["enabled"] and r["params"] == {"threshold": 2000}
    await service.handle(fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura":2500}', received_at=T0)
    assert rule["id"] in service.alerts.open


@pytest.mark.asyncio
async def test_confirmation_timeout_marks_failure(service, pool):
    rule = next(r for r in service.alerts.rules.values() if r["kind"] == "confirmation_timeout")
    await service.alerts.update_rule(rule["id"], name=None, enabled=True, severity=None, params={"ms": 500})
    old = datetime.now(timezone.utc) - timedelta(seconds=5)
    r = await service.handle(CMD, cmd("alta"), received_at=old)
    await service.tick()
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM scene_commands WHERE id=$1", r["command"]["id"])
        ev = await conn.fetchval("SELECT event FROM connectivity_events WHERE component='atuador'")
    assert st == "sem_confirmacao" and ev == "falha_confirmacao"
    assert rule["id"] in service.alerts.open
    # confirmação tardia ainda casa e encerra o alerta
    await service.handle(ST, status("alta"))
    assert rule["id"] not in service.alerts.open
    assert service.sensor["last_command"]["status"] == "confirmado"


@pytest.mark.asyncio
async def test_broker_transitions_recorded_once(service, pool):
    await service.set_broker("conectando", host="h", port=1)
    await service.set_broker("desconectado", error="x")
    await service.set_broker("conectando")
    await service.set_broker("desconectado", error="x")
    await service.set_broker("conectado")
    async with pool.acquire() as conn:
        evs = [r["event"] for r in await conn.fetch("SELECT event FROM connectivity_events ORDER BY id")]
    assert evs == ["desconectado", "conectado"]


@pytest.mark.asyncio
async def test_demo_data_is_isolated(pool):
    real = await build_service(pool, is_demo=False)
    demo = await build_service(pool, is_demo=True)
    await demo.handle(fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura":100}', received_at=T0)
    await real.handle(fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura":900}', received_at=T0)
    rng = dict(frm=T0 - timedelta(hours=1), to=T0 + timedelta(hours=1))
    assert (await q.stats(pool, is_demo=False, **rng))["readings"]["max"] == 900
    assert (await q.stats(pool, is_demo=True, **rng))["readings"]["max"] == 100


@pytest.mark.asyncio
async def test_queries_period_pagination_stats_and_scenes(service, pool):
    raws = [100, 200, 500, 1500, 600, 120]
    for i, raw in enumerate(raws):
        t = T0 + timedelta(minutes=i)
        await service.handle(fw.TOPIC_SENSOR_TELEMETRY, f'{{"leitura":{raw}}}'.encode(), received_at=t)
        await service.handle(CMD, cmd(fw.classify(raw)), received_at=t)
    frm, to = T0, T0 + timedelta(minutes=6)

    p1 = await q.page(pool, "readings", is_demo=False, frm=frm, to=to, limit=4, offset=0)
    p2 = await q.page(pool, "readings", is_demo=False, frm=frm, to=to, limit=4, offset=4)
    assert p1["total"] == 6 and len(p1["items"]) == 4 and len(p2["items"]) == 2
    assert [x["raw"] for x in p1["items"] + p2["items"]] == list(reversed(raws))

    narrow = await q.page(pool, "readings", is_demo=False, frm=T0 + timedelta(minutes=2),
                          to=T0 + timedelta(minutes=3), limit=10, offset=0)
    assert [x["raw"] for x in narrow["items"]] == [1500, 500]

    s = await q.stats(pool, is_demo=False, frm=frm, to=to)
    assert s["readings"] == {**s["readings"], "min": 100, "max": 1500, "count": 6}
    assert s["readings"]["avg"] == pytest.approx(sum(raws) / 6)

    a = await q.scene_analysis(pool, is_demo=False, frm=frm, to=to)
    assert [i["cena"] for i in a["intervals"]] == ["escuro", "ambiente", "alta", "extrema", "alta", "escuro"]
    dist = {d["cena"]: d for d in a["distribution"]}
    assert dist["alta"]["duration_s"] == 120 and dist["alta"]["count"] == 2
    assert a["intense_periods"][0]["duration_s"] == 180  # alta+extrema+alta contínuos
    assert a["intense_periods"][0]["extrema_s"] == 60

    series = await q.reading_series(pool, is_demo=False, frm=frm, to=to, bucket=120)
    assert sum(p["n"] for p in series["points"]) == 6
