"""Validação e interpretação das mensagens MQTT.

Funções puras: recebem tópico + bytes e devolvem um objeto tipado ou um
ParseError. Não tocam em banco nem em estado — fáceis de testar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Union

from . import firmware as fw

MAX_PAYLOAD_BYTES = 4096


@dataclass
class CommandMsg:
    """Sensor -> atuador: {"cena": "..."}"""
    cena: str
    known_scene: bool
    actuator_scene: str  # como o atuador vai armazenar (truncada)


@dataclass
class ConfirmationMsg:
    """Atuador -> broker: {"device": "...", "estado": "<cena>_executada"}"""
    device: str
    estado: str
    cena: str
    known_scene: bool
    leds: tuple[bool, bool, bool, bool]


@dataclass
class TelemetryMsg:
    """Opcional (patch): {"leitura": int, "cena"?: str, "uptime_ms"?: int}"""
    raw: int
    cena_reported: str | None
    cena_computed: str
    uptime_ms: int | None
    device: str | None


@dataclass
class ConnectionMsg:
    """Opcional (patch): {"device": "...", "status": "online"|"offline"}"""
    component: str  # sensor | atuador
    device: str | None
    status: str


@dataclass
class UnhandledMsg:
    """Tópico sob a base que o backend ainda não interpreta (ex.: servo futuro)."""
    payload_json: Any | None = None


@dataclass
class ParseError:
    reason: str
    details: dict = field(default_factory=dict)


Parsed = Union[CommandMsg, ConfirmationMsg, TelemetryMsg, ConnectionMsg, UnhandledMsg, ParseError]


def topic_origin(topic: str) -> str:
    if topic in (fw.TOPIC_COMMAND, fw.TOPIC_SENSOR_TELEMETRY, fw.TOPIC_SENSOR_CONNECTION):
        return "sensor"
    if topic in (fw.TOPIC_ACTUATOR_STATUS, fw.TOPIC_ACTUATOR_CONNECTION):
        return "atuador"
    return "desconhecida"


def _load_object(payload: bytes) -> dict | ParseError:
    if len(payload) > MAX_PAYLOAD_BYTES:
        return ParseError("payload_muito_grande", {"bytes": len(payload)})
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return ParseError("utf8_invalido")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return ParseError("json_invalido", {"erro": str(e)})
    if not isinstance(data, dict):
        return ParseError("json_nao_objeto", {"tipo": type(data).__name__})
    return data


def _parse_command(data: dict) -> Parsed:
    cena = data.get("cena")
    if not isinstance(cena, str) or not cena.strip():
        # O atuador usaria "apagada" como fallback; registramos como inválido
        # porque o sensor original sempre envia uma das 4 cenas.
        return ParseError("campo_cena_ausente_ou_invalido", {"cena": cena})
    return CommandMsg(cena=cena, known_scene=cena in fw.SCENE_KEYS,
                      actuator_scene=fw.actuator_view_of_scene(cena))


def _parse_confirmation(data: dict) -> Parsed:
    device = data.get("device")
    estado = data.get("estado")
    if not isinstance(device, str) or not device:
        return ParseError("campo_device_ausente", {"device": device})
    if not isinstance(estado, str) or not estado.endswith("_executada"):
        return ParseError("campo_estado_invalido", {"estado": estado})
    cena = estado[: -len("_executada")]
    return ConfirmationMsg(device=device, estado=estado, cena=cena,
                           known_scene=cena in fw.SCENE_KEYS,
                           leds=fw.leds_for_scene(cena))


def _parse_telemetry(data: dict) -> Parsed:
    raw = data.get("leitura")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return ParseError("campo_leitura_invalido", {"leitura": raw})
    if not fw.ADC_MIN <= raw <= fw.ADC_MAX:
        return ParseError("leitura_fora_da_faixa_adc", {"leitura": raw})
    reported = data.get("cena")
    if reported is not None and not isinstance(reported, str):
        return ParseError("campo_cena_invalido", {"cena": reported})
    uptime = data.get("uptime_ms")
    if uptime is not None and (isinstance(uptime, bool) or not isinstance(uptime, int) or uptime < 0):
        uptime = None
    device = data.get("device") if isinstance(data.get("device"), str) else None
    return TelemetryMsg(raw=raw, cena_reported=reported, cena_computed=fw.classify(raw),
                        uptime_ms=uptime, device=device)


def _parse_connection(component: str, data: dict) -> Parsed:
    status = data.get("status")
    if status not in ("online", "offline"):
        return ParseError("campo_status_invalido", {"status": status})
    device = data.get("device") if isinstance(data.get("device"), str) else None
    return ConnectionMsg(component=component, device=device, status=status)


def parse(topic: str, payload: bytes) -> Parsed:
    if topic not in (fw.TOPIC_COMMAND, fw.TOPIC_ACTUATOR_STATUS, fw.TOPIC_SENSOR_TELEMETRY,
                     fw.TOPIC_SENSOR_CONNECTION, fw.TOPIC_ACTUATOR_CONNECTION):
        try:
            return UnhandledMsg(json.loads(payload.decode("utf-8")) if payload else None)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return UnhandledMsg(None)

    if topic == fw.TOPIC_ACTUATOR_STATUS and payload == b"":
        # Mensagem vazia retida = alguém limpou o retain do tópico
        return ParseError("payload_vazio")

    data = _load_object(payload)
    if isinstance(data, ParseError):
        return data
    if topic == fw.TOPIC_COMMAND:
        return _parse_command(data)
    if topic == fw.TOPIC_ACTUATOR_STATUS:
        return _parse_confirmation(data)
    if topic == fw.TOPIC_SENSOR_TELEMETRY:
        return _parse_telemetry(data)
    if topic == fw.TOPIC_SENSOR_CONNECTION:
        return _parse_connection("sensor", data)
    return _parse_connection("atuador", data)
