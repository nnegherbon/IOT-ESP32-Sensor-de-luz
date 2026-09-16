# Contrato MQTT

O prefixo do grupo é `iot/luzambiente` (configurável em `MQTT_BASE_TOPIC`).
Telemetria, comando, estado confirmado e presença de conexão ocupam tópicos
diferentes. É isso que mantém os entes desacoplados: o sensor não sabe que
existe um LED, e o atuador não sabe que existe um LDR.

## Situação do hardware (setembro/2026)

| Sensor | Tópico | Estado |
|---|---|---|
| Luminosidade (LDR) | `sensor/luminosidade` | **ativo** — é o que dirige a decisão hoje |
| Som (microfone) | `sensor/som` | inerte — o backend recebe e mostra no dashboard, mas ignora na decisão enquanto `SOM_HABILITADO=false` |
| Presença (PIR) | `sensor/presenca` | inerte — idem, enquanto `OCUPACAO_HABILITADA=false` |

Os três tópicos continuam definidos no contrato porque o backend já sabe
escutá-los — ativar um sensor novo é só ligar a flag correspondente, sem
mudar tópico nem payload.

## Catálogo de tópicos

| Tópico | Emissor → consumidor | QoS | Retido | Payload |
|---|---|---:|---:|---|
| `iot/luzambiente/sensor/luminosidade` | sensor/simulador → backend | 0 ESP32, 1 simulador | não | JSON de telemetria de luz |
| `iot/luzambiente/sensor/som` | sensor/simulador → backend | 0 ESP32, 1 simulador | não | JSON de telemetria de som (inerte) |
| `iot/luzambiente/sensor/presenca` | sensor/simulador → backend | 0 ESP32, 1 simulador | não | JSON de movimento (inerte) |
| `iot/luzambiente/sensor/status` | sensor → observadores | LWT 1 | sim | texto `online` / `offline` |
| `iot/luzambiente/atuador/luz/comando` | backend → atuador | 1 | não | JSON de cena |
| `iot/luzambiente/atuador/status` | atuador → backend | 0 ESP32, 1 simulador | sim | JSON de estado confirmado |
| `iot/luzambiente/atuador/conexao` | atuador → observadores | LWT 1 | sim | texto `online` / `offline` |

O backend assina `iot/luzambiente/#` e processa os sete tópicos acima.

## Telemetria de luminosidade

```json
{"device": "sensor01", "value": 27.5, "unit": "%"}
```

| Campo | Tipo | Obrigatório | Regra |
|---|---|---:|---|
| `device` | string | não | padrão `sensor01` |
| `value` | número | sim | 0 a 100. **Maior valor = ambiente mais claro** |
| `unit` | string | não | `%` nesta versão |

A convenção "maior = mais claro" depende do LDR estar no lado de 3V3 do
divisor de tensão (ver [MONTAGEM.md](MONTAGEM.md)). Se o grupo montar o
divisor invertido, inverta a leitura no firmware, não a regra do backend.

## Telemetria de som (inerte)

```json
{"device": "sensor01", "value": 42.3, "unit": "%"}
```

Mesmo formato de antes. `value` não é decibel — é a amplitude pico a pico da
janela de amostragem, normalizada entre o piso de silêncio e o teto de
calibração. O backend só usa esse valor quando `SOM_HABILITADO=true`.

## Telemetria de presença (inerte)

```json
{"device": "sensor01", "movimento": true}
```

O campo é `movimento`, não `presenca`, de propósito: um PIR detecta variação
de calor em movimento, não a presença de alguém parado. O backend transforma
movimento em ocupação aplicando uma carência, mas só quando
`OCUPACAO_HABILITADA=true`.

## Comando de cena

```json
{
  "cena": "suave",
  "brilho": 30,
  "cor": {"r": 255, "g": 170, "b": 80},
  "animacao": "estatica",
  "source": "automation"
}
```

| Campo | Tipo | Regra |
|---|---|---|
| `cena` | string | `apagada` (sem ocupação), `claro` (ocupado mas já claro), `suave`/`media`/`festa` (escuro, por faixa de som) ou `manual` |
| `brilho` | inteiro | 0 a 255 |
| `cor` | objeto | `r`, `g`, `b` de 0 a 255 |
| `animacao` | string | `off`, `estatica`, `respiracao`, `pulso` |
| `source` | string | `automation` (regra) ou `dashboard` (manual) |

**O atuador de hoje (um LED comum) só usa `brilho`** — liga se `brilho > 0` e
`animacao != "off"`, ignora `cor`. O payload continua carregando cor e
animação porque é o mesmo contrato que a fita RGB vai usar quando chegar; não
muda nada no backend nem no dashboard no dia da troca de hardware.

## Estado confirmado

```json
{
  "device": "atuador01",
  "cena": "suave",
  "brilho": 30,
  "cor": {"r": 255, "g": 170, "b": 80},
  "animacao": "estatica"
}
```

Retido, para que um dashboard aberto depois receba o último estado conhecido.
O dashboard só muda a lâmpada desenhada **depois** que este status chega:
comando enviado não é prova de comando aplicado.

## Retenção, duplicidade e limitações

- Mensagem retida pode estar velha depois de uma queda. O LWT existe para isso.
- **Rode um atuador por prefixo.** ESP32 e simulador assinam o mesmo comando e
  publicam no mesmo status; juntos, o último a falar sobrescreve a visão do
  backend.
- Não há autenticação nem TLS. É laboratório em rede confiável.

## Inspeção manual

```bash
mosquitto_sub -h localhost -t 'iot/luzambiente/#' -v
```

```bash
mosquitto_pub -h localhost -q 1 \
  -t iot/luzambiente/sensor/luminosidade \
  -m '{"device":"terminal","value":15,"unit":"%"}'
```

Voltar ao [índice de montagem](MONTAGEM.md).
