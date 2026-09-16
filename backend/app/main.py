import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import psycopg
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .automation import BAIXO, Cena, Config, ambiente_ocupado, decidir

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://iot:iot_aula@localhost:5432/iot")
BASE = os.getenv("MQTT_BASE_TOPIC", "iot/luzambiente")
STATIC = Path(__file__).parent / "static"

# --- SENSOR DE SOM: DESATIVADO POR ENQUANTO ---------------------------------
# O microfone ainda não foi montado. Em vez de remover o código, ele fica
# aqui pronto e desligado por esta flag. Toda a lógica de classificação de
# som (faixas + histerese, em automation.py) continua existindo e sendo
# testada; só não recebe leitura real. Enquanto SOM_HABILITADO=false, o
# backend decide usando um nível de som fixo (SOM_VALOR_PADRAO) e ignora o
# que chegar em `sensor/som` para fins de decisão (o valor ainda aparece no
# dashboard, se alguém publicar). Para reativar: monte o MAX9814, descomente
# a leitura no firmware e mude para "true" aqui.
SOM_HABILITADO = os.getenv("SOM_HABILITADO", "false").strip().lower() == "true"
SOM_VALOR_PADRAO = float(os.getenv("SOM_VALOR_PADRAO", "0"))
# -----------------------------------------------------------------------------

# --- SENSOR DE PRESENÇA: DESATIVADO POR ENQUANTO ----------------------------
# O PIR também não foi montado (nem substituto, como um botão). Enquanto
# OCUPACAO_HABILITADA=false, o ambiente é considerado SEMPRE ocupado, e a
# decisão depende só da luz. `ambiente_ocupado()` continua existindo e
# testada em automation.py para quando o sensor chegar.
#
# ATENÇÃO — pendência a levar ao professor: a família temática do grupo é
# "Iluminação e ocupação". Sem nenhum sensor (nem manual) de ocupação, essa
# metade do tema não está demonstrável ainda. O sistema funciona, mas hoje
# ele é, na prática, um controle de luz por luminosidade — como o
# projeto-base do professor. Isso deve virar uma tarefa visível no backlog.
OCUPACAO_HABILITADA = os.getenv("OCUPACAO_HABILITADA", "false").strip().lower() == "true"
# -----------------------------------------------------------------------------

CFG = Config(
    limiar_luz=float(os.getenv("AUTOMATION_LUZ_LIMIAR", "40")),
    histerese_luz=float(os.getenv("AUTOMATION_LUZ_HISTERESE", "8")),
    limiar_medio=float(os.getenv("AUTOMATION_SOM_MEDIO", "25")),
    limiar_alto=float(os.getenv("AUTOMATION_SOM_ALTO", "55")),
    histerese_som=float(os.getenv("AUTOMATION_SOM_HISTERESE", "6")),
    brilho_max=int(os.getenv("AUTOMATION_BRILHO_MAX", "120")),
    carencia_presenca_s=float(os.getenv("AUTOMATION_CARENCIA_S", "120")),
)

state = {
    "luz": None,
    "escuro": False,
    "som": None,
    "faixa_som": BAIXO,
    "movimento": False,
    "ocupado": not OCUPACAO_HABILITADA,  # sempre True enquanto o PIR não existe
    "ultimo_movimento": None,
    "cena": "apagada",
    "brilho": 0,
    "cor": {"r": 0, "g": 0, "b": 0},
    "animacao": "off",
    "modo": "automatico",
    "sensor_online": False,
    "atuador_online": False,
    "updated_at": None,
    "recursos": {
        "luz_habilitada": True,
        "som_habilitado": SOM_HABILITADO,
        "ocupacao_habilitada": OCUPACAO_HABILITADA,
    },
    "config": {
        "limiar_luz": CFG.limiar_luz,
        "histerese_luz": CFG.histerese_luz,
        "limiar_medio": CFG.limiar_medio,
        "limiar_alto": CFG.limiar_alto,
        "histerese_som": CFG.histerese_som,
        "brilho_max": CFG.brilho_max,
        "carencia_presenca_s": CFG.carencia_presenca_s,
    },
}
clients: set[WebSocket] = set()
main_loop: asyncio.AbstractEventLoop | None = None
state_lock = threading.Lock()
ultimo_movimento_ts: float | None = None

# Memória do último comando ENVIADO pela automação — separada de
# state["cena"], que só muda quando o ATUADOR confirma (topico
# atuador/status). Comparar com state["cena"] foi um bug real: sem a
# confirmação (atuador offline, ou atraso de rede), a decisão automática
# republicava a cada leitura mesmo sem nada ter mudado.
ultima_cena_enviada: tuple[str, int, str] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_execute(sql: str, params=()) -> None:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as connection:
            connection.execute(sql, params)
    except psycopg.Error as exc:
        print(f"banco indisponivel: {exc}")


async def broadcast() -> None:
    dead = []
    snapshot = dict(state)
    for ws in clients:
        try:
            await ws.send_json(snapshot)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def notify() -> None:
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(), main_loop)


def publicar_cena(cena: Cena, source: str) -> None:
    mqtt_client.publish(
        f"{BASE}/atuador/luz/comando",
        json.dumps(cena.to_payload(source)),
        qos=1,
    )


def aplicar_regra_se_automatico() -> None:
    """Chamado sempre que luz, som ou presença mudam. Assume state_lock tomado."""
    global ultima_cena_enviada
    if state["modo"] != "automatico":
        return
    if state["luz"] is None:
        return  # precisa de ao menos uma leitura do LDR antes de decidir

    nivel_luz = float(state["luz"])

    if SOM_HABILITADO and state["som"] is not None:
        nivel_som = float(state["som"])
    else:
        # Sensor de som fora do circuito por enquanto: usa um nível fixo em
        # vez de esperar uma leitura que nunca vai chegar.
        nivel_som = SOM_VALOR_PADRAO

    cena = decidir(
        bool(state["ocupado"]),
        nivel_luz,
        nivel_som,
        CFG,
        bool(state["escuro"]),
        str(state["faixa_som"]),
    )
    state["escuro"] = cena.escuro
    state["faixa_som"] = cena.faixa_som

    chave = (cena.nome, cena.brilho, cena.animacao)
    if chave != ultima_cena_enviada:
        ultima_cena_enviada = chave
        publicar_cena(cena, "automation")


def recalcular_ocupacao(agora: float) -> None:
    """Assume state_lock tomado."""
    if not OCUPACAO_HABILITADA:
        state["ocupado"] = True
        return
    desde = None if ultimo_movimento_ts is None else agora - ultimo_movimento_ts
    state["ocupado"] = ambiente_ocupado(
        bool(state["movimento"]), desde, CFG.carencia_presenca_s
    )


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"mqtt conectado: {reason_code}")
    client.subscribe(f"{BASE}/#", qos=1)


def on_message(client, userdata, message):
    global ultimo_movimento_ts
    topic = message.topic
    raw = message.payload.decode(errors="replace")

    if topic.endswith("/sensor/status"):
        with state_lock:
            state["sensor_online"] = raw.strip() == "online"
            state["updated_at"] = utc_now()
        notify()
        return
    if topic.endswith("/atuador/conexao"):
        with state_lock:
            state["atuador_online"] = raw.strip() == "online"
            state["updated_at"] = utc_now()
        notify()
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"JSON invalido em {topic}")
        return

    agora = time.monotonic()
    now_iso = utc_now()

    with state_lock:
        if topic == f"{BASE}/sensor/luminosidade":
            # Sensor ativo hoje: LDR no ESP32 sensor. Ver
            # firmware/esp32_sensor/src/main.cpp.
            try:
                valor = float(payload["value"])
            except (KeyError, TypeError, ValueError):
                return
            state.update(luz=valor, sensor_online=True, updated_at=now_iso)
            db_execute(
                "INSERT INTO telemetry(device, metric, value, payload) "
                "VALUES (%s,%s,%s,%s::jsonb)",
                (payload.get("device", "sensor01"), "luz", valor, json.dumps(payload)),
            )
            aplicar_regra_se_automatico()

        elif topic == f"{BASE}/sensor/som":
            # Este bloco continua ativo de propósito: se alguém publicar em
            # sensor/som (o simulador, por exemplo), o valor é guardado e
            # aparece no dashboard. Ele só não é *usado* na decisão
            # automática enquanto SOM_HABILITADO=false.
            try:
                valor = float(payload["value"])
            except (KeyError, TypeError, ValueError):
                return
            state.update(som=valor, sensor_online=True, updated_at=now_iso)
            db_execute(
                "INSERT INTO telemetry(device, metric, value, payload) "
                "VALUES (%s,%s,%s,%s::jsonb)",
                (payload.get("device", "sensor01"), "som", valor, json.dumps(payload)),
            )
            aplicar_regra_se_automatico()

        elif topic == f"{BASE}/sensor/presenca":
            # Idem: guardado e mostrado no dashboard, mas só influencia a
            # decisão quando OCUPACAO_HABILITADA=true.
            movimento = bool(payload.get("movimento", payload.get("value", False)))
            if movimento:
                ultimo_movimento_ts = agora
                state["ultimo_movimento"] = now_iso
            state.update(movimento=movimento, sensor_online=True, updated_at=now_iso)
            db_execute(
                "INSERT INTO telemetry(device, metric, value, payload) "
                "VALUES (%s,%s,%s,%s::jsonb)",
                (
                    payload.get("device", "sensor01"),
                    "presenca",
                    1.0 if movimento else 0.0,
                    json.dumps(payload),
                ),
            )
            recalcular_ocupacao(agora)
            aplicar_regra_se_automatico()

        elif topic == f"{BASE}/atuador/status":
            cor = payload.get("cor") or {}
            state.update(
                cena=str(payload.get("cena", state["cena"])),
                brilho=int(payload.get("brilho", state["brilho"])),
                animacao=str(payload.get("animacao", state["animacao"])),
                cor={
                    "r": int(cor.get("r", state["cor"]["r"])),
                    "g": int(cor.get("g", state["cor"]["g"])),
                    "b": int(cor.get("b", state["cor"]["b"])),
                },
                atuador_online=True,
                updated_at=now_iso,
            )
        else:
            return
    notify()


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="backend-luzambiente")
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message


class ComandoManual(BaseModel):
    brilho: int = Field(ge=0, le=255)
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    animacao: str = Field(default="estatica", pattern="^(off|estatica|respiracao|pulso)$")


async def vigia_ocupacao() -> None:
    """Reavalia a ocupação a cada 5 s.

    Sem isso, a carência do PIR nunca expiraria sozinha quando ele existir.
    Enquanto OCUPACAO_HABILITADA=false, `recalcular_ocupacao` sempre marca
    True e este laço não faz nada de visível.
    """
    while True:
        await asyncio.sleep(5)
        with state_lock:
            antes = state["ocupado"]
            recalcular_ocupacao(time.monotonic())
            if antes != state["ocupado"]:
                state["updated_at"] = utc_now()
                aplicar_regra_se_automatico()
                mudou = True
            else:
                mudou = False
        if mudou:
            await broadcast()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id BIGSERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    device TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value DOUBLE PRECISION NOT NULL,
                    payload JSONB NOT NULL
                )
            """)
    except psycopg.Error as exc:
        print(f"nao foi possivel criar a tabela agora: {exc}")
    mqtt_client.connect_async(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()
    vigia = asyncio.create_task(vigia_ocupacao())
    yield
    vigia.cancel()
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(title="Luz Ambiente Inteligente", version="1.0.0", lifespan=lifespan)


@app.get("/")
def dashboard():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def get_state():
    return state


@app.post("/api/manual")
def manual(comando: ComandoManual):
    global ultima_cena_enviada
    cena = Cena(
        "manual",
        comando.brilho,
        (comando.r, comando.g, comando.b),
        comando.animacao,
        bool(state["escuro"]),
        str(state["faixa_som"]),
    )
    with state_lock:
        state["modo"] = "manual"
        # Zera a memória de dedup: quando voltar ao automático, a próxima
        # decisão deve ser reenviada mesmo que "coincida" com a última
        # automática antes do manual, porque o atuador está com outra cena.
        ultima_cena_enviada = None
    publicar_cena(cena, "dashboard")
    notify()
    return {"accepted": True, **comando.model_dump()}


@app.post("/api/automatico")
def automatico():
    global ultima_cena_enviada
    with state_lock:
        state["modo"] = "automatico"
        if state["luz"] is None:
            raise HTTPException(409, "Ainda não há leitura de luminosidade")
        nivel_som = (
            float(state["som"])
            if SOM_HABILITADO and state["som"] is not None
            else SOM_VALOR_PADRAO
        )
        cena = decidir(
            bool(state["ocupado"]),
            float(state["luz"]),
            nivel_som,
            CFG,
            bool(state["escuro"]),
            str(state["faixa_som"]),
        )
        state["escuro"] = cena.escuro
        state["faixa_som"] = cena.faixa_som
        ultima_cena_enviada = (cena.nome, cena.brilho, cena.animacao)
    publicar_cena(cena, "automation")
    notify()
    return {"accepted": True, "modo": "automatico", "cena": cena.nome}


@app.get("/api/telemetry")
def telemetry(limit: int = 50, metric: str | None = None):
    safe_limit = max(1, min(limit, 500))
    sql = "SELECT recorded_at, device, metric, value FROM telemetry"
    params: tuple = ()
    if metric:
        sql += " WHERE metric = %s"
        params = (metric,)
    sql += " ORDER BY id DESC LIMIT %s"
    params = params + (safe_limit,)
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(sql, params).fetchall()
    return [
        {"at": row[0], "device": row[1], "metric": row[2], "value": row[3]}
        for row in rows
    ]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_json(state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)
