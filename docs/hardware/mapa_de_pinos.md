# Mapa de pinos (alvo N3)

Placas: 2× ESP32 DevKit V1 (ESP32-WROOM-32, 30 pinos). Esquemas em `esquema_eletrico/`.

## Nó sensor: `sensor01`

| Pino | Função | Direção | Ligação | Observação |
|---|---|---|---|---|
| 3V3 | alimentação do divisor | saída de tensão | LDR (lado alto) | o divisor fica limitado a 3,3 V |
| GPIO34 | leitura do LDR | entrada analógica | nó Va (entre o LDR e R1 10 kΩ) | ADC1_CH6, só entrada; o ADC1 funciona com Wi-Fi |
| GND | referência | — | R1 | — |
| USB | alimentação 5 V | — | carregador/PC | ~80 mA médios, picos de ~240 mA no Wi-Fi |

## Nó atuador: `atuador01`

| Pino | Função | Direção | Ligação | Mantido da N1? |
|---|---|---|---|---|
| GPIO27 | LED 1 (ambiente) | saída digital | R2 220 Ω → LED → GND | sim |
| GPIO26 | LED 2 (escuro) | saída digital | R3 220 Ω → LED → GND | sim |
| GPIO25 | LED 3 (alta) | saída digital | R4 220 Ω → LED → GND | sim |
| GPIO33 | LED 4 (extrema) | saída digital | R5 220 Ω → LED → GND | sim |
| GPIO18 | sinal do servo SG90 | saída PWM 50 Hz (LEDC) | fio laranja do servo + R6 10 kΩ pull-down → GND | **novo** |
| GND | referência comum | — | LEDs, R6, GND do servo, negativo da fonte 5 V | **GND comum novo** |
| USB | alimentação 5 V do ESP32 | — | carregador/PC | sim |
| — | alimentação do servo | — | fonte 5 V / 2 A externa (+ C2 470 µF) | **novo** |

## Pinos evitados

| Pino(s) | Motivo |
|---|---|
| GPIO 6–11 | ligados à flash SPI interna |
| GPIO 0, 2, 5, 12, 15 | strapping: o nível no boot altera o modo de inicialização |
| GPIO13 | danificado durante a prototipagem da N1 |
| ADC2 (GPIO 0, 2, 4, 12–15, 25–27) para leitura analógica | o ADC2 não lê com o Wi-Fi ativo; 25–27 são usados só como saídas digitais |
| GPIO 34–39 como saída | são somente entrada |
