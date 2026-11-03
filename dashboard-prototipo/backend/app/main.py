from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import firmware as fw
from . import queries as q
from .alerts import AlertEngine, RuleValidationError
from .config import Settings, get_settings
from .db import create_pool, migrate
from .demo import DemoGenerator
from .hub import Hub, dumps
from .ingest import TelemetryService
from .mqtt_client import run_mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("luz")


class RulePatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    severity: str | None = None
    params: dict | None = None


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
        app.state.pool, app.state.hub, app.state.alerts, app.state.service = pool, hub, alerts, service
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

    app = FastAPI(title="Luz Ambiente — Telemetria", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])

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
            "features": {"servo": False},
        }

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

        async def gen():
            async with pool.acquire() as c, c.transaction():
                first = True
                if format == "json":
                    yield "["
                else:
                    buf = io.StringIO()
                    csv.writer(buf).writerow(cols)
                    yield buf.getvalue()
                async for r in c.cursor(sql, settings.demo_mode, f, t, prefetch=500):
                    if format == "json":
                        yield ("" if first else ",") + dumps(dict(r))
                    else:
                        buf = io.StringIO()
                        csv.writer(buf).writerow(
                            [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                             else (v.isoformat() if isinstance(v, datetime) else v) for v in r.values()])
                        yield buf.getvalue()
                    first = False
                if format == "json":
                    yield "]"

        name = f"{dataset}_{f:%Y%m%dT%H%M}_{t:%Y%m%dT%H%M}{'_demo' if settings.demo_mode else ''}.{format}"
        media = "application/json" if format == "json" else "text/csv; charset=utf-8"
        return StreamingResponse(gen(), media_type=media,
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # --------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
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
