# Montagem

Hardware disponível hoje: 2x ESP32 DevKitV1, 1x LDR, 1x LED comum, protoboards.
Microfone, PIR e fita RGB ainda não chegaram — o projeto está desenhado para
que dar esse próximo passo seja trocar hardware e ligar uma flag, não
reescrever nada (ver [ENTREGA_N1.md](ENTREGA_N1.md)).

Ordem recomendada: cada etapa é testável sozinha.

## Índice dos entes

| Ente | Onde mora | Documento |
|---|---|---|
| Sensor (LDR) | ESP32 nº 1 | este arquivo, seção 2 |
| Atuador (LED) | ESP32 nº 2 | este arquivo, seção 3 |
| Broker MQTT | Docker (`mosquitto`) | [CONTRATO_MQTT.md](CONTRATO_MQTT.md) |
| Regra + API + dashboard | Docker (`backend`) | [CONFIGURACAO.md](CONFIGURACAO.md) |
| Banco | Docker (`postgres`) | tabela `telemetry` |

## 1. Pinagem

| Componente | Ligação | Observação |
|---|---|---|
| LDR | 3V3 → LDR → **GPIO 34** → resistor ~10 kΩ → GND | é um divisor de tensão — o LDR sozinho no ADC não lê nada de útil |
| LED | **GPIO 13** → resistor 220-330 Ω → LED (+) → LED (−) → GND | LED comum, sem polaridade invertida |

> **Confirmem o resistor do divisor.** Na bancada, o valor comum é ~10 kΩ,
> mas o que importa é a ordem de grandeza da resistência do LDR no meio-termo
> de luz (normalmente na casa dos kΩ). Se a leitura ficar sempre perto de 0
> ou sempre perto de 4095, o resistor está desproporcional ao LDR — troquem
> por um mais próximo da resistência dele em luz ambiente.

> **Aviso sobre o ADC.** O ADC2 do ESP32 é compartilhado com o rádio Wi-Fi e
> devolve lixo quando o Wi-Fi está ativo — funciona no teste isolado e quebra
> no dia da integração. Use **somente** GPIO 32, 33, 34, 35, 36 ou 39 para
> qualquer sensor analógico (LDR hoje; microfone amanhã).

## 2. Teste 1 — LDR isolado

Grave um sketch que imprima `analogRead(34)` no monitor serial e cubra/exponha
o LDR com a mão. Você deve ver o número subir com luz e descer no escuro (ou o
oposto, dependendo de qual lado do divisor o LDR está — ajuste a convenção no
firmware se for o caso, mas mantenha "maior = mais claro" no valor que sai
pela rede, é o que o backend espera). Sem isso funcionando, o resto é
adivinhação.

## 3. Teste 2 — LED isolado

Pisque o LED com um `digitalWrite` simples no GPIO 13. Confirma o resistor, a
polaridade e a solda antes de qualquer coisa envolver MQTT.

## 4. Teste 3 — integração local (fallback da N1)

Grave `firmware/esp32_standalone` num único ESP32 com LDR e LED no mesmo
board. Tudo roda local, sem Wi-Fi — é o plano B caso a rede do laboratório
falhe no dia da apresentação (ver [RISCOS.md](RISCOS.md), R6). Critério de
validação: cobrir o LDR acende o LED, destampar apaga, e o comportamento se
repete sem travar.

## 5. Teste 4 — integração distribuída (o que está montado hoje)

Grave `firmware/esp32_sensor` num ESP32 (o que tem o LDR) e
`firmware/esp32_atuador` no outro (o que tem o LED), suba o Docker
(`docker compose up --build`) e abra o dashboard em <http://localhost:8000>.
Cubra o LDR: o dashboard deve mostrar "ambiente escuro" e o LED físico deve
acender junto com a cena "suave" na tela.

## Quando os componentes novos chegarem

| Componente | O que muda | Onde |
|---|---|---|
| Microfone MAX9814 | descomentar os blocos `#if 0 // SOM:` | `firmware/esp32_sensor`, `SOM_HABILITADO=true` no `.env` |
| PIR HC-SR501 | descomentar os blocos `#if 0 // PRESENCA:` | `firmware/esp32_sensor`, `OCUPACAO_HABILITADA=true` no `.env` |
| Fita/anel WS2812B | descomentar os blocos `#if 0 // RGB:`, adicionar `FastLED` de volta ao `platformio.ini` | `firmware/esp32_atuador` |

Nenhum desses três exige mudar o backend, o contrato MQTT ou o dashboard —
só o firmware e uma variável de ambiente.

Voltar ao [README](../README.md).
