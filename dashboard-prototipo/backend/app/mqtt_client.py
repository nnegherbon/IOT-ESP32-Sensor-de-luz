"""Cliente MQTT do backend, com reconexão automática (backoff exponencial).

Assina os tópicos da N1 (histórico) e do contrato v1.1. No v1.1 o backend é o ÚNICO que publica comandos
(luzambiente/v1/atuador/<id>/comando); anuncia a própria presença em luzambiente/v1/backend/status (retido + LWT).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import ssl

import json

import aiomqtt

from .config import Settings
from .ingest import TelemetryService
from . import v1

log = logging.getLogger(__name__)


def make_client_id(prefix: str) -> str:
    # sufixo aleatório: um client ID repetido derrubaria SensorNode01/atuador01
    return f"{prefix}-{secrets.token_hex(4)}"


async def run_mqtt(settings: Settings, service: TelemetryService, stop: asyncio.Event) -> None:
    delay = settings.mqtt_reconnect_min_s
    attempts = 0
    client_id = make_client_id(settings.mqtt_client_id_prefix)
    tls = ssl.create_default_context() if settings.mqtt_tls else None
    control = service.control
    offline = json.dumps({"v": 1, "device": "backend", "online": False})
    will = aiomqtt.Will(v1.BACKEND_STATUS_TOPIC, offline, qos=1, retain=True)
    while not stop.is_set():
        attempts += 1
        await service.set_broker("conectando", host=settings.mqtt_host, port=settings.mqtt_port, attempts=attempts,
                                 error=service.broker.get("last_error"))
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host, port=settings.mqtt_port,
                username=settings.mqtt_username or None, password=settings.mqtt_password or None,
                identifier=client_id, keepalive=settings.mqtt_keepalive, tls_context=tls,
                clean_session=True, timeout=15, will=will,
            ) as client:
                await client.subscribe(settings.mqtt_subscribe, qos=1)
                await client.subscribe(settings.mqtt_subscribe_v1, qos=1)
                await client.publish(v1.BACKEND_STATUS_TOPIC, json.dumps({"v": 1, "device": "backend", "online": True}),
                                     qos=1, retain=True)
                if control is not None:
                    async def publish(topic: str, text: str, qos: int, retain: bool) -> None:
                        await client.publish(topic, text, qos=qos, retain=retain)
                    control.publisher = publish
                log.info("MQTT conectado a %s:%s (client_id=%s, assinatura=%s)",
                         settings.mqtt_host, settings.mqtt_port, client_id, settings.mqtt_subscribe)
                attempts = 0
                delay = settings.mqtt_reconnect_min_s
                await service.set_broker("conectado", attempts=0)
                async for msg in client.messages:
                    if stop.is_set():
                        break
                    payload = msg.payload if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload).encode()
                    await service.handle(str(msg.topic), bytes(payload), qos=msg.qos, retained=bool(msg.retain))
        except asyncio.CancelledError:
            if control is not None:
                control.publisher = None
            raise
        except aiomqtt.MqttError as e:
            log.warning("MQTT desconectado: %s (nova tentativa em %.0fs)", e, delay)
            await service.set_broker("desconectado", error=str(e), attempts=attempts)
        except Exception as e:  # erro inesperado: não derruba o serviço
            log.exception("erro no laço MQTT")
            await service.set_broker("desconectado", error=f"{type(e).__name__}: {e}", attempts=attempts)
        if control is not None:
            control.publisher = None
        if stop.is_set():
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        delay = min(delay * 2, settings.mqtt_reconnect_max_s)
