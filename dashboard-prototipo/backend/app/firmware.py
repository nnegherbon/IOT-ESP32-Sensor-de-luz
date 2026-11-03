"""Contrato com o firmware do repositório nnegherbon/IOT-ESP32-Sensor-de-luz.

Tudo neste arquivo foi extraído de Sensor_de_luz.ino e Atuador_LED.ino.
Se o firmware mudar, este é o único lugar a atualizar.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Identificadores usados pelos dispositivos (mqtt.connect(...)) ----------
# O backend NUNCA deve usar estes client IDs: em MQTT um client ID duplicado
# derruba a sessão do dispositivo que já está conectado.
SENSOR_CLIENT_ID = "SensorNode01"
ACTUATOR_DEVICE_ID = "atuador01"

# --- Tópicos (BASE "iot/luzambiente") ---------------------------------------
TOPIC_BASE = "iot/luzambiente"
# Sensor -> Atuador. Payload: {"cena":"<cena>"}; QoS 0, não retido.
# Publicado APENAS quando a cena muda (enviarCena compara com cenaAtual).
TOPIC_COMMAND = f"{TOPIC_BASE}/atuador/luz/comando"
# Atuador -> broker. Payload: {"device":"atuador01","estado":"<cena>_executada"}
# Publicado RETIDO (retain=true) após cada comando executado.
TOPIC_ACTUATOR_STATUS = f"{TOPIC_BASE}/atuador/status"

# --- Tópicos opcionais (somente com o patch aditivo em firmware-patch/) -----
# O firmware original NÃO publica nestes tópicos. O backend apenas os escuta;
# enquanto ninguém publicar, nada é exibido como existente.
TOPIC_SENSOR_TELEMETRY = f"{TOPIC_BASE}/sensor/telemetria"
TOPIC_SENSOR_CONNECTION = f"{TOPIC_BASE}/sensor/conexao"
TOPIC_ACTUATOR_CONNECTION = f"{TOPIC_BASE}/atuador/conexao"

# --- ADC / cenas -------------------------------------------------------------
# analogRead() no ESP32 (GPIO34) com resolução padrão de 12 bits: 0..4095.
# Valor bruto, sem calibração para lux.
ADC_MIN = 0
ADC_MAX = 4095


@dataclass(frozen=True)
class Scene:
    key: str
    label: str
    lower: int | None  # inclusivo
    upper: int | None  # exclusivo
    order: int


# Limites de Sensor_de_luz.ino (loop): <150 | 150..399 | 400..999 | >=1000
SCENES: tuple[Scene, ...] = (
    Scene("escuro", "Escuro", None, 150, 0),
    Scene("ambiente", "Ambiente", 150, 400, 1),
    Scene("alta", "Alta", 400, 1000, 2),
    Scene("extrema", "Extrema", 1000, None, 3),
)
SCENE_KEYS = tuple(s.key for s in SCENES)

# Valor inicial de cenaAtual no atuador e fallback de doc["cena"] | "apagada"
ACTUATOR_DEFAULT_SCENE = "apagada"
# cenaAtual no atuador é char[16]: a cena é truncada em 15 caracteres
ACTUATOR_SCENE_MAXLEN = 15

# --- LEDs do atuador (Atuador_LED.ino) --------------------------------------
LEDS = (
    {"id": 1, "name": "LED 1", "gpio": 27, "const": "PIN_LED_AMBIENTE"},
    {"id": 2, "name": "LED 2", "gpio": 26, "const": "PIN_LED_ESCURO"},
    {"id": 3, "name": "LED 3", "gpio": 25, "const": "PIN_LED_ALTA"},
    {"id": 4, "name": "LED 4", "gpio": 33, "const": "PIN_LED_EXTREMA"},
)

# Lógica de onMessage(): desligarTodos() e depois acende conforme a cena.
# Observação: na cena "extrema" o firmware acende os QUATRO LEDs.
_SCENE_LEDS: dict[str, tuple[bool, bool, bool, bool]] = {
    "escuro": (False, True, False, False),
    "ambiente": (True, False, False, False),
    "alta": (False, False, True, False),
    "extrema": (True, True, True, True),
}


def classify(raw: int) -> str:
    """Replica exatamente a cadeia if/else do loop() do sensor."""
    if raw < 150:
        return "escuro"
    if raw < 400:
        return "ambiente"
    if raw < 1000:
        return "alta"
    return "extrema"


def leds_for_scene(scene: str | None) -> tuple[bool, bool, bool, bool]:
    """Estado dos LEDs que o firmware do atuador produz para a cena.

    Cenas desconhecidas (inclusive "apagada"): todos desligados, pois o
    atuador chama desligarTodos() e nenhum ramo do if casa.
    """
    return _SCENE_LEDS.get(scene or "", (False, False, False, False))


def actuator_view_of_scene(scene: str) -> str:
    """Como o atuador armazena a cena (strlcpy em char[16])."""
    return scene[:ACTUATOR_SCENE_MAXLEN]


def firmware_description() -> dict:
    return {
        "topics": {
            "command": TOPIC_COMMAND,
            "actuator_status": TOPIC_ACTUATOR_STATUS,
            "optional": {
                "sensor_telemetry": TOPIC_SENSOR_TELEMETRY,
                "sensor_connection": TOPIC_SENSOR_CONNECTION,
                "actuator_connection": TOPIC_ACTUATOR_CONNECTION,
            },
        },
        "device_ids": {"sensor": SENSOR_CLIENT_ID, "actuator": ACTUATOR_DEVICE_ID},
        "adc": {"min": ADC_MIN, "max": ADC_MAX, "unit": "leitura bruta ADC (12 bits)"},
        "scenes": [
            {"key": s.key, "label": s.label, "lower": s.lower, "upper": s.upper, "order": s.order,
             "leds": list(leds_for_scene(s.key))}
            for s in SCENES
        ],
        "leds": list(LEDS),
    }
