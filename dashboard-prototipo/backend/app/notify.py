"""Notificação externa (R15): alertas críticos saem da interface e chegam no celular.

Canais (configurados no .env, todos opcionais e independentes):
    NTFY_URL            ex.: https://ntfy.sh/<tópico-secreto>  (app ntfy no celular, sem cadastro)
    TELEGRAM_BOT_TOKEN  + TELEGRAM_CHAT_ID                     (bot do Telegram)
Cada envio fica registrado na tabela notifications (ok/erro), consultável pela API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
import httpx

log = logging.getLogger(__name__)
SEVERITY_ORDER = {"info": 0, "aviso": 1, "critico": 2}


class Notifier:
    def __init__(self, pool: asyncpg.Pool, *, ntfy_url: str | None, telegram_token: str | None,
                 telegram_chat_id: str | None, min_severity: str = "aviso", is_demo: bool = False) -> None:
        self.pool = pool
        self.ntfy_url = ntfy_url or None
        self.tg_token = telegram_token or None
        self.tg_chat = telegram_chat_id or None
        self.min_level = SEVERITY_ORDER.get(min_severity, 1)
        self.is_demo = is_demo

    @property
    def channels(self) -> list[str]:
        out = []
        if self.ntfy_url:
            out.append("ntfy")
        if self.tg_token and self.tg_chat:
            out.append("telegram")
        return out

    async def on_alert(self, alert: dict) -> None:
        if self.is_demo or SEVERITY_ORDER.get(alert["severity"], 0) < self.min_level:
            return
        title = f"Luz Ambiente - alerta {alert['severity']}"
        await self.send(title, alert["message"], alert_id=alert["id"],
                        priority="high" if alert["severity"] == "critico" else "default")

    async def send(self, title: str, message: str, *, alert_id: int | None = None,
                   priority: str = "default") -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=8) as http:
            if self.ntfy_url:
                results.append(await self._try("ntfy", title, message, alert_id, lambda: http.post(
                    self.ntfy_url, content=message.encode(),
                    headers={"Title": title.encode("ascii", "ignore").decode() or "Luz Ambiente",
                             "Priority": priority, "Tags": "seedling,warning"})))
            if self.tg_token and self.tg_chat:
                results.append(await self._try("telegram", title, message, alert_id, lambda: http.post(
                    f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                    json={"chat_id": self.tg_chat, "text": f"{title}\n{message}"})))
        return results

    async def _try(self, channel, title, message, alert_id, call) -> dict:
        ok, err = True, None
        try:
            r = await call()
            if r.status_code >= 300:
                ok, err = False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        if not ok:
            log.warning("notificação %s falhou: %s", channel, err)
        else:
            log.info("notificação enviada por %s: %s", channel, message)
        async with self.pool.acquire() as c:
            await c.execute("INSERT INTO notifications (sent_at, channel, title, message, ok, error, alert_id, is_demo)"
                            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", datetime.now(timezone.utc), channel, title,
                            message, ok, err, alert_id, self.is_demo)
        return {"channel": channel, "ok": ok, "error": err}
