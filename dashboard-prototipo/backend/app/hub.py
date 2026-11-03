"""Distribuição de eventos em tempo real para os clientes WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


def _default(o: Any):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"não serializável: {type(o).__name__}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False)


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event_type: str, data: Any) -> None:
        if not self._clients:
            return
        text = dumps({"type": event_type, "data": data})
        dead = []
        for ws in list(self._clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=5)
            except Exception:  # cliente lento ou desconectado
                dead.append(ws)
        for ws in dead:
            await self.remove(ws)
