"""Contrato MQTT v1.1 (luzambiente/v1/...): tópicos, validação dos payloads e montagem dos comandos.

Funções puras, sem banco: o mesmo papel de parsing.py para o contrato da N1.
Documentação: CONTRATOS.md na raiz do repositório.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PREFIX = "luzambiente/v1"
SUBSCRIPTION = f"{PREFIX}/#"
DEVICE_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
CMD_ID_RE = re.compile(r"^c-[0-9]{8}-[0-9]{6}$")
SCENES = ("escuro", "ambiente", "alta", "extrema")
SHADE = ("aberta", "fechada")
MODES = ("auto", "manual", "seguro")
ACK_RESULTS = ("recebido", "executado", "rejeitado")  # "recebido" entrou na v1.1
REJECT_REASONS = ("payload_invalido", "modo_seguro", "modo_incompativel", "intertravamento", "duplicado")
MAX_PAYLOAD = 512
BACKEND_STATUS_TOPIC = f"{PREFIX}/backend/status"


def topic_comando(device: str) -> str:
    return f"{PREFIX}/atuador/{device}/comando"


def topic_config(role: str, device: str) -> str:
    return f"{PREFIX}/{role}/{device}/config"


@dataclass
class V1Status:
    role: str  # sensor | atuador | backend
    device: str
    online: bool
    fw: str | None = None
    ip: str | None = None
    rssi: int | None = None


@dataclass
class V1Telemetry:
    device: str
    seq: int
    uptime_ms: int
    raw: int
    amostras: int | None
    rssi: int | None
    sensor_ok: bool
    falha: str | None
    hora_sync: bool | None


@dataclass
class V1Ack:
    device: str
    cmd_id: str
    resultado: str
    motivo: str | None
    uptime_ms: int | None


@dataclass
class V1Estado:
    device: str
    modo: str
    cena: str | None
    leds: tuple[bool, bool, bool, bool]
    sombra: str | None
    servo_graus: int | None
    manual_restante_s: int | None
    ultimo_cmd_id: str | None
    uptime_ms: int
    motivo_seguro: str | None = None


@dataclass
class V1Echo:
    """Mensagem que o próprio backend publicou (comando, config, status): registrada, não interpretada."""
    kind: str
    device: str | None


@dataclass
class V1Error:
    reason: str
    details: dict = field(default_factory=dict)


def _int(v: Any, lo: int | None = None, hi: int | None = None) -> bool:
    if isinstance(v, bool) or not isinstance(v, int):
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def split_topic(topic: str) -> tuple[str, str | None, str] | None:
    """luzambiente/v1/<role>/<device>/<kind>  ou  luzambiente/v1/backend/status."""
    parts = topic.split("/")
    if len(parts) < 4 or "/".join(parts[:2]) != PREFIX:
        return None
    if parts[2] == "backend" and len(parts) == 4:
        return "backend", "backend", parts[3]
    if len(parts) != 5 or parts[2] not in ("sensor", "atuador"):
        return None
    return parts[2], parts[3], parts[4]


def origin(topic: str) -> str:
    st = split_topic(topic)
    if not st:
        return "desconhecida"
    role, _, kind = st
    if kind in ("comando", "config") or role == "backend":
        return "backend"
    return role


def parse(topic: str, data: Any) -> Any:
    st = split_topic(topic)
    if not st:
        return V1Error("topico_desconhecido", {"topico": topic})
    role, device, kind = st
    if device != "backend" and not DEVICE_RE.match(device or ""):
        return V1Error("device_id_invalido", {"device": device})
    if kind in ("comando", "config") or role == "backend":
        return V1Echo(kind=kind, device=device)
    if not isinstance(data, dict):
        return V1Error("json_nao_objeto")
    if data.get("v") != 1:
        return V1Error("versao_invalida", {"v": data.get("v")})
    if data.get("device") != device:
        return V1Error("device_diferente_do_topico", {"device": data.get("device"), "topico": device})

    if kind == "status":
        if not isinstance(data.get("online"), bool):
            return V1Error("campo_online_invalido", {"online": data.get("online")})
        rssi = data.get("rssi") if _int(data.get("rssi"), -120, 0) else None
        return V1Status(role=role, device=device, online=data["online"], fw=data.get("fw"), ip=data.get("ip"),
                        rssi=rssi)

    if role == "sensor" and kind == "telemetria":
        for f in ("seq", "uptime_ms"):
            if not _int(data.get(f), 0):
                return V1Error(f"campo_{f}_invalido", {f: data.get(f)})
        if not _int(data.get("ldr_raw"), 0, 4095):
            return V1Error("ldr_raw_fora_da_faixa_adc", {"ldr_raw": data.get("ldr_raw")})
        am = data.get("amostras")
        if am is not None and not _int(am, 1, 64):
            return V1Error("campo_amostras_invalido", {"amostras": am})
        ok = data.get("sensor_ok", True)
        if not isinstance(ok, bool):
            return V1Error("campo_sensor_ok_invalido", {"sensor_ok": ok})
        hs = data.get("hora_sync")
        return V1Telemetry(device=device, seq=data["seq"], uptime_ms=data["uptime_ms"], raw=data["ldr_raw"],
                           amostras=am, rssi=data.get("rssi") if _int(data.get("rssi"), -120, 0) else None,
                           sensor_ok=ok, falha=data.get("falha") if isinstance(data.get("falha"), str) else None,
                           hora_sync=hs if isinstance(hs, bool) else None)

    if role == "atuador" and kind == "ack":
        cmd_id = data.get("cmd_id")
        if not isinstance(cmd_id, str) or not CMD_ID_RE.match(cmd_id):
            return V1Error("cmd_id_invalido", {"cmd_id": cmd_id})
        res = data.get("resultado")
        if res not in ACK_RESULTS:
            return V1Error("resultado_invalido", {"resultado": res})
        motivo = data.get("motivo")
        if res == "rejeitado" and motivo not in REJECT_REASONS:
            return V1Error("motivo_invalido", {"motivo": motivo})
        if res != "rejeitado" and motivo is not None:
            return V1Error("motivo_sem_rejeicao", {"motivo": motivo})
        up = data.get("uptime_ms")
        return V1Ack(device=device, cmd_id=cmd_id, resultado=res, motivo=motivo,
                     uptime_ms=up if _int(up, 0) else None)

    if role == "atuador" and kind == "estado":
        modo = data.get("modo")
        if modo not in MODES:
            return V1Error("modo_invalido", {"modo": modo})
        cena = data.get("cena")
        if cena is not None and cena not in SCENES:
            return V1Error("cena_invalida", {"cena": cena})
        leds = data.get("leds")
        if not (isinstance(leds, list) and len(leds) == 4 and all(isinstance(x, bool) for x in leds)):
            return V1Error("leds_invalidos", {"leds": leds})
        sombra = data.get("sombra")
        if sombra is not None and sombra not in SHADE:
            return V1Error("sombra_invalida", {"sombra": sombra})
        graus = data.get("servo_graus")
        if graus is not None and not _int(graus, 0, 90):
            return V1Error("servo_graus_fora_da_faixa", {"servo_graus": graus})
        rest = data.get("manual_restante_s")
        if rest is not None and not _int(rest, 0):
            return V1Error("manual_restante_invalido", {"manual_restante_s": rest})
        ult = data.get("ultimo_cmd_id")
        if ult is not None and (not isinstance(ult, str) or not CMD_ID_RE.match(ult)):
            return V1Error("ultimo_cmd_id_invalido", {"ultimo_cmd_id": ult})
        if not _int(data.get("uptime_ms"), 0):
            return V1Error("campo_uptime_ms_invalido")
        ms = data.get("motivo_seguro")
        return V1Estado(device=device, modo=modo, cena=cena, leds=tuple(leds), sombra=sombra, servo_graus=graus,
                        manual_restante_s=rest, ultimo_cmd_id=ult, uptime_ms=data["uptime_ms"],
                        motivo_seguro=ms if isinstance(ms, str) else None)

    return V1Error("tipo_de_mensagem_desconhecido", {"role": role, "kind": kind})


# ---------------------------------------------------------------- comandos
def utc_ts(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_command(cmd_id: str, *, origem: str, acao: str, cena: str | None = None, modo: str | None = None,
                  duracao_s: int | None = None, now: datetime | None = None) -> dict:
    """Monta e valida um comando antes de publicar. Lança ValueError com o motivo."""
    if not CMD_ID_RE.match(cmd_id):
        raise ValueError("cmd_id inválido")
    if origem not in ("auto", "manual"):
        raise ValueError("origem deve ser auto ou manual")
    cmd: dict[str, Any] = {"v": 1, "cmd_id": cmd_id, "origem": origem, "acao": acao}
    if acao == "aplicar":
        if cena not in SCENES:
            raise ValueError(f"cena deve ser uma de {list(SCENES)}")
        cmd["cena"] = cena
        cmd["sombra"] = "fechada" if cena == "extrema" else "aberta"
    elif acao == "definir_modo":
        if origem != "manual":
            raise ValueError("definir_modo só existe com origem manual")
        if modo not in ("auto", "manual"):
            raise ValueError("modo deve ser auto ou manual")
        cmd["modo"] = modo
        if modo == "manual":
            d = 300 if duracao_s is None else duracao_s
            if not _int(d, 60, 1800):
                raise ValueError("duracao_s deve estar entre 60 e 1800")
            cmd["duracao_s"] = d
    else:
        raise ValueError("acao deve ser aplicar ou definir_modo")
    cmd["ts"] = utc_ts(now)
    return cmd
