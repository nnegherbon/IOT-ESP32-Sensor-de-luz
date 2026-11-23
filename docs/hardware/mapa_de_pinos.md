# Mapa de pinos

Placas: 2× ESP32 DevKit V1 (ESP32-WROOM-32, 30 pinos, conversor USB CP2102). Esquemas em `esquema_eletrico/`.
Este mapa é o da montagem atual e bate com `firmware/n1/` e com `dashboard-prototipo/backend/app/firmware.py`.

## Nó sensor: `sensor01`

| Pino | Função | Direção | Ligação | Observação |
|---|---|---|---|---|
| 3V3 | alimentação do divisor | saída de tensão | LDR (lado alto) | o divisor fica limitado a 3,3 V |
| GPIO34 (D34) | leitura do LDR | entrada analógica | nó Va (entre o LDR e R1 10 kΩ) | ADC1_CH6, só entrada; o ADC1 funciona com Wi-Fi. O VN (GPIO39) fica colado: cuidado |
| GND | referência | — | R1 | — |
| USB | alimentação 5 V | — | carregador/PC | ~80 mA médios, picos de ~240 mA no Wi-Fi |

O LDR precisa ficar **exposto à luz**. Se ele ficar dentro de uma caixa fechada, a leitura cai para a cena escuro.

## Nó atuador: `atuador01`

| Pino | Função | Direção | Ligação | Cena |
|---|---|---|---|---|
| GPIO27 (D27) | LED 1 | saída digital | R2 330 Ω → LED → GND | escuro |
| GPIO26 (D26) | LED 2 | saída digital | R3 330 Ω → LED → GND | ambiente |
| GPIO25 (D25) | LED 3 | saída digital | R4 330 Ω → LED → GND | alta |
| GPIO33 (D33) | LED 4 | saída digital | R5 330 Ω → LED → GND | extrema |
| GPIO18 (D18) | sinal do servo | saída PWM 50 Hz (LEDC) | fio de sinal do servo (amarelo/laranja) | sombra: aberta 0°, fechada 105° (só na extrema) |
| VIN | +5 V do servo | — | fio vermelho do servo (trilha +) | 5 V vindos do USB |
| GND | referência comum | — | LEDs, GND do servo (marrom) | — |
| USB | alimentação 5 V do ESP32 e do servo | — | carregador/PC | sem fonte externa |

### Servo sem fonte externa

O projeto precisa funcionar só com o USB, então o servo é alimentado pelo **VIN**. Isso exige alguns cuidados:

- **Carga leve**: braço curto (meio palito de churrasco + pedaço pequeno de papel). Nada que force o motor.
- **Nunca segurar a posição**: o firmware liga o PWM, move em passos de 2° a cada 30 ms e **desliga o PWM** no fim.
  Um SG90 queimou em 22/11/2026 por ficar ~3 min travado segurando a ponta (0°), com o braço sem parafuso.
- **Folga nas pontas**: os ângulos ficam longe dos batentes mecânicos. Se o servo zumbir sem girar, desligue.
- **Recomendados (opcionais)**: capacitor de 100 µF entre VIN e GND perto do servo e resistor de 10 kΩ de
  pull-down do D18 ao GND (mantém o sinal em nível baixo durante o boot).
- **Servo substituto**: MG90S (engrenagem metálica, mesmo tamanho e pinagem do SG90).

## Pinos evitados

| Pino(s) | Motivo |
|---|---|
| GPIO 6–11 | ligados à flash SPI interna |
| GPIO 0, 2, 5, 12, 15 | strapping: o nível no boot altera o modo de inicialização |
| ADC2 (GPIO 0, 2, 4, 12–15, 25–27) para leitura analógica | o ADC2 não lê com o Wi-Fi ativo; 25–27 são usados só como saídas digitais |
| GPIO 34–39 como saída | são somente entrada |
