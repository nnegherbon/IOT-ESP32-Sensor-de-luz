"""Motor de alertas configuráveis.

Cada regra tem no máximo um alerta aberto por vez (índice único parcial).
Regras com limites nulos não podem ser ativadas: o projeto não define
esses limites, então eles precisam ser configurados explicitamente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from . import firmware as fw
from .hub import Hub

log = logging.getLogger(__name__)

KINDS = ("scene", "raw_above", "raw_below", "silence", "confirmation_timeout",
         "broker_disconnected", "device_offline")
SEVERITIES = ("info", "aviso", "critico")


class RuleValidationError(ValueError):
    pass


def validate_params(kind: str, params: dict, enabled: bool) -> dict:
    """Normaliza params; exige limites definidos quando a regra está ativa."""
    if kind not in KINDS:
        raise RuleValidationError(f"tipo de regra desconhecido: {kind}")
    p = dict(params or {})

    def need_number(key: str, *, minimum: float, maximum: float | None = None, integer=True):
        v = p.get(key)
        if v is None:
            if enabled:
                raise RuleValidationError(f"defina '{key}' antes de ativar a regra")
            p[key] = None
            return
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise RuleValidationError(f"'{key}' deve ser numérico")
        if v < minimum or (maximum is not None and v > maximum):
            raise RuleValidationError(f"'{key}' fora da faixa [{minimum}, {maximum if maximum is not None else '∞'}]")
        p[key] = int(v) if integer else float(v)

    if kind == "scene":
        scenes = p.get("scenes")
        if not isinstance(scenes, list) or not scenes or any(s not in fw.SCENE_KEYS for s in scenes):
            raise RuleValidationError(f"'scenes' deve ser uma lista não vazia de {list(fw.SCENE_KEYS)}")
        p = {"scenes": list(dict.fromkeys(scenes))}
    elif kind in ("raw_above", "raw_below"):
        need_number("threshold", minimum=fw.ADC_MIN, maximum=fw.ADC_MAX)
        p = {"threshold": p["threshold"]}
    elif kind == "silence":
        if p.get("component") not in ("sensor", "atuador"):
            raise RuleValidationError("'component' deve ser 'sensor' ou 'atuador'")
        need_number("seconds", minimum=1, maximum=7 * 24 * 3600)
        p = {"component": p["component"], "seconds": p["seconds"]}
    elif kind == "confirmation_timeout":
        need_number("ms", minimum=50, maximum=10 * 60 * 1000)
        p = {"ms": p["ms"]}
    else:
        p = {}
    return p


def rule_dict(r: asyncpg.Record | dict) -> dict:
    return {k: r[k] for k in ("id", "kind", "name", "enabled", "severity", "params", "builtin",
                              "created_at", "updated_at")}


def alert_dict(r: asyncpg.Record | dict) -> dict:
    return {k: r[k] for k in ("id", "rule_id", "kind", "severity", "status", "opened_at", "closed_at",
                              "message", "context", "acknowledged_at", "is_demo")}


class AlertEngine:
    def __init__(self, pool: asyncpg.Pool, hub: Hub, is_demo: bool) -> None:
        self.pool = pool
        self.hub = hub
        self.is_demo = is_demo
        self.rules: dict[int, dict] = {}
        self.open: dict[int, dict] = {}  # rule_id -> alerta aberto

    async def load(self) -> None:
        async with self.pool.acquire() as c:
            self.rules = {r["id"]: rule_dict(r) for r in await c.fetch("SELECT * FROM alert_rules ORDER BY id")}
            rows = await c.fetch("SELECT * FROM alerts WHERE status='aberto' AND is_demo=$1", self.is_demo)
        self.open = {r["rule_id"]: alert_dict(r) for r in rows if r["rule_id"] is not None}

    def enabled(self, kind: str) -> list[dict]:
        return [r for r in self.rules.values() if r["kind"] == kind and r["enabled"]]

    async def open_alert(self, rule: dict, message: str, context: dict | None = None,
                         at: datetime | None = None) -> dict | None:
        if rule["id"] in self.open:
            return None
        at = at or datetime.now(timezone.utc)
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "INSERT INTO alerts (rule_id, kind, severity, status, opened_at, message, context, is_demo)"
                " VALUES ($1,$2,$3,'aberto',$4,$5,$6,$7)"
                " ON CONFLICT (rule_id, is_demo) WHERE status='aberto' DO NOTHING RETURNING *",
                rule["id"], rule["kind"], rule["severity"], at, message, context or {}, self.is_demo)
        if row is None:
            return None
        a = alert_dict(row)
        self.open[rule["id"]] = a
        log.warning("ALERTA aberto [%s] %s", rule["severity"], message)
        await self.hub.broadcast("alert", a)
        return a

    async def close_alert(self, rule_id: int, at: datetime | None = None, reason: str | None = None) -> dict | None:
        if rule_id not in self.open:
            return None
        at = at or datetime.now(timezone.utc)
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "UPDATE alerts SET status='encerrado', closed_at=$2,"
                " context = COALESCE(context,'{}'::jsonb) || jsonb_build_object('motivo_encerramento', $3::text)"
                " WHERE rule_id=$1 AND is_demo=$4 AND status='aberto' RETURNING *",
                rule_id, at, reason, self.is_demo)
        self.open.pop(rule_id, None)
        if row:
            a = alert_dict(row)
            await self.hub.broadcast("alert", a)
            return a
        return None

    async def set_condition(self, rule: dict, active: bool, message: str, context: dict | None = None,
                            at: datetime | None = None, close_reason: str = "condição normalizada") -> None:
        if active:
            await self.open_alert(rule, message, context, at)
        else:
            await self.close_alert(rule["id"], at, close_reason)

    # --- avaliação por tipo de evento ------------------------------------
    async def on_scene(self, cena: str, at: datetime) -> None:
        for rule in self.enabled("scene"):
            active = cena in rule["params"]["scenes"]
            await self.set_condition(rule, active, f"Cena '{cena}' detectada pelo sensor",
                                     {"cena": cena}, at, f"cena mudou para '{cena}'")

    async def on_reading(self, raw: int, at: datetime) -> None:
        for rule in self.enabled("raw_above"):
            t = rule["params"]["threshold"]
            await self.set_condition(rule, raw > t, f"Leitura bruta {raw} acima de {t}",
                                     {"leitura": raw, "limite": t}, at)
        for rule in self.enabled("raw_below"):
            t = rule["params"]["threshold"]
            await self.set_condition(rule, raw < t, f"Leitura bruta {raw} abaixo de {t}",
                                     {"leitura": raw, "limite": t}, at)

    async def on_broker(self, connected: bool, detail: str | None = None) -> None:
        for rule in self.enabled("broker_disconnected"):
            await self.set_condition(rule, not connected,
                                     f"Backend sem conexão com o broker{': ' + detail if detail else ''}",
                                     {"erro": detail}, close_reason="reconectado")

    async def on_device_presence(self, component: str, online: bool, at: datetime) -> None:
        for rule in self.enabled("device_offline"):
            await self.set_condition(rule, not online, f"{component} anunciou offline (LWT)",
                                     {"componente": component}, at, f"{component} online")

    async def check_silence(self, last_seen: dict[str, datetime | None], baseline: datetime,
                            now: datetime) -> list[tuple[dict, bool]]:
        changes = []
        for rule in self.enabled("silence"):
            comp, secs = rule["params"]["component"], rule["params"]["seconds"]
            ref = last_seen.get(comp) or baseline
            silent = (now - ref).total_seconds() > secs
            was_open = rule["id"] in self.open
            await self.set_condition(rule, silent, f"Nenhuma mensagem do {comp} há mais de {secs}s",
                                     {"componente": comp, "ultima_mensagem": last_seen.get(comp)},
                                     now, "mensagens retomadas")
            if silent != was_open:
                changes.append((rule, silent))
        return changes

    # --- CRUD de regras ---------------------------------------------------
    async def update_rule(self, rule_id: int, *, name: str | None, enabled: bool | None,
                          severity: str | None, params: dict | None) -> dict:
        cur = self.rules.get(rule_id)
        if cur is None:
            raise KeyError(rule_id)
        new_enabled = cur["enabled"] if enabled is None else enabled
        new_params = validate_params(cur["kind"], cur["params"] if params is None else params, new_enabled)
        if severity is not None and severity not in SEVERITIES:
            raise RuleValidationError(f"severidade deve ser uma de {SEVERITIES}")
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "UPDATE alert_rules SET name=COALESCE($2,name), enabled=$3, severity=COALESCE($4,severity),"
                " params=$5, updated_at=now() WHERE id=$1 RETURNING *",
                rule_id, name, new_enabled, severity, new_params)
        r = rule_dict(row)
        self.rules[rule_id] = r
        # regra alterada: encerra o alerta aberto; será reavaliada no próximo evento
        await self.close_alert(rule_id, reason="regra alterada")
        await self.hub.broadcast("rule", r)
        return r

    async def create_rule(self, kind: str, name: str, enabled: bool, severity: str, params: dict) -> dict:
        p = validate_params(kind, params, enabled)
        if severity not in SEVERITIES:
            raise RuleValidationError(f"severidade deve ser uma de {SEVERITIES}")
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "INSERT INTO alert_rules (kind,name,enabled,severity,params) VALUES ($1,$2,$3,$4,$5) RETURNING *",
                kind, name, enabled, severity, p)
        r = rule_dict(row)
        self.rules[r["id"]] = r
        await self.hub.broadcast("rule", r)
        return r

    async def delete_rule(self, rule_id: int) -> None:
        r = self.rules.get(rule_id)
        if r is None:
            raise KeyError(rule_id)
        if r["builtin"]:
            raise RuleValidationError("regras padrão não podem ser removidas; desative-as")
        await self.close_alert(rule_id, reason="regra removida")
        async with self.pool.acquire() as c:
            await c.execute("DELETE FROM alert_rules WHERE id=$1", rule_id)
        self.rules.pop(rule_id, None)
        await self.hub.broadcast("rule_deleted", {"id": rule_id})

    def snapshot_open(self) -> list[dict[str, Any]]:
        return sorted(self.open.values(), key=lambda a: a["opened_at"], reverse=True)
