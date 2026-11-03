"""Valida os exemplos do contrato v1 contra os JSON Schemas.

    pip install jsonschema
    python contrato/v1/validar.py

Os exemplos em exemplos/validos devem passar e os de exemplos/invalidos devem
falhar. Além do schema, confere duas regras semânticas do contrato que o JSON
Schema não expressa bem:
  - leds coerentes com a cena (mesma lógica de onMessage() da N1);
  - servo_graus coerente com sombra (aberta = 0°, fechada = 90°).
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

BASE = Path(__file__).resolve().parent
LEDS_POR_CENA = {
    "escuro": [False, True, False, False],   # LED 2 (GPIO26)
    "ambiente": [True, False, False, False],  # LED 1 (GPIO27)
    "alta": [False, False, True, False],      # LED 3 (GPIO25)
    "extrema": [True, True, True, True],      # os 4 LEDs (comportamento herdado da N1)
}
SERVO_POR_SOMBRA = {"aberta": 0, "fechada": 90}


def schemas():
    return {p.name.split(".")[0]: Draft202012Validator(json.loads(p.read_text()), format_checker=FormatChecker())
            for p in (BASE / "schemas").glob("*.schema.json")}


def erros(tipo, obj, vals):
    out = [e.message for e in vals[tipo].iter_errors(obj)]
    if tipo == "estado" and not out:
        if obj["modo"] == "seguro":
            if any(obj["leds"]):
                out.append("em modo seguro os LEDs de cena ficam apagados (LED 1 pisca, mas o estado publicado é false)")
        elif obj["cena"] is not None and obj["leds"] != LEDS_POR_CENA[obj["cena"]]:
            out.append(f"leds {obj['leds']} incoerentes com a cena {obj['cena']}")
        if (obj["sombra"] is None) != (obj["servo_graus"] is None):
            out.append("sombra e servo_graus devem ser ambos null (posição desconhecida) ou ambos definidos")
        elif obj["sombra"] is not None and obj["servo_graus"] != SERVO_POR_SOMBRA[obj["sombra"]]:
            out.append(f"servo_graus {obj['servo_graus']} incoerente com sombra {obj['sombra']}")
    return out


def main() -> int:
    vals = schemas()
    falhas = 0
    for grupo, deve_passar in (("validos", True), ("invalidos", False)):
        for arq in sorted((BASE / "exemplos" / grupo).glob("*.json")):
            tipo = arq.name.split("__")[0]
            e = erros(tipo, json.loads(arq.read_text()), vals)
            ok = (not e) == deve_passar
            falhas += not ok
            status = "OK  " if ok else "FALHA"
            detalhe = "" if deve_passar else f"  -> rejeitado: {e[0] if e else 'NÃO rejeitado'}"
            print(f"{status} {grupo:9} {arq.name}{detalhe}")
    print(f"\n{'todos os exemplos conferem com o contrato v1' if not falhas else f'{falhas} divergência(s)'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
