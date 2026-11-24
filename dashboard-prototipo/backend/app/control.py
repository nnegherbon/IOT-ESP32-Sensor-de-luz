"""Controle no backend (contrato v1.1): regra de decisão remota (R8) e ciclo de comando com cmd_id (R4, R7).

O backend é o ÚNICO componente que publica comandos para o atuador. O sensor só mede e publica a telemetria.

Ciclo de um comando (tabela commands):
    enviado     o backend registrou e publicou (QoS 1)
    recebido    o atuador respondeu ack "recebido" (aceitou o JSON e vai processar)
    executado   ack "executado" (LEDs/servo agiram)      | rejeitado: ack "rejeitado" + motivo
    confirmado  o estado retido do atuador traz ultimo_cmd_id = cmd_id (e a interface reflete)
    sem_confirmacao  nenhum ack em ACK_TIMEOUT_S, mesmo após 1 retransmissão com o mesmo cmd_id
    falha_envio      o broker estava indisponível na hora de publicar
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from . import v1

log = logging.getLogger(__name__)

ACK_TIMEOUT_S = 3.0          # espera pelo ack antes de retransmitir (contrato §3)
CONFIRM_TIMEOUT_S = 8.0      # executado sem estado confirmando -> sem_confirmacao
RETRY_AFTER_REJECT_S = 6.0   # nova tentativa da regra depois de "intertravamento" (servo moveu há < 5 s)
OPEN_STATUSES = ("enviado", "recebido", "executado")

Publisher = Callable[[str, str, int, bool], Awaitable[None]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DecisionConfig:
    enabled: bool = True
    sensor: str = "sensor01"
    atuador: str = "atuador01"
    limite_ambiente: int = 150
    limite_alta: int = 400
    limite_extrema: int = 1000
    histerese: int = 40
    confirmacao_s: float = 3.0
    updated_at: datetime | None = None
    updated_by: str = "padrão"

    @property
    def limites(self) -> tuple[int, int, int]:
        return (self.limite_ambiente, self.limite_alta, self.limite_extrema)

    def classify(self, raw: int) -> str:
        n = sum(1 for lim in self.limites if raw >= lim)
        return v1.SCENES[n]

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "sensor": self.sensor, "atuador": self.atuador,
                "limite_ambiente": self.limite_ambiente, "limite_alta": self.limite_alta,
                "limite_extrema": self.limite_extrema, "histerese": self.histerese,
                "confirmacao_s": self.confirmacao_s, "updated_at": self.updated_at, "updated_by": self.updated_by}


class DecisionEngine:
    """Classifica a leitura em cena com histerese e tempo de confirmação (evita a cena "piscar")."""

    def __init__(self, cfg: DecisionConfig) -> None:
        self.cfg = cfg
        self.level: int | None = None
        self.candidate: int | None = None
        self.candidate_since: datetime | None = None

    def reset(self) -> None:
        self.level = self.candidate = self.candidate_since = None

    def _level_with_hysteresis(self, raw: int) -> int:
        lims, h = self.cfg.limites, self.cfg.histerese
        if self.level is None:
            return sum(1 for lim in lims if raw >= lim)
        n = self.level
        while n < 3 and raw >= lims[n] + h:
            n += 1
        while n > 0 and raw < lims[n - 1] - h:
            n -= 1
        return n

    def update(self, raw: int, at: datetime) -> str | None:
        """Retorna a cena decidida (estável). None enquanto não há decisão."""
        n = self._level_with_hysteresis(raw)
        if self.level is None:
            self.level = n
        elif n == self.level:
            self.candidate = None
        elif n != self.candidate:
            self.candidate, self.candidate_since = n, at
        elif (at - self.candidate_since).total_seconds() >= self.cfg.confirmacao_s:
            self.level, self.candidate = n, None
        return v1.SCENES[self.level]

    @property
    def scene(self) -> str | None:
        return v1.SCENES[self.level] if self.level is not None else None


class ControlService:
    def __init__(self, telemetry, *, is_demo: bool = False) -> None:
        self.t = telemetry                  # TelemetryService (pool, hub, alerts, estado da dashboard)
        self.pool = telemetry.pool
        self.hub = telemetry.hub
        self.alerts = telemetry.alerts
        self.is_demo = is_demo
        self.publisher: Publisher | None = None
        self.cfg = DecisionConfig()
        self.engine = DecisionEngine(self.cfg)
        self._lock = asyncio.Lock()
        self.sensors: dict[str, dict] = {}
        self.actuators: dict[str, dict] = {}
        self.last_reject_at: datetime | None = None
        self.decided_scene: str | None = None

    # ------------------------------------------------------------- carga
    async def load(self) -> None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT * FROM decision_config WHERE id=1")
            if r:
                self._apply_cfg(r)
            st = await c.fetch(
                "SELECT DISTINCT ON (device) * FROM actuator_states WHERE is_demo=$1"
                " ORDER BY device, received_at DESC, id DESC", self.is_demo)
            for s in st:
                self.actuators.setdefault(s["device"], {})["estado"] = self._estado_view(s)
            last = await c.fetch("SELECT * FROM commands WHERE is_demo=$1 ORDER BY sent_at DESC LIMIT 1", self.is_demo)
            if last:
                self.actuators.setdefault(last[0]["device"], {})["last_command"] = self.command_view(last[0])

    def _apply_cfg(self, r) -> None:
        self.cfg = DecisionConfig(enabled=r["enabled"], sensor=r["sensor"], atuador=r["atuador"],
                                  limite_ambiente=r["limite_ambiente"], limite_alta=r["limite_alta"],
                                  limite_extrema=r["limite_extrema"], histerese=r["histerese"],
                                  confirmacao_s=float(r["confirmacao_s"]), updated_at=r["updated_at"],
                                  updated_by=r["updated_by"])
        self.engine.cfg = self.cfg
        self.engine.reset()

    async def update_config(self, user: str, **changes: Any) -> dict:
        allowed = {"enabled", "limite_ambiente", "limite_alta", "limite_extrema", "histerese", "confirmacao_s"}
        bad = set(changes) - allowed
        if bad:
            raise ValueError(f"campos não editáveis: {sorted(bad)}")
        new = {**self.cfg.as_dict(), **{k: v for k, v in changes.items() if v is not None}}
        if not (0 < new["limite_ambiente"] < new["limite_alta"] < new["limite_extrema"] < 4095):
            raise ValueError("os limites devem ser crescentes: 0 < ambiente < alta < extrema < 4095")
        if not 0 <= new["histerese"] <= 500:
            raise ValueError("histerese deve estar entre 0 e 500")
        if not 0 <= float(new["confirmacao_s"]) <= 600:
            raise ValueError("confirmacao_s deve estar entre 0 e 600")
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                "UPDATE decision_config SET enabled=$1, limite_ambiente=$2, limite_alta=$3, limite_extrema=$4,"
                " histerese=$5, confirmacao_s=$6, updated_at=now(), updated_by=$7 WHERE id=1 RETURNING *",
                bool(new["enabled"]), int(new["limite_ambiente"]), int(new["limite_alta"]), int(new["limite_extrema"]),
                int(new["histerese"]), float(new["confirmacao_s"]), user)
        self._apply_cfg(r)
        await self.hub.broadcast("decision_config", self.cfg.as_dict())
        await self.evaluate(utcnow())
        return self.cfg.as_dict()

    # ------------------------------------------------------------- visões
    @staticmethod
    def command_view(r) -> dict:
        d = {k: r[k] for k in ("cmd_id", "device", "origem", "acao", "cena", "sombra", "modo", "duracao_s",
                               "requested_by", "reason", "status", "motivo", "sent_at", "received_at",
                               "executed_at", "confirmed_at", "retries", "duplicate_acks", "latency_ms")}
        return d

    @staticmethod
    def _estado_view(r) -> dict:
        return {"modo": r["modo"], "cena": r["cena"], "leds": list(r["leds"]), "sombra": r["sombra"],
                "servo_graus": r["servo_graus"], "manual_restante_s": r["manual_restante_s"],
                "ultimo_cmd_id": r["ultimo_cmd_id"], "motivo_seguro": r["motivo_seguro"],
                "at": r["received_at"], "retained": r["retained"]}

    def snapshot(self) -> dict:
        return {"decision": self.cfg.as_dict(), "decided_scene": self.decided_scene,
                "sensors": self.sensors, "actuators": self.actuators,
                "publisher": self.publisher is not None}

    # ------------------------------------------------- ingestão (na transação)
    async def store(self, c, m, msg_id: int, at: datetime, retained: bool) -> dict:
        """Grava a mensagem v1 já validada. Retorna chaves que o pipeline da dashboard entende."""
        out: dict[str, Any] = {"v1": m}
        if isinstance(m, v1.V1Telemetry):
            did = await self.t._ensure_device(c, "sensor", m.device, at)
            cena_calc = self.cfg.classify(m.raw)
            row = await c.fetchrow(
                "INSERT INTO sensor_readings (message_id, device_id, received_at, raw, cena_computed, cena_reported,"
                " uptime_ms, is_demo) VALUES ($1,$2,$3,$4,$5,NULL,$6,$7) RETURNING *",
                msg_id, did, at, m.raw, cena_calc, m.uptime_ms, self.is_demo)
            view = self.t._reading_view(row)
            self.t.sensor["last_reading"] = view
            self.t.sensor["telemetry_seen"] = True
            s = self.sensors.setdefault(m.device, {})
            gap = s.get("seq") is not None and m.seq > s["seq"] + 1
            s.update(seq=m.seq, raw=m.raw, at=at, sensor_ok=m.sensor_ok, falha=m.falha, rssi=m.rssi,
                     hora_sync=m.hora_sync, perdidas=(s.get("perdidas", 0) + (m.seq - s["seq"] - 1 if gap else 0)))
            out["reading"] = view
        elif isinstance(m, v1.V1Status):
            if m.role == "backend":
                return out
            await self.t._ensure_device(c, m.role, m.device, at)
            event = "online" if m.online else "offline"
            detail = {"device": m.device, "retida": retained, "fonte": "status v1 / LWT", "fw": m.fw, "ip": m.ip}
            await c.execute("INSERT INTO connectivity_events (occurred_at, component, event, detail, is_demo)"
                            " VALUES ($1,$2,$3,$4,$5)", at, m.role, event, detail, self.is_demo)
            target = self.t.sensor if m.role == "sensor" else self.t.actuator
            target["presence"] = {"status": event, "at": at, "retained": retained}
            info = (self.sensors if m.role == "sensor" else self.actuators).setdefault(m.device, {})
            info.update(online=m.online, fw=m.fw or info.get("fw"), ip=m.ip or info.get("ip"), status_at=at)
            out["presence"] = {"component": m.role, "event": event, "at": at, "detail": detail}
        elif isinstance(m, v1.V1Ack):
            out["ack"] = await self._store_ack(c, m, msg_id, at)
        elif isinstance(m, v1.V1Estado):
            out.update(await self._store_estado(c, m, msg_id, at, retained))
        return out

    async def _store_ack(self, c, m: v1.V1Ack, msg_id: int, at: datetime) -> dict:
        cmd = await c.fetchrow("SELECT * FROM commands WHERE cmd_id=$1 FOR UPDATE", m.cmd_id)
        await c.execute("INSERT INTO command_acks (message_id, cmd_id, device, received_at, resultado, motivo, known,"
                        " is_demo) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                        msg_id, m.cmd_id, m.device, at, m.resultado, m.motivo, cmd is not None, self.is_demo)
        if cmd is None:
            return {"cmd_id": m.cmd_id, "known": False}
        st = cmd["status"]
        duplicate = False
        if m.resultado == "recebido":
            if st == "enviado":
                cmd = await c.fetchrow("UPDATE commands SET status='recebido', received_at=$2 WHERE cmd_id=$1"
                                       " RETURNING *", m.cmd_id, at)
            else:
                duplicate = cmd["received_at"] is not None
        elif m.resultado == "executado":
            if st in ("enviado", "recebido", "sem_confirmacao"):
                cmd = await c.fetchrow(
                    "UPDATE commands SET status='executado', executed_at=$2, received_at=COALESCE(received_at,$2)"
                    " WHERE cmd_id=$1 RETURNING *", m.cmd_id, at)
            else:
                duplicate = True
        else:  # rejeitado
            if st in ("enviado", "recebido", "sem_confirmacao"):
                cmd = await c.fetchrow(
                    "UPDATE commands SET status='rejeitado', motivo=$3, executed_at=$2,"
                    " received_at=COALESCE(received_at,$2) WHERE cmd_id=$1 RETURNING *", m.cmd_id, at, m.motivo)
            else:
                duplicate = True
        if duplicate:
            cmd = await c.fetchrow("UPDATE commands SET duplicate_acks=duplicate_acks+1 WHERE cmd_id=$1 RETURNING *",
                                   m.cmd_id)
        return {"command": self.command_view(cmd), "duplicate": duplicate, "resultado": m.resultado}

    async def _store_estado(self, c, m: v1.V1Estado, msg_id: int, at: datetime, retained: bool) -> dict:
        out: dict[str, Any] = {}
        await self.t._ensure_device(c, "atuador", m.device, at)
        row = await c.fetchrow(
            "INSERT INTO actuator_states (message_id, device, received_at, modo, cena, leds, sombra, servo_graus,"
            " manual_restante_s, ultimo_cmd_id, motivo_seguro, retained, is_demo)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *",
            msg_id, m.device, at, m.modo, m.cena, list(m.leds), m.sombra, m.servo_graus, m.manual_restante_s,
            m.ultimo_cmd_id, m.motivo_seguro, retained, self.is_demo)
        prev = (self.actuators.get(m.device) or {}).get("estado")
        view = self._estado_view(row)
        self.actuators.setdefault(m.device, {})["estado"] = view
        out["estado"] = view
        out["estado_prev"] = prev

        # Sombra (posição comandada) para o painel existente
        if m.sombra is not None and (not prev or prev.get("sombra") != m.sombra or retained):
            sh = await c.fetchrow(
                "INSERT INTO shade_events (message_id, received_at, kind, command, position_deg, payload, is_demo)"
                " VALUES ($1,$2,'posicao',$3,$4,$5,$6) RETURNING *", msg_id, at, m.sombra, m.servo_graus,
                {"device": m.device, "estado": m.sombra, "graus": m.servo_graus, "_retida": retained}, self.is_demo)
            if not retained or self.t.actuator["shade"] is None:
                self.t.actuator["shade"] = self.t._shade_view(sh)

        # Confirmação do comando: o estado traz o último cmd_id executado
        if m.ultimo_cmd_id:
            cmd = await c.fetchrow("SELECT * FROM commands WHERE cmd_id=$1 FOR UPDATE", m.ultimo_cmd_id)
            if cmd and cmd["status"] in ("enviado", "recebido", "executado", "sem_confirmacao"):
                latency = int((at - cmd["sent_at"]).total_seconds() * 1000)
                cmd = await c.fetchrow(
                    "UPDATE commands SET status='confirmado', confirmed_at=$2, latency_ms=$3,"
                    " executed_at=COALESCE(executed_at,$2), received_at=COALESCE(received_at,$2)"
                    " WHERE cmd_id=$1 RETURNING *", m.ultimo_cmd_id, at, latency)
                out["confirmed"] = self.command_view(cmd)
                if cmd["scene_command_id"]:
                    await c.execute(
                        "UPDATE scene_commands SET status='confirmado', confirmed_at=$2, latency_ms=$3 WHERE id=$1",
                        cmd["scene_command_id"], at, latency)
        # Visão "confirmada" do painel (LEDs e cena que o atuador declarou)
        if m.cena is not None and (not prev or prev.get("cena") != m.cena or not retained):
            did = await self.t._ensure_device(c, "atuador", m.device, at)
            conf = await c.fetchrow(
                "INSERT INTO actuator_confirmations (message_id, device_id, received_at, estado, cena, known_scene,"
                " retained, led1, led2, led3, led4, command_id, match_status, is_demo)"
                " VALUES ($1,$2,$3,$4,$5,true,$6,$7,$8,$9,$10,NULL,$11,$12) RETURNING *",
                msg_id, did, at, f"{m.cena}_executada", m.cena, retained, *m.leds,
                "retido_inicial" if retained else ("confirmou_comando" if "confirmed" in out
                                                   else "sem_comando_correspondente"), self.is_demo)
            if not retained or self.t.actuator["confirmed"] is None:
                self.t.actuator["confirmed"] = self.t._conf_view(conf)
            self.t.actuator["device"] = m.device
        return out

    # --------------------------------------------------------- pós-commit
    async def after(self, result: dict) -> None:
        m = result.get("v1")
        at = utcnow()
        if isinstance(m, v1.V1Telemetry):
            fault = None if m.sensor_ok else (m.falha or "sensor_falhou")
            await self.alerts.on_sensor_fault(m.device, fault, m.raw, at)
            if m.device == self.cfg.sensor:
                if fault is None:
                    self.decided_scene = self.engine.update(m.raw, at)
                    await self.alerts.on_scene(self.decided_scene, at)
                await self.evaluate(at, sensor_fault=fault)
        elif isinstance(m, v1.V1Ack) and result.get("ack", {}).get("command"):
            ack = result["ack"]
            cmd = ack["command"]
            self.actuators.setdefault(cmd["device"], {})["last_command"] = cmd
            await self.hub.broadcast("v1_command", cmd)
            if cmd["status"] == "rejeitado" and not ack["duplicate"]:
                self.last_reject_at = at
                await self.alerts.on_command_result(cmd["cmd_id"], False, cmd["motivo"], at)
        elif isinstance(m, v1.V1Estado):
            est = result["estado"]
            prev = result.get("estado_prev") or {}
            await self.hub.broadcast("v1_estado", {"device": m.device, **est})
            if "confirmed" in result:
                cmd = result["confirmed"]
                self.actuators.setdefault(cmd["device"], {})["last_command"] = cmd
                await self.hub.broadcast("v1_command", cmd)
                await self.alerts.on_command_result(cmd["cmd_id"], True, None, at)
            if (est["modo"] == "seguro") != (prev.get("modo") == "seguro") or not prev:
                await self.alerts.on_safe_mode(m.device, est["modo"] == "seguro", est.get("motivo_seguro"), at)
            if est["modo"] == "auto" and prev.get("modo") != "auto":
                await self.evaluate(at)
        elif isinstance(m, v1.V1Status) and m.role == "atuador" and m.online:
            await self.evaluate(at)

    # --------------------------------------------------------- decisão (R8)
    async def evaluate(self, at: datetime, sensor_fault: str | None = None) -> dict | None:
        """Se a cena decidida difere da cena do atuador em modo AUTO, gera um comando (mesmo ciclo do R7)."""
        cfg = self.cfg
        scene = self.engine.scene
        if not cfg.enabled or scene is None or sensor_fault:
            return None
        act = self.actuators.get(cfg.atuador) or {}
        est = act.get("estado")
        if act.get("online") is False or not est or est["modo"] != "auto" or est["cena"] == scene:
            return None
        if self.last_reject_at and (at - self.last_reject_at).total_seconds() < RETRY_AFTER_REJECT_S:
            return None
        async with self.pool.acquire() as c:
            busy = await c.fetchval(
                "SELECT count(*) FROM commands WHERE device=$1 AND is_demo=$2 AND status IN ('enviado','recebido',"
                "'executado') AND sent_at > $3", cfg.atuador, self.is_demo, at - timedelta(seconds=CONFIRM_TIMEOUT_S))
        if busy:
            return None
        raw = (self.sensors.get(cfg.sensor) or {}).get("raw")
        reason = f"leitura {raw} → cena {scene} (atuador estava em {est['cena'] or 'nenhuma'})"
        try:
            return await self.issue(cfg.atuador, origem="auto", acao="aplicar", cena=scene,
                                    requested_by="regra:cena_por_luminosidade", reason=reason)
        except RuntimeError as e:
            log.warning("regra não publicou: %s", e)
            return None

    # ------------------------------------------------------------ comandos
    async def _next_cmd_id(self, c, now: datetime) -> str:
        day = now.strftime("%Y%m%d")
        n = await c.fetchval("SELECT count(*) FROM commands WHERE cmd_id LIKE $1", f"c-{day}-%")
        return f"c-{day}-{n + 1:06d}"

    async def issue(self, device: str, *, origem: str, acao: str, requested_by: str, cena: str | None = None,
                    modo: str | None = None, duracao_s: int | None = None, reason: str | None = None) -> dict:
        if not v1.DEVICE_RE.match(device):
            raise ValueError("device inválido")
        async with self._lock:
            now = utcnow()
            async with self.pool.acquire() as c, c.transaction():
                cmd_id = await self._next_cmd_id(c, now)
                payload = v1.build_command(cmd_id, origem=origem, acao=acao, cena=cena, modo=modo,
                                           duracao_s=duracao_s, now=now)
                text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                topic = v1.topic_comando(device)
                msg_id = await c.fetchval(
                    "INSERT INTO mqtt_messages (received_at, topic, origin, payload, payload_bytes, qos, retained,"
                    " parse_status, is_demo) VALUES ($1,$2,'backend',$3,$4,1,false,'ok',$5) RETURNING id",
                    now, topic, text, len(text.encode()), self.is_demo)
                scene_id = None
                if acao == "aplicar":
                    prev = (self.actuators.get(device) or {}).get("estado", {}) or {}
                    scene_id = await c.fetchval(
                        "INSERT INTO scene_commands (message_id, received_at, cena, known_scene, previous_cena, is_demo)"
                        " VALUES ($1,$2,$3,true,$4,$5) RETURNING id", msg_id, now, cena, prev.get("cena"), self.is_demo)
                row = await c.fetchrow(
                    "INSERT INTO commands (cmd_id, device, origem, acao, cena, sombra, modo, duracao_s, payload,"
                    " requested_by, reason, status, sent_at, scene_command_id, is_demo)"
                    " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'enviado',$12,$13,$14) RETURNING *",
                    cmd_id, device, origem, acao, payload.get("cena"), payload.get("sombra"), payload.get("modo"),
                    payload.get("duracao_s"), payload, requested_by, reason, now, scene_id, self.is_demo)
            ok, err = await self._publish(topic, text)
            if not ok:
                async with self.pool.acquire() as c:
                    row = await c.fetchrow("UPDATE commands SET status='falha_envio', motivo=$2 WHERE cmd_id=$1"
                                           " RETURNING *", cmd_id, err)
            view = self.command_view(row)
        self.actuators.setdefault(device, {})["last_command"] = view
        log.info("comando %s %s/%s por %s: %s", cmd_id, acao, cena or modo, requested_by, view["status"])
        await self.hub.broadcast("v1_command", view)
        if not ok:
            await self.alerts.on_command_result(cmd_id, False, f"falha_envio: {err}", utcnow())
        return view

    async def resend(self, cmd_id: str, requested_by: str) -> dict:
        """Republica o MESMO comando (mesmo cmd_id). Serve para demonstrar a idempotência do atuador (R10)."""
        async with self.pool.acquire() as c:
            row = await c.fetchrow("SELECT * FROM commands WHERE cmd_id=$1", cmd_id)
        if not row:
            raise KeyError(cmd_id)
        text = json.dumps(row["payload"], separators=(",", ":"), ensure_ascii=False)
        ok, err = await self._publish(v1.topic_comando(row["device"]), text)
        if not ok:
            raise RuntimeError(err)
        log.info("comando %s republicado por %s (teste de duplicidade)", cmd_id, requested_by)
        return self.command_view(row)

    async def publish_config(self, role: str, device: str, config: dict) -> dict:
        payload = {"v": 1, **config}
        ok, err = await self._publish(v1.topic_config(role, device), json.dumps(payload, separators=(",", ":")),
                                      retain=True)
        if not ok:
            raise RuntimeError(err)
        return payload

    async def _publish(self, topic: str, text: str, retain: bool = False) -> tuple[bool, str | None]:
        if self.publisher is None:
            return False, "backend sem conexão com o broker"
        try:
            await self.publisher(topic, text, 1, retain)
            return True, None
        except Exception as e:  # broker caiu no meio
            return False, f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------- watchdog
    async def tick(self) -> None:
        now = utcnow()
        async with self.pool.acquire() as c:
            due = await c.fetch(
                "SELECT * FROM commands WHERE is_demo=$1 AND status IN ('enviado','recebido','executado')"
                " AND sent_at < $2 ORDER BY sent_at", self.is_demo, now - timedelta(seconds=ACK_TIMEOUT_S))
        for r in due:
            age = (now - r["sent_at"]).total_seconds()
            if r["status"] == "enviado" and r["retries"] == 0:
                text = json.dumps(r["payload"], separators=(",", ":"), ensure_ascii=False)
                ok, _ = await self._publish(v1.topic_comando(r["device"]), text)
                async with self.pool.acquire() as c:
                    await c.execute("UPDATE commands SET retries=retries+1 WHERE cmd_id=$1", r["cmd_id"])
                log.warning("comando %s sem ack em %.0fs: retransmitido (%s)", r["cmd_id"], ACK_TIMEOUT_S,
                            "ok" if ok else "falhou")
                continue
            limit = CONFIRM_TIMEOUT_S if r["status"] == "executado" else 2 * ACK_TIMEOUT_S
            if age >= limit:
                async with self.pool.acquire() as c:
                    row = await c.fetchrow(
                        "UPDATE commands SET status='sem_confirmacao', motivo=COALESCE(motivo,$2) WHERE cmd_id=$1"
                        " AND status IN ('enviado','recebido','executado') RETURNING *", r["cmd_id"],
                        "sem ack" if r["status"] == "enviado" else "sem estado confirmando")
                    if row and row["scene_command_id"]:
                        await c.execute("UPDATE scene_commands SET status='sem_confirmacao' WHERE id=$1",
                                        row["scene_command_id"])
                if row:
                    v = self.command_view(row)
                    self.actuators.setdefault(v["device"], {})["last_command"] = v
                    await self.hub.broadcast("v1_command", v)
                    await self.alerts.on_command_result(v["cmd_id"], False, v["motivo"], now)
        # sensor parado: telemetria a cada 2 s, considerado parado após 10 s (contrato §3)
        await self.evaluate(now)
