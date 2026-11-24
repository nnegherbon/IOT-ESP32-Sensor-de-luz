"""Contrato v1.1, regra de decisão no backend, ciclo do comando com cmd_id e autenticação (R3, R4, R7, R8, R9, R16)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import parsing as p
from app import v1
from app.auth import Auth, AuthError
from app.control import ControlService, DecisionConfig, DecisionEngine
from tests.conftest import build_service

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def js(obj) -> bytes:
    return json.dumps(obj).encode()


# ------------------------------------------------------------------ contrato
def test_telemetria_valida():
    m = p.parse("luzambiente/v1/sensor/sensor01/telemetria",
                js({"v": 1, "device": "sensor01", "seq": 5, "uptime_ms": 1000, "ldr_raw": 812, "amostras": 16}))
    assert isinstance(m, p.V1Msg) and m.obj.raw == 812 and m.obj.sensor_ok


@pytest.mark.parametrize("payload,reason", [
    ({"device": "sensor01", "seq": 1, "uptime_ms": 1, "ldr_raw": 10}, "versao_invalida"),
    ({"v": 1, "device": "sensor01", "seq": 1, "uptime_ms": 1, "ldr_raw": 5000}, "ldr_raw_fora_da_faixa_adc"),
    ({"v": 1, "device": "sensor02", "seq": 1, "uptime_ms": 1, "ldr_raw": 10}, "device_diferente_do_topico"),
    ({"v": 1, "device": "sensor01", "seq": -1, "uptime_ms": 1, "ldr_raw": 10}, "campo_seq_invalido"),
])
def test_telemetria_invalida_e_rejeitada(payload, reason):
    m = p.parse("luzambiente/v1/sensor/sensor01/telemetria", js(payload))
    assert isinstance(m, p.ParseError) and m.reason == reason


def test_ack_exige_motivo_quando_rejeitado():
    t = "luzambiente/v1/atuador/atuador01/ack"
    ok = p.parse(t, js({"v": 1, "device": "atuador01", "cmd_id": "c-20261124-000001", "resultado": "rejeitado",
                        "motivo": "modo_seguro"}))
    assert isinstance(ok, p.V1Msg)
    bad = p.parse(t, js({"v": 1, "device": "atuador01", "cmd_id": "c-20261124-000001", "resultado": "rejeitado",
                         "motivo": None}))
    assert isinstance(bad, p.ParseError)


def test_payload_maior_que_512_bytes():
    m = p.parse("luzambiente/v1/sensor/sensor01/telemetria", b"{" + b" " * 600 + b"}")
    assert isinstance(m, p.ParseError) and m.reason == "payload_maior_que_512_bytes"


def test_build_command_regras():
    c = v1.build_command("c-20261124-000001", origem="auto", acao="aplicar", cena="extrema", now=T0)
    assert c["sombra"] == "fechada" and c["v"] == 1 and c["ts"] == "2026-11-24T12:00:00Z"
    assert v1.build_command("c-20261124-000002", origem="manual", acao="definir_modo", modo="manual")["duracao_s"] == 300
    with pytest.raises(ValueError):
        v1.build_command("c-20261124-000003", origem="auto", acao="definir_modo", modo="manual")
    with pytest.raises(ValueError):
        v1.build_command("c-20261124-000004", origem="manual", acao="aplicar", cena="noite")


# ------------------------------------------------------------------- decisão
def test_decisao_com_histerese_e_confirmacao():
    e = DecisionEngine(DecisionConfig(histerese=40, confirmacao_s=3))
    assert e.update(565, T0) == "alta"
    assert e.update(1010, T0 + timedelta(seconds=1)) == "alta"       # dentro da folga: não troca
    assert e.update(1050, T0 + timedelta(seconds=2)) == "alta"       # candidato, aguardando 3 s
    assert e.update(1060, T0 + timedelta(seconds=4)) == "alta"
    assert e.update(1070, T0 + timedelta(seconds=5.5)) == "extrema"  # estável por 3,5 s
    assert e.update(980, T0 + timedelta(seconds=6)) == "extrema"     # acima de 1000-40: continua
    assert e.update(900, T0 + timedelta(seconds=7)) == "extrema"     # candidato a alta
    assert e.update(1100, T0 + timedelta(seconds=8)) == "extrema"    # voltou: descarta
    assert e.update(900, T0 + timedelta(seconds=9)) == "extrema"


# --------------------------------------------------------------------- auth
def test_auth_perfis_e_token():
    a = Auth("admin:s3nha:admin,ana:abc:operador", "segredo", 1)
    token, user = a.login("admin", "s3nha")
    assert user.can_command and a.verify(token).username == "admin"
    _, op = a.login("ana", "abc")
    assert not op.can_command
    with pytest.raises(AuthError):
        a.login("admin", "errada")
    with pytest.raises(AuthError):
        a.verify(token[:-2] + "xx")
    with pytest.raises(AuthError):
        Auth("admin:s3nha:admin", "outro-segredo").verify(token)


# ------------------------------------------------------- ciclo do comando (R7)
class FakeBroker:
    def __init__(self):
        self.sent = []

    async def __call__(self, topic, text, qos, retain):
        self.sent.append((topic, json.loads(text)))


async def setup_control(service):
    control = ControlService(service)
    await control.load()
    service.control = control
    broker = FakeBroker()
    control.publisher = broker
    return control, broker


def estado(cena, modo="auto", ultimo=None, sombra="aberta"):
    leds = {"escuro": [True, False, False, False], "ambiente": [False, True, False, False],
            "alta": [False, False, True, False], "extrema": [True, True, True, True], None: [False] * 4}[cena]
    return js({"v": 1, "device": "atuador01", "modo": modo, "cena": cena, "leds": leds, "sombra": sombra,
               "servo_graus": 90 if sombra == "fechada" else 0, "manual_restante_s": None,
               "ultimo_cmd_id": ultimo, "uptime_ms": 1000})


@pytest.mark.asyncio
async def test_regra_gera_comando_e_ciclo_ate_confirmar(service):
    control, broker = await setup_control(service)
    control.cfg.confirmacao_s = 0
    await service.handle("luzambiente/v1/atuador/atuador01/status", js({"v": 1, "device": "atuador01", "online": True}))
    await service.handle("luzambiente/v1/atuador/atuador01/estado", estado("alta"), retained=True)
    for seq, raw in enumerate((565, 1200, 1210)):
        await service.handle("luzambiente/v1/sensor/sensor01/telemetria",
                             js({"v": 1, "device": "sensor01", "seq": seq, "uptime_ms": 100 * seq, "ldr_raw": raw}))
    assert len(broker.sent) == 1
    topic, cmd = broker.sent[0]
    assert topic == "luzambiente/v1/atuador/atuador01/comando"
    assert cmd["cena"] == "extrema" and cmd["sombra"] == "fechada" and cmd["origem"] == "auto"
    cid = cmd["cmd_id"]

    ack = "luzambiente/v1/atuador/atuador01/ack"
    await service.handle(ack, js({"v": 1, "device": "atuador01", "cmd_id": cid, "resultado": "recebido", "motivo": None}))
    await service.handle(ack, js({"v": 1, "device": "atuador01", "cmd_id": cid, "resultado": "executado", "motivo": None}))
    await service.handle("luzambiente/v1/atuador/atuador01/estado", estado("extrema", ultimo=cid, sombra="fechada"))
    async with service.pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM commands WHERE cmd_id=$1", cid)
    assert r["status"] == "confirmado" and r["received_at"] and r["executed_at"] and r["confirmed_at"]
    assert r["requested_by"] == "regra:cena_por_luminosidade"
    # o painel de visão geral acompanha o comando v1 e não acusa divergência
    assert service.sensor["last_command"]["cena"] == "extrema"
    assert service.sensor["last_command"]["status"] == "confirmado"
    assert service.sync_state() == "sincronizado"

    # ack duplicado (QoS 1 / reenvio) não muda o estado, só é contado
    await service.handle(ack, js({"v": 1, "device": "atuador01", "cmd_id": cid, "resultado": "executado", "motivo": None}))
    async with service.pool.acquire() as c:
        r = await c.fetchrow("SELECT status, duplicate_acks FROM commands WHERE cmd_id=$1", cid)
    assert r["status"] == "confirmado" and r["duplicate_acks"] == 1


@pytest.mark.asyncio
async def test_rejeicao_com_motivo_e_modo_manual_suspende_regra(service):
    control, broker = await setup_control(service)
    await service.handle("luzambiente/v1/atuador/atuador01/estado", estado("alta", modo="manual"), retained=True)
    cmd = await control.issue("atuador01", origem="manual", acao="aplicar", cena="escuro", requested_by="admin")
    await service.handle("luzambiente/v1/atuador/atuador01/ack",
                         js({"v": 1, "device": "atuador01", "cmd_id": cmd["cmd_id"], "resultado": "rejeitado",
                             "motivo": "intertravamento"}))
    async with service.pool.acquire() as c:
        r = await c.fetchrow("SELECT status, motivo FROM commands WHERE cmd_id=$1", cmd["cmd_id"])
    assert (r["status"], r["motivo"]) == ("rejeitado", "intertravamento")
    # em MANUAL a regra automática não comanda
    await service.handle("luzambiente/v1/sensor/sensor01/telemetria",
                         js({"v": 1, "device": "sensor01", "seq": 1, "uptime_ms": 1, "ldr_raw": 3000}))
    assert len(broker.sent) == 1


@pytest.mark.asyncio
async def test_sem_broker_registra_falha_de_envio(service):
    control, _ = await setup_control(service)
    control.publisher = None
    cmd = await control.issue("atuador01", origem="manual", acao="definir_modo", modo="auto", requested_by="admin")
    assert cmd["status"] == "falha_envio" and "broker" in cmd["motivo"]


@pytest.mark.asyncio
async def test_falha_de_sensor_abre_alerta_e_nao_comanda(service):
    control, broker = await setup_control(service)
    await service.handle("luzambiente/v1/atuador/atuador01/estado", estado("alta"), retained=True)
    await service.handle("luzambiente/v1/sensor/sensor01/telemetria",
                         js({"v": 1, "device": "sensor01", "seq": 1, "uptime_ms": 1, "ldr_raw": 4095,
                             "sensor_ok": False, "falha": "saturado"}))
    assert broker.sent == []
    assert any(a["kind"] == "sensor_fault" for a in service.alerts.open.values())


@pytest.mark.asyncio
async def test_mensagem_invalida_e_registrada(service):
    await setup_control(service)
    r = await service.handle("luzambiente/v1/sensor/sensor01/telemetria", b'{"v":1,"device":"sensor01"}')
    assert r["status"] == "invalido"
    async with service.pool.acquire() as c:
        row = await c.fetchrow("SELECT parse_status, error_reason FROM mqtt_messages ORDER BY id DESC LIMIT 1")
    assert row["parse_status"] == "invalido" and row["error_reason"] == "campo_seq_invalido"
