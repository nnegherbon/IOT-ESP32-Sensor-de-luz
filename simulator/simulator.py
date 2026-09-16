"""Simulador do nó sensor e do nó atuador.

Permite demonstrar o ciclo completo sem nenhum hardware: você digita o nível
de luz e vê a cena decidida pelo backend aparecer no dashboard. Som ('s') e
presença ('p') também podem ser publicados — úteis para testar o backend
antes mesmo do microfone/PIR chegarem — mas só afetam a cena depois que
SOM_HABILITADO / OCUPACAO_HABILITADA forem ligados no backend.

Uso:
    docker compose --profile tools run --rm simulator

Comandos:
    80          nível de luz em % (0-100; maior = mais claro)
    s 40        nível de som em % (inerte por padrão — ver acima)
    p           alterna movimento/presença (inerte por padrão — ver acima)
    auto        luz variando sozinha até você apertar Enter
    q           sai
"""

import json
import os
import random
import threading
import time

import paho.mqtt.client as mqtt

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
BASE = os.getenv("MQTT_BASE_TOPIC", "iot/luzambiente")

atuador = {"cena": "apagada", "brilho": 0, "cor": {"r": 0, "g": 0, "b": 0}, "animacao": "off"}
lock = threading.Lock()
movimento = False
rodando_auto = threading.Event()


def publicar_status(client):
    client.publish(
        f"{BASE}/atuador/status",
        json.dumps({"device": "atuador-sim", **atuador}),
        qos=1,
        retain=True,
    )


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(f"{BASE}/atuador/luz/comando", qos=1)
    client.publish(f"{BASE}/sensor/status", "online", retain=True)
    client.publish(f"{BASE}/atuador/conexao", "online", retain=True)
    publicar_status(client)
    print(f"conectado em {HOST}:{PORT}, prefixo {BASE}")


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
    except json.JSONDecodeError:
        return
    with lock:
        atuador.update(
            cena=payload.get("cena", atuador["cena"]),
            brilho=int(payload.get("brilho", atuador["brilho"])),
            cor=payload.get("cor", atuador["cor"]),
            animacao=payload.get("animacao", atuador["animacao"]),
        )
        cor = atuador["cor"]
        print(
            f"  [atuador] cena={atuador['cena']:8s} brilho={atuador['brilho']:3d} "
            f"cor=({cor['r']},{cor['g']},{cor['b']}) efeito={atuador['animacao']}"
        )
        publicar_status(client)


def publicar_luz(client, valor: float):
    client.publish(
        f"{BASE}/sensor/luminosidade",
        json.dumps({"device": "sensor-sim", "value": valor, "unit": "%"}),
        qos=1,
    )


def publicar_som(client, valor: float):
    client.publish(
        f"{BASE}/sensor/som",
        json.dumps({"device": "sensor-sim", "value": valor, "unit": "%"}),
        qos=1,
    )


def publicar_presenca(client, mov: bool):
    client.publish(
        f"{BASE}/sensor/presenca",
        json.dumps({"device": "sensor-sim", "movimento": mov}),
        qos=1,
    )


def laco_automatico(client):
    """Luz andando sozinha, como o sol passando por uma janela."""
    valor = 50.0
    while rodando_auto.is_set():
        valor = max(0.0, min(100.0, valor + random.uniform(-15, 15)))
        publicar_luz(client, round(valor, 1))
        time.sleep(1.0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulador-luzambiente")
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT)
client.loop_start()
time.sleep(0.5)

publicar_presenca(client, movimento)
print(__doc__.split("Comandos:")[1])

try:
    while True:
        entrada = input("luz%/s <valor>/p/auto/q> ").strip().lower()
        if entrada == "q":
            break
        if entrada == "p":
            movimento = not movimento
            publicar_presenca(client, movimento)
            print(f"  [sensor] movimento={'sim' if movimento else 'nao'} (inerte por padrao)")
            continue
        if entrada == "auto":
            rodando_auto.set()
            threading.Thread(target=laco_automatico, args=(client,), daemon=True).start()
            input("  variando a luz... Enter para parar. ")
            rodando_auto.clear()
            continue
        if entrada.startswith("s"):
            partes = entrada.split()
            if len(partes) != 2:
                print("  use: s <valor de 0 a 100>")
                continue
            try:
                valor = max(0.0, min(100.0, float(partes[1])))
            except ValueError:
                print("  use: s <valor de 0 a 100>")
                continue
            publicar_som(client, valor)
            print(f"  [sensor] som={valor}% (inerte por padrao)")
            continue
        try:
            valor = max(0.0, min(100.0, float(entrada)))
        except ValueError:
            print("  digite um numero de 0 a 100 (luz), ou s <valor> / p / auto / q")
            continue
        publicar_luz(client, valor)
except (KeyboardInterrupt, EOFError):
    pass
finally:
    rodando_auto.clear()
    client.publish(f"{BASE}/sensor/status", "offline", retain=True)
    client.publish(f"{BASE}/atuador/conexao", "offline", retain=True)
    client.loop_stop()
    client.disconnect()
