from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import firmware as fw
from . import queries as q
from . import v1
from .alerts import AlertEngine, RuleValidationError
from .auth import Auth, AuthError, User
from .control import ControlService
from .notify import Notifier
from .config import Settings, get_settings
from .db import create_pool, migrate
from .demo import DemoGenerator
from .hub import Hub, dumps
from .ingest import TelemetryService
from .mqtt_client import run_mqtt

# Exportação CSV: horários em Brasília (UTC-3, sem horário de verão desde 2019) para abrir legível
# em planilha. O JSON mantém ISO 8601 em UTC, que é o formato para máquinas.
EXPORT_TZ = timezone(timedelta(hours=-3), "BRT")
TIME_COLS = {"received_at", "occurred_at", "confirmed_at", "opened_at", "closed_at", "acknowledged_at"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("luz")


class RulePatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    severity: str | None = None
    params: dict | None = None


class LoginBody(BaseModel):
    username: str
    password: str


class CommandBody(BaseModel):
    device: str | None = None
    acao: Literal["aplicar", "definir_modo"]
    cena: str | None = None
    modo: str | None = None
    duracao_s: int | None = None


class DecisionPatch(BaseModel):
    enabled: bool | None = None
    limite_ambiente: int | None = None
    limite_alta: int | None = None
    limite_extrema: int | None = None
    histerese: int | None = None
    confirmacao_s: float | None = None


# Configurações remotas persistidas na NVS do dispositivo (R2): só estas chaves são aceitas.
DEVICE_CONFIG_KEYS = {
    "sensor": {"intervalo_ms": (1000, 60000), "limite_local": (1, 4095)},
    "atuador": {"seguro_apos_s": (10, 600), "sombra_fechada_graus": (45, 120)},
}

PUBLIC_PATHS = {"/api/health", "/api/auth/login"}


class RuleCreate(BaseModel):
    kind: str
    name: str
    enabled: bool = False
    severity: str = "aviso"
    params: dict = {}


async def _watchdog(service: TelemetryService, interval: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await service.tick()
            if service.control is not None:
                await service.control.tick()
        except Exception:
            log.exception("erro no watchdog")
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)


def create_app(settings: Settings | None = None, *, start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = await create_pool(settings.database_url)
        await migrate(pool)
        hub = Hub()
        alerts = AlertEngine(pool, hub, settings.demo_mode)
        await alerts.load()
        service = TelemetryService(pool, hub, alerts, is_demo=settings.demo_mode,
                                   store_raw_payloads=settings.store_raw_payloads)
        await service.restore()
        control = ControlService(service, is_demo=settings.demo_mode)
        await control.load()
        service.control = control
        notifier = Notifier(pool, ntfy_url=settings.ntfy_url, telegram_token=settings.telegram_bot_token,
                            telegram_chat_id=settings.telegram_chat_id, min_severity=settings.notify_min_severity,
                            is_demo=settings.demo_mode)
        alerts.on_open = notifier.on_alert
        app.state.pool, app.state.hub, app.state.alerts, app.state.service = pool, hub, alerts, service
        app.state.control, app.state.notifier = control, notifier
        app.state.settings = settings
        stop = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if start_background:
            if settings.demo_mode:
                tasks.append(asyncio.create_task(DemoGenerator(service, settings.demo_interval_s).run(stop)))
            elif settings.mqtt_enabled:
                tasks.append(asyncio.create_task(run_mqtt(settings, service, stop)))
            else:
                await service.set_broker("desativado")
            tasks.append(asyncio.create_task(_watchdog(service, settings.watchdog_interval_s, stop)))
        try:
            yield
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            for t in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await t
            await pool.close()

    app = FastAPI(title="Luz Ambiente", version="3.0.0", lifespan=lifespan)
    auth = Auth(settings.auth_users, settings.auth_secret, settings.auth_ttl_h)
    app.state.auth = auth
    if not auth.enabled:
        log.warning("AUTH_USERS vazio: a API está ABERTA (use só em testes)")

    async def audit(pool, user: User, action: str, detail: dict | None = None, ok: bool = True) -> None:
        async with pool.acquire() as c:
            await c.execute("INSERT INTO audit_log (username, role, action, detail, ok) VALUES ($1,$2,$3,$4,$5)",
                            user.username, user.role, action, detail or {}, ok)

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if not auth.enabled or not path.startswith("/api/") or path in PUBLIC_PATHS or request.method == "OPTIONS":
            request.state.user = User("anonimo", "admin") if not auth.enabled else None
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
        try:
            user = auth.verify(token)
        except AuthError as e:
            return JSONResponse(status_code=e.status, content={"detail": e.detail})
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not user.can_command:
            await audit(request.app.state.pool, user, f"{request.method} {path}", {"negado": "perfil operador"}, False)
            return JSONResponse(status_code=403, content={"detail": "seu perfil (operador) só visualiza; "
                                                                    "comandos e configurações exigem admin"})
        request.state.user = user
        return await call_next(request)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])

    # ---------------------------------------------------------------- login
    @app.post("/api/auth/login")
    async def login(req: Request, body: LoginBody):
        try:
            token, user = auth.login(body.username, body.password)
        except AuthError as e:
            await audit(req.app.state.pool, User(body.username[:40] or "?", "desconhecido"), "login",
                        {"erro": e.detail}, False)
            raise HTTPException(e.status, e.detail)
        await audit(req.app.state.pool, user, "login")
        return {"token": token, "user": {"username": user.username, "role": user.role,
                                         "can_command": user.can_command}}

    @app.get("/api/auth/me")
    async def me(req: Request):
        u: User = req.state.user
        return {"username": u.username, "role": u.role, "can_command": u.can_command}

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def svc(req: Request) -> TelemetryService:
        return req.app.state.service

    def rng(frm: datetime | None, to: datetime | None):
        return q.default_range(frm, to)

    def lim(limit: int) -> int:
        return max(1, min(limit, settings.max_page_size))

    # ---------------------------------------------------------------- status
    @app.get("/api/health")
    async def health(req: Request):
        async with req.app.state.pool.acquire() as c:
            await c.fetchval("SELECT 1")
        s = svc(req)
        return {"ok": True, "database": "ok", "broker": s.broker["status"], "demo": s.is_demo}

    @app.get("/api/config")
    async def config(req: Request):
        return {
            "demo": settings.demo_mode,
            "mqtt": {"enabled": settings.mqtt_enabled, "host": settings.mqtt_host, "port": settings.mqtt_port,
                     "tls": settings.mqtt_tls, "subscription": settings.mqtt_subscribe,
                     "auth": bool(settings.mqtt_username)},  # nunca expõe usuário/senha
            "firmware": fw.firmware_description(),
            "features": {"servo": True},
            "contrato": "v1.1",
            "auth": auth.enabled,
            "notificacao": req.app.state.notifier.channels,
        }

    # ------------------------------------------------- controle (contrato v1.1)
    def ctl(req: Request) -> ControlService:
        return req.app.state.control

    @app.get("/api/v1/state")
    async def v1_state(req: Request):
        return JSONResponse(json.loads(dumps(ctl(req).snapshot())))

    @app.get("/api/v1/commands")
    async def v1_commands(req: Request, limit: int = 50, status: str | None = None):
        async with req.app.state.pool.acquire() as c:
            rows = await c.fetch(
                "SELECT * FROM commands WHERE is_demo=$1 AND ($2::text IS NULL OR status=$2)"
                " ORDER BY sent_at DESC LIMIT $3", settings.demo_mode, status, lim(limit))
        return [ControlService.command_view(r) for r in rows]

    @app.get("/api/v1/commands/{cmd_id}")
    async def v1_command(req: Request, cmd_id: str):
        async with req.app.state.pool.acquire() as c:
            r = await c.fetchrow("SELECT * FROM commands WHERE cmd_id=$1", cmd_id)
            acks = await c.fetch("SELECT received_at, resultado, motivo FROM command_acks WHERE cmd_id=$1"
                                 " ORDER BY received_at", cmd_id)
        if not r:
            raise HTTPException(404, "comando não encontrado")
        return {**ControlService.command_view(r), "payload": r["payload"], "acks": [dict(a) for a in acks]}

    @app.post("/api/v1/commands", status_code=201)
    async def v1_send(req: Request, body: CommandBody):
        user: User = req.state.user
        c = ctl(req)
        device = body.device or c.cfg.atuador
        try:
            v1.build_command("c-00000000-000000", origem="manual", acao=body.acao, cena=body.cena, modo=body.modo,
                             duracao_s=body.duracao_s)
        except ValueError as e:
            await audit(req.app.state.pool, user, "comando", {**body.model_dump(), "erro": str(e)}, False)
            raise HTTPException(422, f"comando inválido: {e}")
        cmd = await c.issue(device, origem="manual", acao=body.acao, cena=body.cena, modo=body.modo,
                            duracao_s=body.duracao_s, requested_by=user.username, reason="enviado pela interface")
        await audit(req.app.state.pool, user, "comando", {"cmd_id": cmd["cmd_id"], **body.model_dump()})
        return cmd

    @app.post("/api/v1/commands/{cmd_id}/reenviar")
    async def v1_resend(req: Request, cmd_id: str):
        user: User = req.state.user
        try:
            cmd = await ctl(req).resend(cmd_id, user.username)
        except KeyError:
            raise HTTPException(404, "comando não encontrado")
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        await audit(req.app.state.pool, user, "reenvio_duplicado", {"cmd_id": cmd_id})
        return cmd

    @app.get("/api/v1/decision")
    async def v1_decision(req: Request):
        return ctl(req).cfg.as_dict()

    @app.put("/api/v1/decision")
    async def v1_decision_put(req: Request, body: DecisionPatch):
        user: User = req.state.user
        try:
            r = await ctl(req).update_config(user.username, **body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(422, str(e))
        await audit(req.app.state.pool, user, "regra_alterada", body.model_dump(exclude_none=True))
        return r

    @app.post("/api/v1/config/{role}/{device}")
    async def v1_device_config(req: Request, role: str, device: str, body: dict):
        user: User = req.state.user
        allowed = DEVICE_CONFIG_KEYS.get(role)
        if allowed is None or not v1.DEVICE_RE.match(device):
            raise HTTPException(404, "dispositivo desconhecido")
        clean = {}
        for k, val in body.items():
            if k not in allowed:
                raise HTTPException(422, f"'{k}' não é configurável; use {sorted(allowed)}")
            lo, hi = allowed[k]
            if isinstance(val, bool) or not isinstance(val, int) or not lo <= val <= hi:
                raise HTTPException(422, f"'{k}' deve ser inteiro entre {lo} e {hi}")
            clean[k] = val
        if not clean:
            raise HTTPException(422, "nada para configurar")
        try:
            payload = await ctl(req).publish_config(role, device, clean)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        await audit(req.app.state.pool, user, "config_dispositivo", {"device": device, **clean})
        return payload

    @app.get("/api/v1/notifications")
    async def v1_notifications(req: Request, limit: int = 30):
        async with req.app.state.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM notifications ORDER BY sent_at DESC LIMIT $1", lim(limit))
        return {"channels": req.app.state.notifier.channels, "items": [dict(r) for r in rows]}

    @app.post("/api/v1/notifications/teste")
    async def v1_notify_test(req: Request):
        n: Notifier = req.app.state.notifier
        if not n.channels:
            raise HTTPException(409, "nenhum canal configurado (NTFY_URL ou TELEGRAM_* no .env)")
        return await n.send("Luz Ambiente · teste", f"Notificação de teste enviada por {req.state.user.username}")

    @app.get("/api/audit")
    async def audit_list(req: Request, limit: int = 50):
        async with req.app.state.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM audit_log ORDER BY at DESC LIMIT $1", lim(limit))
        return [dict(r) for r in rows]

    @app.get("/api/state")
    async def state(req: Request):
        return JSONResponse(json.loads(dumps(svc(req).snapshot())))

    # -------------------------------------------------------------- histórico
    @app.get("/api/readings")
    async def readings(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                       limit: int = 100, offset: int = Query(0, ge=0), order: Literal["asc", "desc"] = "desc"):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "readings", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, order=order)

    @app.get("/api/readings/series")
    async def series(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                     bucket: int | None = Query(None, ge=1, le=86400)):
        f, t = rng(frm, to)
        return await q.reading_series(req.app.state.pool, is_demo=settings.demo_mode, frm=f, to=t, bucket=bucket)

    @app.get("/api/stats")
    async def stats(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None):
        f, t = rng(frm, to)
        return await q.stats(req.app.state.pool, is_demo=settings.demo_mode, frm=f, to=t)

    @app.get("/api/commands")
    async def commands(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                       limit: int = 100, offset: int = Query(0, ge=0), status: str | None = None):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "commands", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, filters={"status": status})

    @app.get("/api/confirmations")
    async def confirmations(req: Request, frm: datetime | None = Query(None, alias="from"),
                            to: datetime | None = None, limit: int = 100, offset: int = Query(0, ge=0)):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "confirmations", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset)

    @app.get("/api/events")
    async def events(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                     limit: int = 100, offset: int = Query(0, ge=0), category: str | None = None):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "events", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, filters={"category": category})

    @app.get("/api/connectivity")
    async def connectivity(req: Request, frm: datetime | None = Query(None, alias="from"),
                           to: datetime | None = None, limit: int = 100, offset: int = Query(0, ge=0),
                           component: str | None = None):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "connectivity", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, filters={"component": component})

    @app.get("/api/messages")
    async def messages(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                       limit: int = 100, offset: int = Query(0, ge=0), parse_status: str | None = None,
                       topic: str | None = None):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "messages", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, filters={"parse_status": parse_status, "topic": topic})

    @app.get("/api/analytics/scenes")
    async def scenes(req: Request, frm: datetime | None = Query(None, alias="from"), to: datetime | None = None):
        f, t = rng(frm, to)
        return await q.scene_analysis(req.app.state.pool, is_demo=settings.demo_mode, frm=f, to=t)

    # ---------------------------------------------------------------- alertas
    @app.get("/api/alerts")
    async def alerts_list(req: Request, frm: datetime | None = Query(None, alias="from"),
                          to: datetime | None = None, limit: int = 100, offset: int = Query(0, ge=0),
                          status: Literal["aberto", "encerrado"] | None = None):
        f, t = rng(frm, to)
        return await q.page(req.app.state.pool, "alerts", is_demo=settings.demo_mode, frm=f, to=t,
                            limit=lim(limit), offset=offset, filters={"status": status})

    @app.post("/api/alerts/{alert_id}/ack")
    async def ack(req: Request, alert_id: int):
        async with req.app.state.pool.acquire() as c:
            row = await c.fetchrow("UPDATE alerts SET acknowledged_at=COALESCE(acknowledged_at, now())"
                                   " WHERE id=$1 RETURNING id, acknowledged_at", alert_id)
        if not row:
            raise HTTPException(404, "alerta não encontrado")
        eng: AlertEngine = req.app.state.alerts
        for a in eng.open.values():
            if a["id"] == alert_id:
                a["acknowledged_at"] = row["acknowledged_at"]
        return dict(row)

    @app.get("/api/alert-rules")
    async def rules(req: Request):
        return sorted(req.app.state.alerts.rules.values(), key=lambda r: r["id"])

    @app.put("/api/alert-rules/{rule_id}")
    async def update_rule(req: Request, rule_id: int, body: RulePatch):
        try:
            r = await req.app.state.alerts.update_rule(rule_id, **body.model_dump())
        except KeyError:
            raise HTTPException(404, "regra não encontrada")
        except RuleValidationError as e:
            raise HTTPException(422, str(e))
        await svc(req).reevaluate()
        return r

    @app.post("/api/alert-rules", status_code=201)
    async def create_rule(req: Request, body: RuleCreate):
        try:
            r = await req.app.state.alerts.create_rule(**body.model_dump())
        except RuleValidationError as e:
            raise HTTPException(422, str(e))
        await svc(req).reevaluate()
        return r

    @app.delete("/api/alert-rules/{rule_id}", status_code=204)
    async def delete_rule(req: Request, rule_id: int):
        try:
            await req.app.state.alerts.delete_rule(rule_id)
        except KeyError:
            raise HTTPException(404, "regra não encontrada")
        except RuleValidationError as e:
            raise HTTPException(409, str(e))

    # -------------------------------------------------------------- exportação
    @app.get("/api/export/{dataset}")
    async def export(req: Request, dataset: str, format: Literal["csv", "json"] = "csv",
                     frm: datetime | None = Query(None, alias="from"), to: datetime | None = None):
        if dataset not in q.DATASETS:
            raise HTTPException(404, f"dataset desconhecido; use um de {list(q.DATASETS)}")
        f, t = rng(frm, to)
        src, tcol, cols = q.DATASETS[dataset]
        sql = (f"SELECT {', '.join(cols)} FROM {src} WHERE is_demo=$1 AND {tcol} BETWEEN $2 AND $3"
               f" ORDER BY {tcol}")
        pool = req.app.state.pool

        def csv_line(values: list) -> str:
            buf = io.StringIO()
            # ";" é o separador que o Excel em português espera (com "," tudo cai numa coluna só)
            csv.writer(buf, delimiter=";", lineterminator="\r\n").writerow(values)
            return buf.getvalue()

        def csv_cell(v):
            if isinstance(v, datetime):
                return v.astimezone(EXPORT_TZ).strftime("%d/%m/%Y %H:%M:%S")
            if isinstance(v, bool):
                return "sim" if v else "não"
            if isinstance(v, dict):  # detalhes legíveis em vez de um bloco JSON
                return " | ".join(f"{k}: {csv_cell(x) if x is not None else '—'}" for k, x in v.items())
            if isinstance(v, list):
                return ", ".join(str(csv_cell(x)) for x in v)
            return v

        async def gen():
            async with pool.acquire() as c, c.transaction():
                first = True
                if format == "json":
                    yield "[\n"
                else:
                    # BOM: faz o Excel abrir como UTF-8 (acentos corretos)
                    yield "﻿" + csv_line([f"{col} (horário de Brasília)" if col in TIME_COLS else col
                                               for col in cols])
                async for r in c.cursor(sql, settings.demo_mode, f, t, prefetch=500):
                    if format == "json":
                        yield ("" if first else ",\n") + "  " + dumps(dict(r))
                    else:
                        yield csv_line([csv_cell(v) for v in r.values()])
                    first = False
                if format == "json":
                    yield "\n]\n"

        name = f"{dataset}_{f:%Y%m%dT%H%M}_{t:%Y%m%dT%H%M}{'_demo' if settings.demo_mode else ''}.{format}"
        media = "application/json" if format == "json" else "text/csv; charset=utf-8"
        return StreamingResponse(gen(), media_type=media,
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # --------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if auth.enabled:
            try:
                auth.verify(websocket.query_params.get("token"))
            except AuthError:
                await websocket.close(code=4401)
                return
        await websocket.accept()
        hub: Hub = websocket.app.state.hub
        await hub.add(websocket)
        try:
            await websocket.send_text(dumps({"type": "state", "data": websocket.app.state.service.snapshot()}))
            while True:  # mantém aberto; aceita "ping" do cliente
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            pass
        finally:
            await hub.remove(websocket)

    return app


app = create_app()
