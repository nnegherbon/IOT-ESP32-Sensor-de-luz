"""Validação dos payloads exatamente como o firmware os produz."""
import pytest

from app import firmware as fw
from app import parsing as p


@pytest.mark.parametrize("raw,cena", [
    (0, "escuro"), (149, "escuro"), (150, "ambiente"), (399, "ambiente"),
    (400, "alta"), (999, "alta"), (1000, "extrema"), (4095, "extrema"),
])
def test_classify_matches_sensor_firmware_boundaries(raw, cena):
    assert fw.classify(raw) == cena


def test_led_mapping_matches_actuator_firmware():
    assert fw.leds_for_scene("escuro") == (False, True, False, False)    # GPIO26
    assert fw.leds_for_scene("ambiente") == (True, False, False, False)  # GPIO27
    assert fw.leds_for_scene("alta") == (False, False, True, False)      # GPIO25
    assert fw.leds_for_scene("extrema") == (True, True, True, True)      # todos
    assert fw.leds_for_scene("apagada") == (False, False, False, False)
    assert fw.leds_for_scene("qualquer") == (False, False, False, False)


def test_sensor_command_payload():
    # String payload = "{\"cena\":\"" + novaCena + "\"}";
    m = p.parse(fw.TOPIC_COMMAND, b'{"cena":"extrema"}')
    assert isinstance(m, p.CommandMsg)
    assert m.cena == "extrema" and m.known_scene


def test_actuator_status_payload():
    # snprintf(..., "{\"device\":\"%s\",\"estado\":\"%s_executada\"}", DEVICE_ID, cenaAtual)
    m = p.parse(fw.TOPIC_ACTUATOR_STATUS, b'{"device":"atuador01","estado":"ambiente_executada"}')
    assert isinstance(m, p.ConfirmationMsg)
    assert (m.device, m.cena, m.leds) == ("atuador01", "ambiente", (True, False, False, False))


def test_actuator_default_state_is_parsed_but_unknown():
    m = p.parse(fw.TOPIC_ACTUATOR_STATUS, b'{"device":"atuador01","estado":"apagada_executada"}')
    assert isinstance(m, p.ConfirmationMsg) and not m.known_scene


def test_unknown_scene_is_accepted_but_flagged():
    m = p.parse(fw.TOPIC_COMMAND, b'{"cena":"neblina"}')
    assert isinstance(m, p.CommandMsg) and not m.known_scene


def test_actuator_truncation_is_modelled():
    m = p.parse(fw.TOPIC_COMMAND, b'{"cena":"abcdefghijklmnopqrstu"}')
    assert m.actuator_scene == "abcdefghijklmno"


@pytest.mark.parametrize("topic,payload,reason", [
    (fw.TOPIC_COMMAND, b'{"cena": ', "json_invalido"),
    (fw.TOPIC_COMMAND, b'["extrema"]', "json_nao_objeto"),
    (fw.TOPIC_COMMAND, b'{"scene":"alta"}', "campo_cena_ausente_ou_invalido"),
    (fw.TOPIC_COMMAND, b'{"cena": 3}', "campo_cena_ausente_ou_invalido"),
    (fw.TOPIC_COMMAND, b'\xff\xfe', "utf8_invalido"),
    (fw.TOPIC_ACTUATOR_STATUS, b'{"estado":"alta_executada"}', "campo_device_ausente"),
    (fw.TOPIC_ACTUATOR_STATUS, b'{"device":"atuador01","estado":"alta"}', "campo_estado_invalido"),
    (fw.TOPIC_ACTUATOR_STATUS, b'', "payload_vazio"),
    (fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura": 5000}', "leitura_fora_da_faixa_adc"),
    (fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura": "12"}', "campo_leitura_invalido"),
    (fw.TOPIC_SENSOR_TELEMETRY, b'{"leitura": true}', "campo_leitura_invalido"),
    (fw.TOPIC_SENSOR_CONNECTION, b'{"status": "talvez"}', "campo_status_invalido"),
    (fw.TOPIC_COMMAND, b"x" * (p.MAX_PAYLOAD_BYTES + 1), "payload_muito_grande"),
])
def test_invalid_messages(topic, payload, reason):
    m = p.parse(topic, payload)
    assert isinstance(m, p.ParseError) and m.reason == reason


def test_optional_telemetry_payload():
    m = p.parse(fw.TOPIC_SENSOR_TELEMETRY, b'{"device":"SensorNode01","leitura":412,"cena":"alta","uptime_ms":1000}')
    assert isinstance(m, p.TelemetryMsg)
    assert (m.raw, m.cena_computed, m.cena_reported) == (412, "alta", "alta")


def test_unknown_topic_under_base_is_kept_unhandled():
    m = p.parse("iot/luzambiente/atuador/servo/posicao", b'{"graus": 90}')
    assert isinstance(m, p.UnhandledMsg) and m.payload_json == {"graus": 90}
