"""MODO DEMONSTRAÇÃO — dados sintéticos, claramente identificados.

Gera mensagens com os MESMOS tópicos e payloads do firmware e as envia
pelo mesmo pipeline de ingestão, gravando tudo com is_demo=true.
Nunca publica no broker: é apenas um gerador local.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random

from . import firmware as fw
from .ingest import TelemetryService

log = logging.getLogger(__name__)


class DemoGenerator:
    def __init__(self, service: TelemetryService, interval_s: float = 1.0, seed: int | None = None) -> None:
        self.s = service
        self.interval = interval_s
        self.rng = random.Random(seed)
        self.t = 0.0
        self.cena_sensor = ""  # igual a cenaAtual="" no firmware do sensor
        self.spike = 0

    def next_raw(self) -> int:
        self.t += self.interval
        base = 700 + 650 * math.sin(self.t / 40)            # ciclo lento
        base += 120 * math.sin(self.t / 7.3)                # nuvens
        if self.spike <= 0 and self.rng.random() < 0.02:    # "lanterna"
            self.spike = self.rng.randint(4, 10)
        if self.spike > 0:
            self.spike -= 1
            base += 1500
        raw = int(base + self.rng.gauss(0, 35))
        return max(fw.ADC_MIN, min(fw.ADC_MAX, raw))

    async def _actuator(self, cena: str) -> None:
        await asyncio.sleep(self.rng.uniform(0.04, 0.35))
        if self.rng.random() < 0.04:  # simula confirmação perdida
            log.info("[demo] confirmação de '%s' descartada propositalmente", cena)
            return
        payload = {"device": fw.ACTUATOR_DEVICE_ID, "estado": f"{fw.actuator_view_of_scene(cena)}_executada"}
        await self.s.handle(fw.TOPIC_ACTUATOR_STATUS, json.dumps(payload).encode(), qos=1, retained=False)

    async def step(self) -> None:
        raw = self.next_raw()
        cena = fw.classify(raw)
        # telemetria periódica: simula o patch opcional do sensor
        await self.s.handle(fw.TOPIC_SENSOR_TELEMETRY,
                            json.dumps({"device": fw.SENSOR_CLIENT_ID, "leitura": raw, "cena": cena,
                                        "uptime_ms": int(self.t * 1000)}).encode(), qos=0)
        if cena != self.cena_sensor:  # enviarCena(): só publica na mudança
            self.cena_sensor = cena
            await self.s.handle(fw.TOPIC_COMMAND, json.dumps({"cena": cena}).encode(), qos=0)
            asyncio.create_task(self._actuator(cena))
        if self.rng.random() < 0.01:
            await self.s.handle(fw.TOPIC_COMMAND, b'{"cena": ', qos=0)  # JSON truncado

    async def run(self, stop: asyncio.Event) -> None:
        log.warning("MODO DEMONSTRAÇÃO ATIVO — dados sintéticos (is_demo=true)")
        await self.s.handle(fw.TOPIC_SENSOR_CONNECTION,
                            json.dumps({"device": fw.SENSOR_CLIENT_ID, "status": "online"}).encode(), retained=True)
        await self.s.handle(fw.TOPIC_ACTUATOR_CONNECTION,
                            json.dumps({"device": fw.ACTUATOR_DEVICE_ID, "status": "online"}).encode(), retained=True)
        while not stop.is_set():
            try:
                await self.step()
            except Exception:
                log.exception("[demo] erro no gerador")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
