"""Consultas históricas (período, paginação, agregações, exportação)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import asyncpg

from . import firmware as fw

# dataset -> (tabela/SQL base, coluna de tempo, colunas exportadas)
DATASETS: dict[str, tuple[str, str, list[str]]] = {
    "readings": ("sensor_readings", "received_at",
                 ["id", "received_at", "raw", "cena_computed", "cena_reported", "uptime_ms"]),
    "commands": ("scene_commands", "received_at",
                 ["id", "received_at", "cena", "previous_cena", "known_scene", "status", "confirmed_at", "latency_ms"]),
    "confirmations": (
        "(SELECT c.*, d.device_key AS device FROM actuator_confirmations c LEFT JOIN devices d ON d.id=c.device_id) t",
        "received_at",
        ["id", "received_at", "device", "estado", "cena", "retained", "led1", "led2", "led3", "led4",
         "match_status", "command_id"]),
    "connectivity": ("connectivity_events", "occurred_at", ["id", "occurred_at", "component", "event", "detail"]),
    "messages": ("mqtt_messages", "received_at",
                 ["id", "received_at", "topic", "origin", "qos", "retained", "parse_status", "error_reason",
                  "error_details", "payload"]),
    "alerts": ("alerts", "opened_at",
               ["id", "opened_at", "closed_at", "kind", "severity", "status", "message", "context", "acknowledged_at"]),
    "events": ("v_events", "occurred_at", ["occurred_at", "category", "ref_id", "detail"]),
}


def default_range(frm: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    to = to or datetime.now(timezone.utc)
    frm = frm or (to - timedelta(hours=24))
    if frm.tzinfo is None:
        frm = frm.replace(tzinfo=timezone.utc)
    if to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)
    if frm > to:
        raise ValueError("'from' deve ser anterior a 'to'")
    return frm, to


async def page(pool: asyncpg.Pool, dataset: str, *, is_demo: bool, frm: datetime, to: datetime,
               limit: int, offset: int, filters: dict | None = None, order: str = "desc") -> dict:
    src, tcol, cols = DATASETS[dataset]
    where = [f"is_demo = $1", f"{tcol} >= $2", f"{tcol} <= $3"]
    args: list = [is_demo, frm, to]
    for col, val in (filters or {}).items():
        if val is None:
            continue
        args.append(val)
        where.append(f"{col} = ${len(args)}")
    w = " AND ".join(where)
    direction = "ASC" if order == "asc" else "DESC"
    order_cols = f"{tcol} {direction}" + (f", id {direction}" if "id" in cols else "")
    async with pool.acquire() as c:
        total = await c.fetchval(f"SELECT count(*) FROM {src} WHERE {w}", *args)
        rows = await c.fetch(
            f"SELECT {', '.join(cols)} FROM {src} WHERE {w} ORDER BY {order_cols}"
            f" LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}", *args, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "from": frm, "to": to,
            "items": [dict(r) for r in rows]}


def bucket_seconds(frm: datetime, to: datetime, target_points: int = 360) -> int:
    span = max(1.0, (to - frm).total_seconds())
    raw = span / target_points
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400):
        if raw <= step:
            return step
    return int(math.ceil(raw / 86400) * 86400)


async def reading_series(pool, *, is_demo: bool, frm, to, bucket: int | None) -> dict:
    b = bucket or bucket_seconds(frm, to)
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT date_bin(make_interval(secs => $4), received_at, TIMESTAMPTZ '2000-01-01') AS t,"
            " min(raw) AS min, max(raw) AS max, round(avg(raw))::int AS avg, count(*) AS n"
            " FROM sensor_readings WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3"
            " GROUP BY 1 ORDER BY 1", is_demo, frm, to, b)
    return {"bucket_s": b, "from": frm, "to": to, "points": [dict(r) for r in rows]}


async def stats(pool, *, is_demo: bool, frm, to) -> dict:
    async with pool.acquire() as c:
        r = await c.fetchrow(
            "SELECT min(raw) mn, max(raw) mx, avg(raw)::float av, count(*) n,"
            " min(received_at) first_at, max(received_at) last_at"
            " FROM sensor_readings WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3", is_demo, frm, to)
        cmd = await c.fetchrow(
            "SELECT count(*) n, count(*) FILTER (WHERE status='confirmado') confirmed,"
            " count(*) FILTER (WHERE status='sem_confirmacao') unconfirmed,"
            " count(*) FILTER (WHERE status='aguardando') pending,"
            " avg(latency_ms)::float lat_avg, percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) lat_p95,"
            " max(latency_ms) lat_max"
            " FROM scene_commands WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3", is_demo, frm, to)
        msg = await c.fetchrow(
            "SELECT count(*) n, count(*) FILTER (WHERE parse_status='invalido') invalid,"
            " count(*) FILTER (WHERE parse_status='erro_processamento') errors"
            " FROM mqtt_messages WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3", is_demo, frm, to)
        conf = await c.fetchval(
            "SELECT count(*) FROM actuator_confirmations WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3",
            is_demo, frm, to)
        alerts = await c.fetchval(
            "SELECT count(*) FROM alerts WHERE is_demo=$1 AND opened_at BETWEEN $2 AND $3", is_demo, frm, to)
    return {
        "from": frm, "to": to,
        "readings": {"min": r["mn"], "max": r["mx"], "avg": r["av"], "count": r["n"],
                     "first_at": r["first_at"], "last_at": r["last_at"]},
        "commands": {"count": cmd["n"], "confirmed": cmd["confirmed"], "unconfirmed": cmd["unconfirmed"],
                     "pending": cmd["pending"], "latency_avg_ms": cmd["lat_avg"], "latency_p95_ms": cmd["lat_p95"],
                     "latency_max_ms": cmd["lat_max"]},
        "confirmations": conf,
        "messages": {"count": msg["n"], "invalid": msg["invalid"], "errors": msg["errors"]},
        "alerts": alerts,
    }


async def scene_analysis(pool, *, is_demo: bool, frm: datetime, to: datetime) -> dict:
    """Intervalos de cada cena a partir das transições publicadas pelo sensor.

    Como o sensor só publica na mudança, a cena vigente vale até a próxima
    transição. A cena anterior ao início do período é incluída para que o
    primeiro trecho seja contabilizado.
    """
    now = datetime.now(timezone.utc)
    end = min(to, now)
    async with pool.acquire() as c:
        before = await c.fetchrow(
            "SELECT cena, received_at FROM scene_commands WHERE is_demo=$1 AND received_at < $2"
            " ORDER BY received_at DESC, id DESC LIMIT 1", is_demo, frm)
        rows = await c.fetch(
            "SELECT cena, received_at FROM scene_commands WHERE is_demo=$1 AND received_at BETWEEN $2 AND $3"
            " ORDER BY received_at, id", is_demo, frm, end)
    marks = ([(before["cena"], frm)] if before else []) + [(r["cena"], r["received_at"]) for r in rows]
    intervals = []
    for i, (cena, start) in enumerate(marks):
        stop = marks[i + 1][1] if i + 1 < len(marks) else end
        if stop <= start:
            continue
        if intervals and intervals[-1]["cena"] == cena:  # repetição (ex.: sensor reiniciado)
            intervals[-1]["end"] = stop
        else:
            intervals.append({"cena": cena, "start": start, "end": stop})
    for iv in intervals:
        iv["duration_s"] = (iv["end"] - iv["start"]).total_seconds()

    dist = {s: {"duration_s": 0.0, "count": 0} for s in fw.SCENE_KEYS}
    for iv in intervals:
        d = dist.setdefault(iv["cena"], {"duration_s": 0.0, "count": 0})
        d["duration_s"] += iv["duration_s"]
        d["count"] += 1
    covered = sum(iv["duration_s"] for iv in intervals)

    # períodos de exposição intensa = trechos contínuos em "alta" ou "extrema"
    intense: list[dict] = []
    for iv in intervals:
        if iv["cena"] not in ("alta", "extrema"):
            continue
        if intense and intense[-1]["end"] == iv["start"]:
            intense[-1]["end"] = iv["end"]
            intense[-1]["cenas"].add(iv["cena"])
            if iv["cena"] == "extrema":
                intense[-1]["extrema_s"] += iv["duration_s"]
        else:
            intense.append({"start": iv["start"], "end": iv["end"], "cenas": {iv["cena"]},
                            "extrema_s": iv["duration_s"] if iv["cena"] == "extrema" else 0.0})
    for it in intense:
        it["duration_s"] = (it["end"] - it["start"]).total_seconds()
        it["cenas"] = sorted(it["cenas"], key=fw.SCENE_KEYS.index)
    intense.sort(key=lambda x: x["duration_s"], reverse=True)

    return {"from": frm, "to": end, "covered_s": covered, "intervals": intervals[-2000:],
            "intervals_total": len(intervals),
            "distribution": [{"cena": k, **v, "share": (v["duration_s"] / covered) if covered else 0}
                             for k, v in dist.items()],
            "intense_periods": intense[:50]}
