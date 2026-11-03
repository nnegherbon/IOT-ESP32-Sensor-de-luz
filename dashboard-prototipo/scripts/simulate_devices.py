"""Emulador de bancada dos DOIS ESP32 (para testes sem hardware).

Publica, em um broker MQTT, exatamente os mesmos tópicos e payloads dos
firmwares, com os mesmos client IDs. Use SOMENTE com um broker local ou
privado — no broker público você interferiria com os dispositivos reais.

    python scripts/simulate_devices.py --host localhost --port 1883 [--telemetria] [--perder 0.05]
"""
import argparse
import asyncio
import json
import math
import random
import sys

import aiomqtt

CMD = "iot/luzambiente/atuador/luz/comando"
STATUS = "iot/luzambiente/atuador/status"
TELEM = "iot/luzambiente/sensor/telemetria"


def classify(raw: int) -> str:
    return "escuro" if raw < 150 else "ambiente" if raw < 400 else "alta" if raw < 1000 else "extrema"


async def atuador(host, port, perder):
    async with aiomqtt.Client(host, port, identifier="atuador01") as c:
        await c.subscribe(CMD, qos=1)
        async for m in c.messages:
            try:
                cena = json.loads(m.payload).get("cena", "apagada")
            except Exception:
                print("atuador: Comando JSON inválido.")
                continue
            cena = str(cena)[:15]
            if random.random() < perder:
                print(f"atuador: (simulando falha) sem confirmação para {cena}")
                continue
            await asyncio.sleep(random.uniform(0.03, 0.2))
            await c.publish(STATUS, json.dumps({"device": "atuador01", "estado": f"{cena}_executada"},
                                               separators=(",", ":")), retain=True)
            print(f"atuador: {cena}_executada")


async def sensor(host, port, telemetria):
    atual, t = "", 0.0
    async with aiomqtt.Client(host, port, identifier="SensorNode01") as c:
        while True:
            t += 0.3
            raw = int(max(0, min(4095, 650 + 600 * math.sin(t / 15) + random.gauss(0, 30))))
            cena = classify(raw)
            if cena != atual:
                await c.publish(CMD, '{"cena":"' + cena + '"}')
                print(f"sensor: Mudança detetada! Comando enviado: {cena} (leitura {raw})")
                atual = cena
            if telemetria and int(t / 0.3) % 7 == 0:
                await c.publish(TELEM, json.dumps({"device": "SensorNode01", "leitura": raw, "cena": cena,
                                                   "uptime_ms": int(t * 1000)}))
            await asyncio.sleep(0.3)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--telemetria", action="store_true", help="emula também o patch opcional de telemetria")
    ap.add_argument("--perder", type=float, default=0.0, help="fração de confirmações descartadas")
    a = ap.parse_args()
    if "hivemq.com" in a.host:
        sys.exit("Recusado: não publique no broker público usado pelos dispositivos reais.")
    await asyncio.gather(atuador(a.host, a.port, a.perder), sensor(a.host, a.port, a.telemetria))


if __name__ == "__main__":
    asyncio.run(main())
