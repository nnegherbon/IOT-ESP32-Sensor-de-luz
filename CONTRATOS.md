# Contrato MQTT · Luz Ambiente

| | |
|---|---|
| Versão em uso | **v1.1** (24/11/2026), compatível com a v1.0 congelada no CP13 |
| Prefixo | `luzambiente/v1/` |
| Schemas | [`contrato/v1/schemas/`](contrato/v1/schemas/) (JSON Schema 2020-12), exemplos em [`contrato/v1/exemplos/`](contrato/v1/exemplos/) |
| Validação | `python contrato/v1/validar.py` (roda no CI) · no backend: [`app/v1.py`](dashboard-prototipo/backend/app/v1.py) |
| Histórico | v1.0 detalhada em [`contrato/v1/CONTRATO_v1.md`](contrato/v1/CONTRATO_v1.md) · contrato informal da N1 em `iot/luzambiente/...` (só leitura de histórico) |

## Mudanças da v1.1 em relação à v1.0 congelada

Todas são **aditivas**: um consumidor da v1.0 continua funcionando, por isso o prefixo segue `v1`.

| Mudança | Motivo |
|---|---|
| `ack.resultado` ganhou `"recebido"` (antes só `executado`/`rejeitado`) | separar *recebido* de *executado* no ciclo do comando (R7) |
| telemetria ganhou `sensor_ok`, `falha`, `hora_sync`, `ts` (opcionais) | validação da leitura e hora explícita (R2) |
| estado ganhou `angulo_real` e `motivo_seguro` (opcionais) | o servo real usa 15° para "aberta" (folga do batente); `servo_graus` segue lógico 0/90 |
| novo tópico `…/{device}/config` (retido, backend → dispositivo) | configuração remota persistente na NVS (R2) |

## 1. Árvore de tópicos

```text
luzambiente/v1/
├── backend/status                    backend → todos       retido · QoS 1 · LWT
├── sensor/{device}/
│   ├── status                        sensor → todos        retido · QoS 1 · LWT
│   ├── telemetria                    sensor → backend      QoS 0 · a cada intervalo_ms (padrão 2 s)
│   └── config                        backend → sensor      retido · QoS 1
└── atuador/{device}/
    ├── status                        atuador → todos       retido · QoS 1 · LWT
    ├── comando                       backend → atuador     QoS 1 · NÃO retido
    ├── ack                           atuador → backend     QoS 1 · recebido + executado|rejeitado
    ├── estado                        atuador → backend     retido · QoS 1 · na mudança + a cada 30 s
    └── config                        backend → atuador     retido · QoS 1
```

`{device}` segue `^[a-z][a-z0-9-]{2,31}$`, é igual ao campo `device` do payload e ao usuário MQTT do dispositivo.
Nesta entrega: `sensor01` e `atuador01` (R13). Todo payload é JSON UTF-8, até 512 bytes, com `"v": 1`.

## 2. Payloads (um exemplo por tópico)

**status** (o mesmo tópico é o *Last Will* com `online:false`; keepalive 15 s):
```json
{"v":1,"device":"sensor01","online":true,"fw":"3.0.0","ip":"192.168.68.110","rssi":-58}
```

**telemetria**:
```json
{"v":1,"device":"sensor01","seq":1024,"uptime_ms":2048312,"ldr_raw":812,"amostras":16,"rssi":-61,
 "sensor_ok":true,"hora_sync":true,"ts":"2026-11-24T14:05:10Z"}
```

| Campo | Unidade / faixa |
|---|---|
| `ldr_raw` | contagens do ADC de 12 bits, 0–4095 (média de `amostras`); **não é lux** |
| `seq` | contador desde o boot; lacuna = mensagem perdida |
| `uptime_ms` | milissegundos desde o boot (`millis()`) |
| `rssi` | dBm, −120 a 0 |
| `sensor_ok` / `falha` | `false` + `saturado` (≥ 4090: resistor solto) ou `instavel` (desvio > 250: LDR solto) |
| `hora_sync` / `ts` | NTP sincronizado e hora UTC; sem NTP, `hora_sync:false` e o backend carimba o recebimento |

**comando** (somente o backend publica; a ACL impede os demais):
```json
{"v":1,"cmd_id":"c-20261124-000012","origem":"auto","acao":"aplicar","cena":"extrema","sombra":"fechada","ts":"2026-11-24T14:05:12Z"}
{"v":1,"cmd_id":"c-20261124-000013","origem":"manual","acao":"definir_modo","modo":"manual","duracao_s":300,"ts":"2026-11-24T14:06:00Z"}
```

**ack**:
```json
{"v":1,"device":"atuador01","cmd_id":"c-20261124-000012","resultado":"recebido","motivo":null,"uptime_ms":3100100}
{"v":1,"device":"atuador01","cmd_id":"c-20261124-000012","resultado":"executado","motivo":null,"uptime_ms":3102480}
{"v":1,"device":"atuador01","cmd_id":"c-20261124-000014","resultado":"rejeitado","motivo":"modo_incompativel","uptime_ms":3160001}
```

**estado** (a confirmação final: `ultimo_cmd_id` = comando confirmado):
```json
{"v":1,"device":"atuador01","modo":"auto","cena":"extrema","leds":[true,true,true,true],"sombra":"fechada",
 "servo_graus":90,"angulo_real":90,"manual_restante_s":null,"ultimo_cmd_id":"c-20261124-000012","uptime_ms":3102500}
```

**config**:
```json
{"v":1,"intervalo_ms":2000,"limite_local":1000}
{"v":1,"seguro_apos_s":30,"sombra_fechada_graus":90}
```

## 3. Comandos aceitos e faixas

| `acao` | Campos | Faixas | Aceito quando |
|---|---|---|---|
| `aplicar` | `cena`, `sombra` | cena ∈ escuro · ambiente · alta · extrema; sombra = `fechada` só na extrema | `origem:auto` em AUTO, `origem:manual` em MANUAL |
| `definir_modo` | `modo`, `duracao_s` | modo ∈ auto · manual; `duracao_s` 60–1800 (padrão 300) | sempre com `origem:manual`, fora do SEGURO |

Configuração remota: sensor `intervalo_ms` 1000–60000 e `limite_local` 1–4095; atuador `seguro_apos_s` 10–600 e
`sombra_fechada_graus` 45–120. Valores fora da faixa são recusados pela API (422) e ignorados pelo firmware.

## 4. Confirmação (ciclo do comando, R7)

```text
backend registra e publica ──▶ enviado
atuador: ack "recebido"   ──▶ recebido
atuador: ack "executado"  ──▶ executado         (ou ack "rejeitado" + motivo ──▶ rejeitado)
atuador: estado retido com ultimo_cmd_id = cmd_id ──▶ confirmado (a interface só mostra a cena nova aqui)
sem ack em 3 s ──▶ retransmite 1× com o MESMO cmd_id ──▶ sem ack em 6 s ──▶ sem_confirmacao (+ alerta)
broker indisponível ao publicar ──▶ falha_envio (+ alerta)
```

**Idempotência:** o atuador guarda os últimos 8 `cmd_id`. Um `cmd_id` repetido (QoS 1 entregue duas vezes ou
retransmissão) **não executa de novo**: o atuador reenvia o ack original e o backend conta `duplicate_acks`.

## 5. Catálogo de códigos de erro

| Código | Onde | Significado |
|---|---|---|
| `payload_invalido` | ack | JSON inválido, `v` ≠ 1, campo obrigatório ausente ou fora da faixa |
| `modo_seguro` | ack | atuador em SEGURO (rede/backend/sensor caiu): recusa todo comando |
| `modo_incompativel` | ack | `origem:auto` em MANUAL, ou `aplicar` manual em AUTO |
| `intertravamento` | ack | o servo moveu há menos de 5 s (protege o servo); a regra tenta de novo depois |
| `saturado` · `instavel` | telemetria `falha` | leitura implausível do LDR (falha de sensor) |
| `falha_envio` · `sem_confirmacao` | backend (`commands.status`) | broker fora do ar · atuador não respondeu |
| `versao_invalida`, `device_diferente_do_topico`, `ldr_raw_fora_da_faixa_adc`, `cmd_id_invalido`, `json_invalido`, `payload_maior_que_512_bytes`, … | backend (`mqtt_messages.error_reason`) | mensagem recebida rejeitada pela validação; fica gravada como `invalido` |

## 6. QoS e retenção (justificativa)

| Tópico | QoS | Retido | Por quê |
|---|---|---|---|
| `*/status` | 1 | sim | quem conecta depois sabe na hora quem está online; o LWT publica `offline` sozinho se a placa cair |
| `telemetria` | 0 | não | chega a cada 2 s: perder uma é irrelevante e a próxima corrige; `seq` mostra a perda |
| `comando` | 1 | **não** | precisa chegar, mas um comando velho nunca pode ser reexecutado ao reconectar |
| `ack` | 1 | não | é a prova de execução; duplicatas são tratadas pelo `cmd_id` |
| `estado` | 1 | sim | o último estado real do atuador fica disponível para o backend e a interface após reinícios |
| `config` | 1 | sim | o dispositivo recebe a configuração vigente mesmo se estava desligado quando ela mudou |

## 7. Acesso ao broker (ACL)

Broker sem acesso anônimo. Usuários e permissões em [`dashboard-prototipo/mosquitto/acl`](dashboard-prototipo/mosquitto/acl);
as senhas ficam no `.env` (fora do Git) e o arquivo de senhas é gerado na subida do container.

| Usuário | Publica | Assina |
|---|---|---|
| `backend` | `luzambiente/v1/#` | `luzambiente/v1/#`, `iot/luzambiente/#` (histórico N1) |
| `sensor01` | `sensor/sensor01/{status,telemetria}` | `sensor/sensor01/config` |
| `atuador01` | `atuador/atuador01/{status,ack,estado}` | `atuador/atuador01/{comando,config}`, `backend/status`, `sensor/+/status` |
