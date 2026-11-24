# Luz Ambiente · plataforma (broker + backend + banco + interface)

Sobe com um único comando o **broker Mosquitto** (com senha e ACL), o **PostgreSQL**, o **backend FastAPI** (que valida,
grava, **decide e comanda**) e a **interface React** (com login). Contrato em uso: **v1.1** ([`../CONTRATOS.md`](../CONTRATOS.md)).

```
sensor01 ──telemetria──▶ Mosquitto ──▶ backend: valida → PostgreSQL → regra (cena) → comando com cmd_id ──▶ Mosquitto ──▶ atuador01
                          (senha + ACL)     ▲                                                               │
                                            └────────────── ack (recebido/executado/rejeitado) + estado ────┘
                                    backend ──REST + WebSocket──▶ interface (login, perfis) · alertas ──▶ celular (ntfy)
```

## 1. Execução (Docker Compose)

```bash
cp .env.example .env      # preencha as senhas (ver seção 3)
docker compose up -d --build
# interface: http://localhost:8081   ·   saúde da API: http://localhost:8081/api/health
```

| Serviço | Papel |
|---|---|
| `mosquitto` | broker MQTT na porta 1883 (aberta na rede para os ESP32). Sem acesso anônimo: o arquivo de senhas é gerado na subida a partir do `.env`; permissões em [`mosquitto/acl`](mosquitto/acl) |
| `db` | PostgreSQL 16, volume `pgdata` (sobrevive a reinícios) |
| `backend` | assinante MQTT, validação, regra de decisão, publicação de comandos, API REST, WebSocket, alertas, notificações |
| `frontend` | nginx servindo a interface e fazendo proxy de `/api` e `/ws` |

As migrações rodam sozinhas na subida (`backend/app/migrations/`, controladas por `schema_migrations`).
Se a interface der 502 depois de recriar o backend: `docker compose restart frontend`.

## 2. O que o backend faz

| Etapa | Onde |
|---|---|
| Valida cada mensagem do contrato v1.1 (versão, device do tópico, faixas, tamanho ≤ 512 B). Inválidas são **descartadas e gravadas** com o motivo | [`app/v1.py`](backend/app/v1.py), tabela `mqtt_messages` |
| Grava telemetria, presença (status/LWT), acks e estados | [`app/control.py`](backend/app/control.py) |
| **Regra remota:** classifica a leitura em cena com histerese e tempo de confirmação; em modo AUTO, se a cena do atuador difere, publica `aplicar` | `DecisionEngine`, tabela `decision_config` |
| **Ciclo do comando:** enviado → recebido → executado → confirmado (ou rejeitado com motivo); retransmite 1× sem ack em 3 s; `sem_confirmacao` e `falha_envio` geram alerta | tabelas `commands`, `command_acks` |
| Alertas (sol extremo, sensor com falha, placa offline, silêncio, comando falhou, modo seguro, broker caído) e **notificação externa** | [`app/alerts.py`](backend/app/alerts.py), [`app/notify.py`](backend/app/notify.py) |
| Login (token HMAC) e perfis: `admin` comanda e configura; `operador` só lê (POST/PUT/DELETE → 403) | [`app/auth.py`](backend/app/auth.py), tabela `audit_log` |

Os tópicos da N1 (`iot/luzambiente/...`) continuam assinados **só para o histórico** gravado antes da migração.

## 3. Configuração (`.env`)

| Variável | Exemplo | Descrição |
|---|---|---|
| `POSTGRES_PASSWORD` | — | senha do banco |
| `MQTT_PASS_BACKEND`, `MQTT_PASS_SENSOR01`, `MQTT_PASS_ATUADOR01` | — | senhas do broker, uma por cliente (as mesmas vão no `secrets.h` de cada firmware) |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | `backend` / = `MQTT_PASS_BACKEND` | como o backend entra no broker |
| `AUTH_USERS` | `admin:<senha>:admin,operador:<senha>:operador` | usuários da interface (R9/R16) |
| `AUTH_SECRET` | `openssl rand -hex 32` | assina os tokens; sem ele, as sessões caem a cada reinício |
| `NTFY_URL` | `https://ntfy.sh/<tópico-secreto>` | notificação no celular (app ntfy). Alternativa: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| `NOTIFY_MIN_SEVERITY` | `critico` | gravidade mínima para notificar |
| `HTTP_PORT` | `8081` | porta da interface no PC |
| `OTA_PASS` | — | senha do OTA dos firmwares (usada pelo arduino-cli) |
| `DEMO_MODE` | `false` | dados sintéticos isolados (`is_demo=true`) quando não há hardware |

O `.env` nunca vai para o Git. `/api/config` informa se há autenticação e quais canais de notificação existem, nunca senhas.

## 4. Banco de dados

| Tabela | Conteúdo |
|---|---|
| `sensor_readings` | medições: dispositivo, valor bruto do ADC (0–4095), cena calculada, horário |
| `commands` | cada comando: `cmd_id`, origem (regra ou usuário), ação, cena/modo, status do ciclo, motivo, horários de envio, recebimento, execução e confirmação, latência, retransmissões, acks duplicados |
| `command_acks` | todo ack recebido, inclusive repetidos |
| `actuator_states` | estados publicados: modo, cena, LEDs, sombra, último `cmd_id`, motivo do modo seguro |
| `decision_config` | parâmetros da regra (limites, histerese, confirmação), quem alterou e quando |
| `mqtt_messages` | toda mensagem, com `parse_status` (`ok`, `invalido`, …) e o motivo da rejeição |
| `connectivity_events` | broker conectado/desconectado, online/offline (LWT), silêncio |
| `alert_rules`, `alerts`, `notifications`, `audit_log` | regras, alertas, notificações enviadas, ações dos usuários |
| `scene_commands`, `actuator_confirmations`, `shade_events` | visão de transições, confirmações e posição da sombra usada pelos painéis (N1 e v1) |

Backup: `./scripts/backup.sh` (mantém 30) e `./scripts/restore.sh backups/luz_….dump`.

## 5. API

Todas as rotas `/api/*` exigem `Authorization: Bearer <token>` (exceto `/api/health` e `/api/auth/login`); o WebSocket
e as exportações aceitam `?token=`.

| Método | Rota | |
|---|---|---|
| POST | `/api/auth/login` | `{"username","password"}` → token e perfil |
| GET | `/api/v1/state` | decisão atual, sensores, atuadores, último comando |
| GET/POST | `/api/v1/commands` | listar / enviar (`aplicar` + `cena`, ou `definir_modo` + `modo` e `duracao_s`) — admin |
| GET | `/api/v1/commands/{cmd_id}` | comando com payload e todos os acks |
| POST | `/api/v1/commands/{cmd_id}/reenviar` | republica o mesmo `cmd_id` (teste de duplicidade) — admin |
| GET/PUT | `/api/v1/decision` | parâmetros da regra — PUT só admin |
| POST | `/api/v1/config/{sensor\|atuador}/{device}` | configuração remota persistida na NVS — admin |
| GET/POST | `/api/v1/notifications`, `/api/v1/notifications/teste` | histórico e teste de notificação |
| GET | `/api/readings`, `/api/readings/series`, `/api/stats`, `/api/analytics/scenes`, `/api/events`, `/api/messages`, `/api/alerts`, `/api/audit` | histórico e painel analítico (`from`, `to`, `limit`, `offset`) |
| GET | `/api/export/{dataset}?format=csv\|json` | exportação (CSV para Excel pt-BR) |
| WS | `/ws?token=` | eventos ao vivo (`state`, `reading`, `v1_command`, `v1_estado`, `alert`, …) |

Documentação interativa: `http://localhost:8000/docs` quando o backend roda fora do Docker.

## 6. Testes e CI

```bash
cd backend
export TEST_DATABASE_URL=postgresql://luz:luz@localhost:5432/luz_test   # banco descartável
pip install -r requirements-dev.txt && pytest -q
```

59 testes: contrato v1.1 (payloads válidos e inválidos), regra com histerese, ciclo completo do comando, rejeição com
motivo, ack duplicado, falha de envio sem broker, falha de sensor, login e perfis, além dos testes da N1 (persistência,
alertas, exportação, WebSocket e integração MQTT real com broker local). O GitHub Actions
([`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)) roda os testes com PostgreSQL, valida o contrato e compila
a interface e os dois firmwares a cada push.

## 7. Limitações

- MQTT sem TLS (rede local); a segurança avançada (R16) é feita pelos perfis da interface e pela ACL do broker.
- Leitura em valor bruto do ADC, sem conversão para lux (o kit não tem luxímetro para calibrar).
- A posição da sombra é a comandada: o servo não informa a posição real.
- O tópico do ntfy público é protegido só pelo nome secreto.
- `scripts/simulate_devices.py` emula apenas o contrato da N1.
