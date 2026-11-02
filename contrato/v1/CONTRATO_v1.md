# Contrato MQTT v1 (congelado)

| | |
|---|---|
| Versão | **v1.0, congelada em 29/10/2026** |
| Prefixo | `luzambiente/v1/` |
| Substitui | contrato informal da N1 (`iot/luzambiente/atuador/luz/comando` e `iot/luzambiente/atuador/status`) |
| Validação | `schemas/*.schema.json` (JSON Schema 2020-12) + `python contrato/v1/validar.py` |

"Congelado" quer dizer que tópicos, campos obrigatórios, tipos e valores permitidos **não mudam** até a N3.
Campos novos e opcionais podem ser acrescentados, porque todo consumidor ignora campos desconhecidos.
Qualquer mudança incompatível (renomear, remover, mudar tipo ou semântica) cria o prefixo `luzambiente/v2/`
e mantém a v1 funcionando durante a transição.

## 1. Árvore de tópicos

```text
luzambiente/v1/
├── backend/
│   └── status                    backend → todos       retido · QoS 1 · LWT
├── sensor/{device_id}/
│   ├── status                    sensor → todos        retido · QoS 1 · LWT
│   └── telemetria                sensor → backend      QoS 0 · a cada 2 s
└── atuador/{device_id}/
    ├── status                    atuador → todos       retido · QoS 1 · LWT
    ├── comando                   backend → atuador     QoS 1
    ├── ack                       atuador → backend     QoS 1 · 1 por comando recebido
    └── estado                    atuador → backend     retido · QoS 1 · na mudança + a cada 30 s
```

- `{device_id}`: `^[a-z][a-z0-9-]{2,31}$`, igual ao campo `device` do payload e ao usuário MQTT do dispositivo.
  Nesta entrega são `sensor01` e `atuador01`. Novos pares são só novos IDs (R13), sem mudar o contrato.
- O par sensor ↔ atuador (qual sensor decide qual atuador) é uma configuração do backend e não aparece nos tópicos.

## 2. Payloads

Todos são JSON UTF-8, com no máximo 512 bytes e o campo obrigatório `"v": 1`.

### 2.1 `status` (presença / LWT)

Publicado retido logo após conectar. O mesmo tópico é registrado como *Last Will* com `online:false`,
então o broker o publica sozinho se o dispositivo cair sem se desconectar (keepalive 15 s, ou seja, ~22 s).

```json
{"v":1,"device":"sensor01","online":true,"fw":"1.0.0","ip":"192.168.0.21","rssi":-61}
```
```json
{"v":1,"device":"sensor01","online":false}
```

### 2.2 `telemetria` (sensor → backend)

```json
{"v":1,"device":"sensor01","seq":1024,"uptime_ms":2048312,"ldr_raw":812,"amostras":16,"rssi":-61}
```

| Campo | Tipo | Regra |
|---|---|---|
| `seq` | inteiro ≥ 0 | incrementa a cada envio e volta a 0 no boot; uma lacuna indica perda |
| `uptime_ms` | inteiro | `millis()` (o ESP32 não tem RTC; o backend carimba a hora de recebimento) |
| `ldr_raw` | 0–4095 | média de `amostras` leituras de `analogRead(34)`, ADC1 de 12 bits, valor bruto (não é lux) |
| `amostras` | 1–64 | padrão 16 |
| `rssi` | dBm | opcional |

O sensor **não classifica e não decide**: na v1 a classificação em cenas sai do firmware e vai para o backend (R8).

### 2.3 `comando` (backend → atuador)

Somente o backend publica neste tópico, e a ACL impede qualquer outro cliente.

```json
{"v":1,"cmd_id":"c-20261103-000123","origem":"auto","acao":"aplicar","cena":"extrema","sombra":"fechada","ts":"2026-11-03T19:42:10Z"}
```
```json
{"v":1,"cmd_id":"c-20261103-000124","origem":"manual","acao":"definir_modo","modo":"manual","duracao_s":300,"ts":"2026-11-03T19:43:00Z"}
```
```json
{"v":1,"cmd_id":"c-20261103-000126","origem":"manual","acao":"definir_modo","modo":"auto","ts":"2026-11-03T19:45:00Z"}
```

| Campo | Regra |
|---|---|
| `cmd_id` | `c-AAAAMMDD-NNNNNN`, gerado pelo backend; correlaciona comando e ack e serve de chave de idempotência |
| `origem` | `auto` = motor de decisão do backend · `manual` = operador na interface |
| `acao` | `aplicar` exige `cena` + `sombra` · `definir_modo` exige `modo` (e `duracao_s` se `manual`) e só existe com `origem:"manual"` |
| `duracao_s` | 60–1800, padrão 300; é o timeout do modo manual |
| `ts` | hora UTC do backend, apenas informativa |

### 2.4 `ack` (atuador → backend)

Todo comando recebido gera **exatamente um** ack, mesmo quando é rejeitado.

```json
{"v":1,"device":"atuador01","cmd_id":"c-20261103-000123","resultado":"executado","motivo":null,"uptime_ms":3100422}
```
```json
{"v":1,"device":"atuador01","cmd_id":"c-20261103-000127","resultado":"rejeitado","motivo":"modo_seguro","uptime_ms":3160001}
```

| `motivo` | Quando |
|---|---|
| `null` | `resultado:"executado"` |
| `payload_invalido` | JSON inválido, `v` ≠ 1 ou campo obrigatório ausente (se `cmd_id` puder ser lido) |
| `modo_seguro` | atuador em SEGURO: só aceita sair por si quando as condições normalizam |
| `modo_incompativel` | `origem:"auto"` em MANUAL, ou `origem:"manual"` + `aplicar` em AUTO |
| `intertravamento` | servo moveu há menos de 5 s |

**Idempotência:** se chegar um `cmd_id` já processado (o QoS 1 pode entregar duplicado, e o backend retransmite uma vez),
o atuador **não executa de novo** e republica o ack original.

### 2.5 `estado` (atuador → backend, retido)

```json
{"v":1,"device":"atuador01","modo":"auto","cena":"extrema","leds":[true,true,true,true],"sombra":"fechada",
 "servo_graus":90,"manual_restante_s":null,"ultimo_cmd_id":"c-20261103-000123","uptime_ms":3100480}
```

| Campo | Regra |
|---|---|
| `modo` | `auto` · `manual` · `seguro` |
| `cena` | cena aplicada, ou `null` antes do primeiro comando |
| `leds` | `[LED1 GPIO27, LED2 GPIO26, LED3 GPIO25, LED4 GPIO33]`, o que foi escrito nos pinos |
| `sombra` / `servo_graus` | `aberta`/0° ou `fechada`/90°; ambos `null` = posição desconhecida (após o boot, servo sem PWM) |
| `manual_restante_s` | segundos até o timeout do modo manual; `null` fora do manual |

Mapeamento cena → LEDs, mantido da N1: escuro → LED 2 · ambiente → LED 1 · alta → LED 3 · extrema → LEDs 1 a 4.

## 3. QoS, retenção e tempos

| Tópico | QoS | Retido | Frequência | Tempo-limite usado pelo consumidor |
|---|---|---|---|---|
| `*/status` | 1 | sim | ao conectar + LWT | — |
| `sensor/*/telemetria` | 0 | não | 2 s | backend considera o sensor parado após 10 s sem telemetria |
| `atuador/*/comando` | 1 | **não** (um comando velho nunca é reexecutado ao reconectar) | sob demanda | — |
| `atuador/*/ack` | 1 | não | 1 por comando | backend espera 3 s, retransmite 1× com o mesmo `cmd_id` e então marca *sem confirmação* |
| `atuador/*/estado` | 1 | sim | mudança + 30 s | backend considera o atuador mudo após 90 s |

Keepalive MQTT de 15 s em todos os clientes.

## 4. Perfis de acesso (ACL do broker)

| Usuário MQTT | Publica | Assina |
|---|---|---|
| `sensor01` | `luzambiente/v1/sensor/sensor01/#` | — |
| `atuador01` | `luzambiente/v1/atuador/atuador01/{status,ack,estado}` | `luzambiente/v1/atuador/atuador01/comando`, `luzambiente/v1/backend/status`, `luzambiente/v1/sensor/+/status` |
| `backend` | `luzambiente/v1/atuador/+/comando`, `luzambiente/v1/backend/status` | `luzambiente/v1/#` |

Um dispositivo só escreve no próprio ramo, e só o backend comanda. As senhas ficam fora do repositório
(`secrets.h` no firmware e `.env` no backend, ambos no `.gitignore`).

## 5. Diferenças em relação à N1

| N1 | v1 | Motivo |
|---|---|---|
| sensor classifica e publica `{"cena":…}` | sensor publica `ldr_raw`; o backend decide | decisão remota (R8), valor bruto disponível para histórico |
| sem identificação no payload do sensor | `device` no tópico e no payload | múltiplos dispositivos (R13) |
| `{"estado":"alta_executada"}` | `ack` com `cmd_id` + `estado` estruturado | casar comando ↔ confirmação (R7) |
| sem presença | `status` retido + LWT | detectar queda de dispositivo (R10) |
| sem versão | `"v":1` + prefixo `/v1/` | evolução sem quebrar |
| broker público, sem senha | usuário/senha + ACL por dispositivo | segurança (R9/R16) |
