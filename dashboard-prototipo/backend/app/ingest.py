"""Pipeline de ingestão: mensagem MQTT -> validação -> PostgreSQL -> estado -> WebSocket -> alertas.

Usado tanto pelo cliente MQTT real quanto pelo modo demonstração; a única
diferença é is_demo, que separa os dados em todas as tabelas.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from . import firmware as fw
from . import parsing as p
from .alerts import AlertEngine
from .hub import Hub

log = logging.getLogger(__name__)

# Janela máxima para casar uma confirmação com um comando anterior.
MATCH_WINDOW_S = 300


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryService:
    def __init__(self, pool: asyncpg.Pool, hub: Hub, alerts: AlertEngine, *, is_demo: bool,
                 store_raw_payloads: bool = True) -> None:
        self.pool = pool
        self.hub = hub
        self.alerts = alerts
        self.is_demo = is_demo
        self.store_raw = store_raw_payloads
        self._lock = asyncio.Lock()
        self.started_at = utcnow()
        self._device_ids: dict[tuple[str, str], int] = {}
        self.stats = {"recebidas": 0, "invalidas": 0, "erros": 0, "nao_tratadas": 0}
        self.broker: dict[str, Any] = {"status": "demo" if is_demo else "desconectado", "since": self.started_at,
                                       "host": None, "port": None, "last_error": None, "attempts": 0}
        self.sensor: dict[str, Any] = {"last_message_at": None, "last_command": None, "last_reading": None,
                                       "telemetry_seen": False, "presence": None}
        self.actuator: dict[str, Any] = {"device": None, "last_message_at": None, "confirmed": None,
                                         "presence": None}
        self.last_message_at: datetime | None = None
        self._broker_recorded: str | None = None

    # ------------------------------------------------------------------ estado
    async def restore(self) -> None:
        """Reconstrói o estado a partir do banco (persistência entre reinícios)."""
        d = self.is_demo
        async with self.pool.acquire() as c:
            cmd = await c.fetchrow("SELECT * FROM scene_commands WHERE is_demo=$1 ORDER BY received_at DESC, id DESC LIMIT 1", d)
            conf = await c.fetchrow("SELECT * FROM actuator_confirmations WHERE is_demo=$1 ORDER BY received_at DESC, id DESC LIMIT 1", d)
            rd = await c.fetchrow("SELECT * FROM sensor_readings WHERE is_demo=$1 ORDER BY received_at DESC, id DESC LIMIT 1", d)
            last = await c.fetchrow(
                "SELECT max(received_at) FILTER (WHERE origin='sensor') s, max(received_at) FILTER (WHERE origin='atuador') a,"
                " max(received_at) m FROM mqtt_messages WHERE is_demo=$1", d)
            for comp, target in (("sensor", self.sensor), ("atuador", self.actuator)):
                pr = await c.fetchrow(
                    "SELECT occurred_at, event FROM connectivity_events WHERE is_demo=$1 AND component=$2"
                    " AND event IN ('online','offline') ORDER BY occurred_at DESC LIMIT 1", d, comp)
                if pr:
                    target["presence"] = {"status": pr["event"], "at": pr["occurred_at"]}
        if cmd:
            self.sensor["last_command"] = self._cmd_view(cmd)
        if conf:
            self.actuator["confirmed"] = self._conf_view(conf)
            self.actuator["device"] = conf and await self._device_key(conf["device_id"])
        if rd:
            self.sensor["last_reading"] = self._reading_view(rd)
            self.sensor["telemetry_seen"] = True
        self.sensor["last_message_at"] = last["s"]
        self.actuator["last_message_at"] = last["a"]
        self.last_message_at = last["m"]

    async def _device_key(self, device_id: int | None) -> str | None:
        if device_id is None:
            return None
        async with self.pool.acquire() as c:
            return await c.fetchval("SELECT device_key FROM devices WHERE id=$1", device_id)

    @staticmethod
    def _cmd_view(r) -> dict:
        return {"id": r["id"], "cena": r["cena"], "known_scene": r["known_scene"], "at": r["received_at"],
                "previous": r["previous_cena"], "status": r["status"], "confirmed_at": r["confirmed_at"],
                "latency_ms": r["latency_ms"]}

    @staticmethod
    def _conf_view(r) -> dict:
        return {"id": r["id"], "cena": r["cena"], "estado": r["estado"], "at": r["received_at"],
                "retained": r["retained"], "match_status": r["match_status"], "command_id": r["command_id"],
                "leds": [r["led1"], r["led2"], r["led3"], r["led4"]], "known_scene": r["known_scene"]}

    @staticmethod
    def _reading_view(r) -> dict:
        return {"id": r["id"], "raw": r["raw"], "cena_computed": r["cena_computed"],
                "cena_reported": r["cena_reported"], "at": r["received_at"], "uptime_ms": r["uptime_ms"]}

    def sync_state(self) -> str:
        cmd, conf = self.sensor["last_command"], self.actuator["confirmed"]
        if not cmd and not conf:
            return "sem_dados"
        if cmd and cmd["status"] == "aguardando":
            return "aguardando_confirmacao"
        if cmd and cmd["status"] == "sem_confirmacao":
            return "sem_confirmacao"
        if cmd and conf and fw.actuator_view_of_scene(cmd["cena"]) == conf["cena"]:
            return "sincronizado"
        if not cmd:
            return "sem_comando"
        if not conf:
            return "sem_confirmacao"
        return "divergente"

    def snapshot(self) -> dict:
        return {
            "now": utcnow(),
            "demo": self.is_demo,
            "started_at": self.started_at,
            "broker": self.broker,
            "sensor": self.sensor,
            "actuator": self.actuator,
            "sync": self.sync_state(),
            "last_message_at": self.last_message_at,
            "stats": self.stats,
            "open_alerts": self.alerts.snapshot_open(),
            "ws_clients": self.hub.client_count,
        }

    async def _push_state(self) -> None:
        await self.hub.broadcast("state", self.snapshot())

    # ----------------------------------------------------------------- broker
    async def set_broker(self, status: str, *, host: str | None = None, port: int | None = None,
                         error: str | None = None, attempts: int | None = None) -> None:
        prev = self.broker["status"]
        self.broker.update(status=status, last_error=error if status != "conectado" else None)
        if host is not None:
            self.broker["host"], self.broker["port"] = host, port
        if attempts is not None:
            self.broker["attempts"] = attempts
        if status != prev:
            self.broker["since"] = utcnow()
            # registra só transições reais conectado <-> desconectado (não cada tentativa)
            if status in ("conectado", "desconectado") and status != self._broker_recorded:
                self._broker_recorded = status
                async with self.pool.acquire() as c:
                    await c.execute(
                        "INSERT INTO connectivity_events (component, event, detail, is_demo) VALUES ('broker',$1,$2,$3)",
                        status, {"host": self.broker["host"], "porta": self.broker["port"], "erro": error}, self.is_demo)
                await self.hub.broadcast("connectivity", {"component": "broker", "event": status, "at": utcnow(),
                                                          "detail": {"erro": error}})
                await self.alerts.on_broker(status == "conectado", error)
        await self._push_state()

    # --------------------------------------------------------------- ingestão
    async def handle(self, topic: str, payload: bytes, *, qos: int | None = None, retained: bool = False,
                     received_at: datetime | None = None) -> dict:
        async with self._lock:
            return await self._handle(topic, payload, qos, retained, received_at or utcnow())

    async def _ensure_device(self, c: asyncpg.Connection, role: str, key: str, at: datetime) -> int:
        cached = self._device_ids.get((role, key))
        if cached:
            await c.execute("UPDATE devices SET last_seen_at=$2 WHERE id=$1 AND last_seen_at < $2", cached, at)
            return cached
        did = await c.fetchval(
            "INSERT INTO devices (role, device_key, first_seen_at, last_seen_at) VALUES ($1,$2,$3,$3)"
            " ON CONFLICT (role, device_key) DO UPDATE SET last_seen_at=GREATEST(devices.last_seen_at, EXCLUDED.last_seen_at)"
            " RETURNING id", role, key, at)
        self._device_ids[(role, key)] = did
        return did

    async def _handle(self, topic: str, payload: bytes, qos, retained: bool, at: datetime) -> dict:
        self.stats["recebidas"] += 1
        parsed = p.parse(topic, payload)
        origin = p.topic_origin(topic)
        text = payload.decode("utf-8", "replace") if self.store_raw else None
        if isinstance(parsed, p.ParseError):
            status = "invalido"
        elif isinstance(parsed, p.UnhandledMsg):
            status = "nao_tratado"
        else:
            status = "ok"

        result: dict[str, Any] = {"status": status, "topic": topic}
        try:
            async with self.pool.acquire() as c, c.transaction():
                msg_id = await c.fetchval(
                    "INSERT INTO mqtt_messages (received_at, topic, origin, payload, payload_bytes, qos, retained,"
                    " parse_status, error_reason, error_details, is_demo) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)"
                    " RETURNING id",
                    at, topic, origin, text[:p.MAX_PAYLOAD_BYTES] if text else None, len(payload), qos, retained,
                    status, getattr(parsed, "reason", None), getattr(parsed, "details", None), self.is_demo)
                result["message_id"] = msg_id
                if isinstance(parsed, p.CommandMsg):
                    result["command"] = await self._store_command(c, parsed, msg_id, at)
                elif isinstance(parsed, p.ConfirmationMsg):
                    result["confirmation"] = await self._store_confirmation(c, parsed, msg_id, at, retained)
                elif isinstance(parsed, p.TelemetryMsg):
                    result["reading"] = await self._store_reading(c, parsed, msg_id, at)
                elif isinstance(parsed, p.ConnectionMsg):
                    result["presence"] = await self._store_presence(c, parsed, at, retained)
        except Exception as e:  # falha de banco ou bug: registra fora da transação abortada
            log.exception("erro ao processar mensagem de %s", topic)
            self.stats["erros"] += 1
            try:
                async with self.pool.acquire() as c:
                    await c.execute(
                        "INSERT INTO mqtt_messages (received_at, topic, origin, payload, payload_bytes, qos, retained,"
                        " parse_status, error_reason, error_details, is_demo)"
                        " VALUES ($1,$2,$3,$4,$5,$6,$7,'erro_processamento',$8,$9,$10)",
                        at, topic, origin, text, len(payload), qos, retained, type(e).__name__,
                        {"erro": str(e)[:500]}, self.is_demo)
            except Exception:
                log.exception("não foi possível registrar o erro de processamento")
            await self.hub.broadcast("message_error", {"topic": topic, "at": at, "erro": type(e).__name__})
            return {"status": "erro_processamento", "topic": topic}

        # --- pós-commit: estado, tempo real, alertas
        if origin == "sensor":
            self.sensor["last_message_at"] = at
        elif origin == "atuador":
            self.actuator["last_message_at"] = at
        self.last_message_at = at

        if status == "invalido":
            self.stats["invalidas"] += 1
            await self.hub.broadcast("message_invalid", {"id": result["message_id"], "topic": topic, "at": at,
                                                         "reason": parsed.reason, "payload": (text or "")[:200]})
        elif status == "nao_tratado":
            self.stats["nao_tratadas"] += 1

        if "command" in result:
            await self.hub.broadcast("command", result["command"])
            await self.alerts.on_scene(result["command"]["cena"], at)
        if "confirmation" in result:
            await self.hub.broadcast("confirmation", result["confirmation"])
            conf = result["confirmation"]
            if conf["match_status"] == "confirmou_comando":
                for rule in self.alerts.enabled("confirmation_timeout"):
                    await self.alerts.close_alert(rule["id"], at, "atuador confirmou")
        if "reading" in result:
            await self.hub.broadcast("reading", result["reading"])
            await self.alerts.on_reading(result["reading"]["raw"], at)
        if "presence" in result and result["presence"]:
            pr = result["presence"]
            await self.hub.broadcast("connectivity", pr)
            await self.alerts.on_device_presence(pr["component"], pr["event"] == "online", at)
        await self._check_silence(at)
        await self._push_state()
        return result

    async def _store_command(self, c, m: p.CommandMsg, msg_id: int, at: datetime) -> dict:
        did = await self._ensure_device(c, "sensor", fw.SENSOR_CLIENT_ID, at)
        prev = self.sensor["last_command"]["cena"] if self.sensor["last_command"] else None
        row = await c.fetchrow(
            "INSERT INTO scene_commands (message_id, device_id, received_at, cena, known_scene, previous_cena, is_demo)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *", msg_id, did, at, m.cena, m.known_scene, prev, self.is_demo)
        view = self._cmd_view(row)
        self.sensor["last_command"] = view
        return view

    async def _store_confirmation(self, c, m: p.ConfirmationMsg, msg_id: int, at: datetime, retained: bool) -> dict:
        did = await self._ensure_device(c, "atuador", m.device, at)
        cmd = None
        if retained:
            # Mensagem retida entregue na (re)assinatura: estado antigo de horário desconhecido.
            match = "retido_inicial"
        else:
            cmd = await c.fetchrow(
                "SELECT id, received_at FROM scene_commands WHERE is_demo=$1"
                " AND status IN ('aguardando','sem_confirmacao') AND left(cena, $2)=$3"
                " AND received_at <= $4 AND received_at >= $4 - make_interval(secs => $5)"
                " ORDER BY received_at DESC, id DESC LIMIT 1 FOR UPDATE",
                self.is_demo, fw.ACTUATOR_SCENE_MAXLEN, m.cena, at, MATCH_WINDOW_S)
            match = "confirmou_comando" if cmd else "sem_comando_correspondente"
        l1, l2, l3, l4 = m.leds
        row = await c.fetchrow(
            "INSERT INTO actuator_confirmations (message_id, device_id, received_at, estado, cena, known_scene, retained,"
            " led1, led2, led3, led4, command_id, match_status, is_demo)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING *",
            msg_id, did, at, m.estado, m.cena, m.known_scene, retained, l1, l2, l3, l4,
            cmd["id"] if cmd else None, match, self.is_demo)
        if cmd:
            latency = int((at - cmd["received_at"]).total_seconds() * 1000)
            upd = await c.fetchrow(
                "UPDATE scene_commands SET status='confirmado', confirmed_at=$2, confirmation_id=$3, latency_ms=$4"
                " WHERE id=$1 RETURNING *", cmd["id"], at, row["id"], latency)
            # comandos anteriores ainda pendentes foram sobrepostos pelo mais novo
            await c.execute(
                "UPDATE scene_commands SET status='substituido' WHERE is_demo=$1 AND status='aguardando'"
                " AND (received_at, id) < ($2, $3)", self.is_demo, cmd["received_at"], cmd["id"])
            if self.sensor["last_command"] and self.sensor["last_command"]["id"] in (upd["id"],):
                self.sensor["last_command"] = self._cmd_view(upd)
            elif self.sensor["last_command"] and self.sensor["last_command"]["status"] == "aguardando" \
                    and self.sensor["last_command"]["at"] < cmd["received_at"]:
                self.sensor["last_command"]["status"] = "substituido"
        view = self._conf_view(row)
        self.actuator["device"] = m.device
        # A retida só inicializa o estado confirmado se ainda não sabemos nada mais recente.
        if not retained or self.actuator["confirmed"] is None:
            self.actuator["confirmed"] = view
        return view

    async def _store_reading(self, c, m: p.TelemetryMsg, msg_id: int, at: datetime) -> dict:
        did = await self._ensure_device(c, "sensor", m.device or fw.SENSOR_CLIENT_ID, at)
        row = await c.fetchrow(
            "INSERT INTO sensor_readings (message_id, device_id, received_at, raw, cena_computed, cena_reported, uptime_ms, is_demo)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
            msg_id, did, at, m.raw, m.cena_computed, m.cena_reported, m.uptime_ms, self.is_demo)
        view = self._reading_view(row)
        self.sensor["last_reading"] = view
        self.sensor["telemetry_seen"] = True
        return view

    async def _store_presence(self, c, m: p.ConnectionMsg, at: datetime, retained: bool) -> dict:
        await self._ensure_device(c, m.component, m.device or (fw.SENSOR_CLIENT_ID if m.component == "sensor"
                                                               else fw.ACTUATOR_DEVICE_ID), at)
        detail = {"device": m.device, "retida": retained, "fonte": "LWT/anúncio"}
        await c.execute("INSERT INTO connectivity_events (occurred_at, component, event, detail, is_demo)"
                        " VALUES ($1,$2,$3,$4,$5)", at, m.component, m.status, detail, self.is_demo)
        target = self.sensor if m.component == "sensor" else self.actuator
        target["presence"] = {"status": m.status, "at": at, "retained": retained}
        return {"component": m.component, "event": m.status, "at": at, "detail": detail}

    # --------------------------------------------------------------- watchdog
    async def _check_silence(self, now: datetime) -> bool:
        changes = await self.alerts.check_silence(
            {"sensor": self.sensor["last_message_at"], "atuador": self.actuator["last_message_at"]},
            self.started_at, now)
        for rule, silent in changes:
            comp = rule["params"]["component"]
            ev = "silencio" if silent else "retomado"
            async with self.pool.acquire() as c:
                await c.execute("INSERT INTO connectivity_events (occurred_at, component, event, detail, is_demo)"
                                " VALUES ($1,$2,$3,$4,$5)", now, comp, ev,
                                {"limite_s": rule["params"]["seconds"]}, self.is_demo)
            await self.hub.broadcast("connectivity", {"component": comp, "event": ev, "at": now})
        return bool(changes)

    async def tick(self) -> None:
        """Executado periodicamente: confirmações atrasadas e ausência de mensagens."""
        now = utcnow()
        changed = False
        async with self._lock:
            for rule in self.alerts.enabled("confirmation_timeout"):
                ms = rule["params"]["ms"]
                async with self.pool.acquire() as c:
                    rows = await c.fetch(
                        "UPDATE scene_commands SET status='sem_confirmacao' WHERE is_demo=$1 AND status='aguardando'"
                        " AND received_at < $2::timestamptz - make_interval(secs => $3::float8) RETURNING *",
                        self.is_demo, now, ms / 1000)
                    for r in rows:
                        await c.execute(
                            "INSERT INTO connectivity_events (occurred_at, component, event, detail, is_demo)"
                            " VALUES ($1,'atuador','falha_confirmacao',$2,$3)",
                            now, {"comando_id": r["id"], "cena": r["cena"], "limite_ms": ms}, self.is_demo)
                for r in rows:
                    v = self._cmd_view(r)
                    if self.sensor["last_command"] and self.sensor["last_command"]["id"] == r["id"]:
                        self.sensor["last_command"] = v
                    await self.hub.broadcast("command", v)
                    await self.hub.broadcast("connectivity", {"component": "atuador", "event": "falha_confirmacao",
                                                              "at": now, "detail": {"cena": r["cena"]}})
                if rows:
                    changed = True
                    last = rows[-1]
                    await self.alerts.open_alert(
                        rule, f"Atuador não confirmou a cena '{last['cena']}' em {ms} ms",
                        {"comando_id": last["id"], "cena": last["cena"]}, now)
            changed = await self._check_silence(now) or changed
        if changed:
            await self._push_state()

    async def reevaluate(self) -> None:
        """Reaplica regras ao estado atual (após alteração de regra)."""
        async with self._lock:
            now = utcnow()
            if self.sensor["last_command"]:
                await self.alerts.on_scene(self.sensor["last_command"]["cena"], now)
            if self.sensor["last_reading"]:
                await self.alerts.on_reading(self.sensor["last_reading"]["raw"], now)
            if not self.is_demo:
                await self.alerts.on_broker(self.broker["status"] == "conectado", self.broker["last_error"])
            await self._check_silence(now)
        await self._push_state()
