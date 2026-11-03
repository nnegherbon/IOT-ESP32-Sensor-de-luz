"""Esquema elétrico do projeto (alvo da N3, desenhado para a N2, sem bancada).

Gera esquema_sensor.{svg,png} e esquema_atuador.{svg,png}:
    pip install schemdraw matplotlib
    python docs/esquema_eletrico/esquema.py

Todos os símbolos de terra (⏚) de um mesmo nó são o MESMO ponto elétrico.
No nó atuador, o GND do ESP32 e o negativo da fonte de 5 V do servo são interligados (GND comum).
"""
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

OUT = Path(__file__).resolve().parent
schemdraw.config(fontsize=12, lw=1.4)


def ic(pins_right, label, spacing, pins_left=()):
    """ESP32 como bloco; pinos listados de cima para baixo."""
    n = max(len(pins_right), len(pins_left))
    pins = [elm.IcPin(name=p, side="right", slot=f"{n - i}/{n}") for i, p in enumerate(pins_right)]
    pins += [elm.IcPin(name=p, side="left", slot=f"{n - i}/{n}") for i, p in enumerate(pins_left)]
    return elm.Ic(pins=pins, size=(3.6, n * spacing), pinspacing=spacing, edgepadW=0.6)


def notas(d, xy, texto):
    d += elm.Label().at(xy).label(texto, fontsize=10.5, halign="left", valign="top")


# ------------------------------------------------------------------ sensor
with schemdraw.Drawing(show=False) as d:
    d.config(unit=2.5)
    E = d.add(ic(["3V3", "GPIO34", "GND"], "", 2.0))
    d += elm.Label().at((E.center[0], E["3V3"][1] + 1.4)).label("ESP32 DevKit V1 #1 · sensor01 · USB 5 V", fontsize=12)
    d += elm.Line().at(E["3V3"]).right(1.6)
    d += elm.Photoresistor().down(2.0).label("LDR GL5528", loc="bottom", ofst=0.3)
    A = d.here
    d += elm.Dot().label("Va", loc="left", ofst=(0.0, 0.25))
    d += elm.Line().at(E["GPIO34"]).to(A)
    d += elm.Resistor().at(A).down(3.0).label("R1\n10 kΩ", loc="bottom", ofst=0.3)
    B = d.here
    d += elm.Ground().at(B)
    d += elm.Line().at(E["GND"]).right(0.6)
    d += elm.Ground()
    notas(d, (8.4, 3.2),
          "Divisor de tensão no ADC1:\n"
          "Va = 3,3 V × R1 / (R1 + R_LDR)\n"
          "• mais luz → R_LDR menor → Va maior\n"
          "  (coerente com a N1: leitura alta = luz forte)\n"
          "• alimentado pelo 3V3 → Va ≤ 3,3 V:\n"
          "  nenhum sinal de 5 V chega ao GPIO\n"
          "• I máx ≈ 3,3 V / 10 kΩ = 0,33 mA\n"
          "• GPIO34 = ADC1_CH6, só entrada:\n"
          "  o ADC1 lê com o Wi-Fi ativo (o ADC2 não)\n"
          "• atenuação 11 dB (padrão do analogRead):\n"
          "  linear até ~2,45 V; satura em 4095 perto de 3,1 V")
    d.save(str(OUT / "esquema_sensor.svg"))
    d.save(str(OUT / "esquema_sensor.png"), dpi=150)

# ---------------------------------------------------------------- atuador
with schemdraw.Drawing(show=False) as d:
    d.config(unit=2.5)
    E = d.add(ic(["GPIO27", "GPIO26", "GPIO25", "GPIO33", "GPIO18", "GND"], "", 1.8))
    d += elm.Label().at((E.center[0], E["GPIO27"][1] + 1.9)).label("ESP32 DevKit V1 #2 · atuador01 · USB 5 V", fontsize=12)
    for pin, r, led in (("GPIO27", "R2 220 Ω", "LED1 (ambiente)"), ("GPIO26", "R3 220 Ω", "LED2 (escuro)"),
                        ("GPIO25", "R4 220 Ω", "LED3 (alta)"), ("GPIO33", "R5 220 Ω", "LED4 (extrema)")):
        d += elm.Line().at(E[pin]).right(0.5)
        d += elm.Resistor().right(2.4).label(r, loc="top", ofst=0.05)
        d += elm.LED().right(2.4).label(led, loc="top", ofst=0.05)
        d += elm.Line().right(0.4)
        d += elm.Ground(lead=False).right()
    # GPIO18 -> servo
    d += elm.Line().at(E["GPIO18"]).right(1.4)
    S = d.here
    d += elm.Dot()
    d += elm.Resistor().down(2.4).label("R6 10 kΩ\npull-down", loc="bottom", ofst=0.3)
    d += elm.Ground()
    sv = elm.Ic(pins=[elm.IcPin(name="SIG", side="left", slot="2/2"),
                      elm.IcPin(name="V+", side="right", slot="2/2"),
                      elm.IcPin(name="GND", side="right", slot="1/2")],
                size=(3.0, 2.4), pinspacing=1.2)
    d += elm.Line().at(S).right(6.4).label("PWM 50 Hz, 3,3 V", loc="top", fontsize=10)
    SV = d.add(sv.anchor("SIG"))
    d += elm.Label().at((SV.center[0], SV["SIG"][1] + 1.0)).label("Servo SG90 (ponte H interna)", fontsize=11)
    d += elm.Line().at(SV["GND"]).right(0.6)
    d += elm.Ground()
    d += elm.Line().at(SV["V+"]).right(1.6)
    V = d.here
    d += elm.Dot().label("+5 V servo", loc="top", ofst=0.15)
    d += elm.Capacitor(polar=True).down(2.6).label("C2\n470 µF / 16 V", loc="bottom", ofst=0.3)
    d += elm.Ground()
    d += elm.Line().at(V).right(4.2)
    d += elm.SourceV().down(2.6).reverse().label("Fonte\n5 V / 2 A", loc="bottom", ofst=0.4)
    d += elm.Ground()
    d += elm.Line().at(E["GND"]).right(0.6)
    d += elm.Ground()
    d += elm.Label().at((SV.center[0] + 1.5, E["GND"][1] - 2.0)).label(
        "Todo símbolo de terra = GND COMUM (ESP32 #2 + fonte 5 V + servo)", fontsize=11)
    d.save(str(OUT / "esquema_atuador.svg"))
    d.save(str(OUT / "esquema_atuador.png"), dpi=150)
print("ok")
