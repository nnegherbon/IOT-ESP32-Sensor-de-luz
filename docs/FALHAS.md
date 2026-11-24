# Cenários de falha testados (R10)

Todos executados em **24/11/2026** com o hardware real (`sensor01` e `atuador01`, firmware 3.0.x, contrato v1.1),
o broker Mosquitto e o backend rodando pelo `docker compose`. As evidências brutas (Serial dos ESP32, logs do backend
e consultas ao PostgreSQL) estão em [`docs/evidencias/`](evidencias/). Nenhum cenário exigiu reinício manual.

## 1. Queda do Wi-Fi do dispositivo

| | |
|---|---|
| **Como foi provocado** | comando `wifioff 45` no Serial do `sensor01`: o firmware desliga o Wi-Fi por 45 s (gancho de teste) |
| **Esperado** | sensor segue medindo e aplicando a regra local; o broker publica o LWT `offline`; o atuador entra em SEGURO; alerta e notificação; ao voltar, tudo se recompõe sozinho |
| **Observado** | 11:54:21 alerta "sem mensagens do sensor > 10 s" · 11:54:33 LWT `sensor offline` · 11:54:34 atuador em **SEGURO** (`sensor_offline`) · 11:54:34–35 **2 notificações no celular (ntfy)** · durante a queda o Serial mostra `Luz: 5xx ok … (sem broker: só regra local)` · 11:54:58 sensor online, atuador volta a **AUTO** e o backend envia `c-20261124-000005` (alta), **confirmado em 201 ms** |
| **Evidência** | [`r10_1_queda_wifi_sensor.txt`](evidencias/r10_1_queda_wifi_sensor.txt) |

## 2. Broker indisponível

| | |
|---|---|
| **Como foi provocado** | `docker compose stop mosquitto`, aguardar 45–50 s, `docker compose start mosquitto` (duas vezes) |
| **Esperado** | backend registra a desconexão, alerta e notifica, reconecta com backoff; dispositivos reconectam e **refazem as assinaturas**; o atuador entra em SEGURO e volta a AUTO; comando pendente é retransmitido com o mesmo `cmd_id` |
| **Observado** | 11:56:01 `broker desconectado` + **notificações** "Backend sem conexão com o broker" e "atuador offline (LWT)" · reconexão com espera 1 → 2 → 4 → 8 → 16 s · 11:57:05 conectado · Serial do atuador: `MODO SEGURO` → 15 tentativas a cada 3 s → `MQTT conectado (assinaturas refeitas)` → `condições normalizadas: modo AUTO` · o primeiro comando após a volta (`c-20261124-000006`) ficou **sem ack em 3 s, foi retransmitido** e **confirmado** (4,9 s no total) |
| **Evidência** | [`r10_2_broker_indisponivel.txt`](evidencias/r10_2_broker_indisponivel.txt), [`r2_seguro_sem_broker_serial_atuador.txt`](evidencias/r2_seguro_sem_broker_serial_atuador.txt) |

## 3. Falha de sensor

| | |
|---|---|
| **Como foi provocado** | fio do GPIO34 (nó do divisor LDR + 10 kΩ) puxado da protoboard por ~15 s e recolocado |
| **Esperado** | firmware detecta leitura implausível (`saturado` ≥ 4090 ou `instavel` com desvio > 250), publica `sensor_ok:false`; LED azul da placa pisca rápido (regra local); backend abre alerta, notifica e **não decide com dado ruim**; ao recolocar, volta sozinho |
| **Observado** | 12:05:18 `Luz: 4095 FALHA saturado` → `instavel` até 12:05:30 · alerta "Sensor sensor01 com leitura implausível (saturado, ldr_raw=4095)" aberto 12:05:18 e fechado 12:05:32 · **notificação no celular** 12:05:19 · **nenhum comando** entre 12:05:18 e 12:05:30 · após recolocar o fio, a regra voltou a comandar (`c-20261124-000010` em diante, todos confirmados) |
| **Evidência** | [`r10_3_falha_sensor_serial.txt`](evidencias/r10_3_falha_sensor_serial.txt), [`r10_3_falha_sensor_backend.txt`](evidencias/r10_3_falha_sensor_backend.txt) |

## 4. Comando inválido ou duplicado

| | |
|---|---|
| **Como foi provocado** | pela API (`/api/v1/commands`): cena inexistente; cena manual com o atuador em AUTO; reenvio do mesmo `cmd_id` (`/reenviar`); telemetria fora da faixa publicada direto no broker |
| **Esperado** | entrada inválida recusada pela API; comando proibido rejeitado pelo atuador com motivo; duplicado **não executa de novo**; mensagem inválida descartada e registrada |
| **Observado** | `{"acao":"aplicar","cena":"noite"}` → **HTTP 422** "cena deve ser uma de …" · `c-20261124-000002` (escuro, manual, atuador em AUTO) → ack `recebido` + `rejeitado` com **motivo `modo_incompativel`** · `c-20261124-000003` reenviado → o atuador respondeu o **ack original** sem executar (`duplicate_acks = 1`, estado inalterado) · telemetria `ldr_raw: 9999` → gravada como `invalido` com `ldr_raw_fora_da_faixa_adc` |
| **Evidência** | [`r10_r7_r9_comandos.txt`](evidencias/r10_r7_r9_comandos.txt) |

## Outros requisitos verificados na mesma sessão

| Requisito | Verificação | Evidência |
|---|---|---|
| R9 | comando sem login → HTTP 401 | `r10_r7_r9_comandos.txt` |
| R16 | perfil `operador` tenta comandar → HTTP 403 | `r10_r7_r9_comandos.txt` |
| R15 | notificação ntfy recebida no celular | [`r15_ntfy_celular.png`](evidencias/r15_ntfy_celular.png) |
| R17 | firmware 3.0.1 enviado pelo Wi-Fi; o sensor voltou anunciando `fw 3.0.1` | [`r17_ota_sensor.txt`](evidencias/r17_ota_sensor.txt) |

## Como repetir ao vivo na defesa

| Cenário | Ação | O que mostrar |
|---|---|---|
| Wi-Fi | Serial do sensor: `wifioff 30` | LED azul segue a luz; atuador pisca o LED 1 (SEGURO); notificação; volta sozinho |
| Broker | `docker compose stop mosquitto` → 40 s → `docker compose start mosquitto` | faixa vermelha na interface, notificação, reconexão |
| Sensor | puxar o fio do D34 | alerta "leitura implausível", LED azul piscando rápido, notificação |
| Comando | aba **Controle**: aplicar uma cena com o modo em automático; depois **Reenviar igual** | rejeitado com `modo_incompativel`; ack duplicado contado e não executado |
