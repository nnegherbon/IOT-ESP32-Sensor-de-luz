# Luz Ambiente · Dashboard de Telemetria (protótipo)

> **Protótipo adiantado** do backend, banco e interface da N3, construído sobre o **contrato da N1**
> (`iot/luzambiente/...`). Na Unidade 3 ele será migrado ao [contrato v1](../contrato/v1/CONTRATO_v1.md)
> e ganhará o envio de comandos, o motor de decisão e o login (ver `docs/CP12_PROJETO_v1.0.md`, seção 3).

Plataforma de telemetria para o projeto [IOT-ESP32-Sensor-de-luz](https://github.com/nnegherbon/IOT-ESP32-Sensor-de-luz):
assina o HiveMQ, grava todo o histórico em PostgreSQL e apresenta em tempo real a cena de luminosidade,
o estado comandado × confirmado do atuador, a conectividade dos módulos, estatísticas e alertas.

```
ESP32 Sensor ──MQTT──▶ HiveMQ ──MQTT──▶ ESP32 Atuador
                          │
                          ▼  (assinatura somente leitura: iot/luzambiente/#)
                 Backend FastAPI ──▶ PostgreSQL
                    │  REST + WebSocket
                    ▼
                 Frontend React/TS (nginx)
```

## 1. O que foi extraído do firmware

| Item | Valor real no código |
|---|---|
| Broker | `broker.hivemq.com:1883`, sem usuário/senha |
| Comando (sensor → atuador) | `iot/luzambiente/atuador/luz/comando` · `{"cena":"<cena>"}` · QoS 0, **só quando a cena muda** |
| Confirmação (atuador) | `iot/luzambiente/atuador/status` · `{"device":"atuador01","estado":"<cena>_executada"}` · **retida** |
| Client IDs | `SensorNode01` e `atuador01` |
| Leitura | `analogRead(34)` — ADC 12 bits, 0–4095, sem calibração para lux |
| Cenas | `escuro` < 150 · `ambiente` 150–399 · `alta` 400–999 · `extrema` ≥ 1000 |
| LEDs | escuro → LED 2 (GPIO26) · ambiente → LED 1 (GPIO27) · alta → LED 3 (GPIO25) · **extrema → os 4 LEDs** |

Tudo isso está centralizado em `backend/app/firmware.py`.

**Consequências diretas (não contornadas com dados inventados):**

- O firmware **não publica o valor do LDR** (só o imprime na Serial). Sem alterar o firmware, o painel mostra cena, transições,
  comando × confirmação e latência, mas leitura bruta, mín/máx/média e alertas por limite ficam como "não disponível".
- O sensor só publica na mudança de cena, então silêncio não implica desconexão; e nenhum ESP32 publica presença (LWT).
- Os payloads não têm horário: o timestamp é o do recebimento no backend.
- O estado dos LEDs é **derivado** da cena confirmada pela lógica de `onMessage()`, não lido dos pinos.

### Patch opcional e aditivo (`firmware-patch/`)

Justificativa técnica: sem ele a leitura do LDR não sai do ESP32. Os patches **não alteram** tópicos, payloads, limites,
client IDs nem a lógica existente — apenas acrescentam (marcado com `// [+]` no código):

| Arquivo | Acrescenta |
|---|---|
| `Sensor_de_luz_telemetria.ino` | `iot/luzambiente/sensor/telemetria` → `{"device","leitura","cena","uptime_ms"}` a cada 2 s; LWT/presença em `iot/luzambiente/sensor/conexao` |
| `Atuador_LED_presenca.ino` | LWT/presença em `iot/luzambiente/atuador/conexao` |

O backend já escuta esses tópicos; assim que forem publicados, gráficos e alertas correspondentes passam a funcionar sem nenhuma mudança no painel.

## 2. Execução rápida (Docker Compose)

```bash
cp .env.example .env          # defina ao menos POSTGRES_PASSWORD
docker compose up -d --build
# painel:  http://localhost:8080
# API:     http://localhost:8080/api/health
```

Serviços: `db` (PostgreSQL 16, volume `pgdata`), `backend` (assinante MQTT + API + WebSocket), `frontend` (nginx servindo o SPA
e fazendo proxy de `/api` e `/ws`). As migrações rodam automaticamente na subida do backend.

### Modo demonstração

Se o broker ou os dispositivos não estiverem acessíveis, defina `DEMO_MODE=true` no `.env`. Um gerador local produz mensagens
**no formato exato do firmware** (incluindo a telemetria do patch e falhas ocasionais de confirmação) pelo mesmo pipeline de ingestão.
O painel exibe uma faixa "Dados sintéticos", o backend não se conecta ao broker, e os registros ficam com `is_demo=true` —
nunca se misturam com os reais. Volte para `DEMO_MODE=false` para a integração real.

## 3. Execução em desenvolvimento (sem Docker)

```bash
# Banco
createuser -P luz && createdb -O luz luz

# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://luz:SENHA@localhost:5432/luz
uvicorn app.main:app --reload --port 8000        # docs em http://localhost:8000/docs

# Frontend
cd ../frontend
npm install
npm run dev                                       # http://localhost:5173 (proxy para :8000)
```

### Bancada sem hardware

`scripts/simulate_devices.py` emula **os dois ESP32** (mesmos tópicos, payloads e client IDs) contra um broker local
(ex.: `docker run -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf`). Ele se recusa a rodar contra o
broker público para não interferir nos dispositivos reais.

```bash
MQTT_HOST=localhost uvicorn app.main:app --port 8000
python scripts/simulate_devices.py --host localhost --telemetria --perder 0.05
```

## 4. Configuração (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `MQTT_HOST` / `MQTT_PORT` | `broker.hivemq.com` / `1883` | mesmos do firmware |
| `MQTT_USERNAME` / `MQTT_PASSWORD` / `MQTT_TLS` | vazio / vazio / `false` | para um cluster HiveMQ Cloud privado (porta 8883 + TLS) |
| `MQTT_SUBSCRIBE` | `iot/luzambiente/#` | tópicos desconhecidos sob a base são guardados como `nao_tratado` |
| `MQTT_CLIENT_ID_PREFIX` | `luz-dashboard` | sempre recebe sufixo aleatório para não derrubar `SensorNode01`/`atuador01` |
| `DEMO_MODE` | `false` | dados sintéticos isolados |
| `CORS_ORIGINS` | localhost | só necessário fora do nginx |

Credenciais ficam apenas no backend (`.env`, fora do git). O frontend fala só com o backend; `/api/config` informa se há
autenticação, nunca usuário ou senha. O backend é **somente leitura** no MQTT: não publica em nenhum tópico.

## 5. Banco de dados

Esquema em `backend/app/migrations/001_init.sql` (aplicado automaticamente, controlado por `schema_migrations`).

| Tabela | Conteúdo |
|---|---|
| `mqtt_messages` | toda mensagem recebida: tópico, payload, QoS, retida, status (`ok`, `invalido`, `nao_tratado`, `erro_processamento`), motivo do erro |
| `scene_commands` | transições de cena do sensor, cena anterior, status (`aguardando`, `confirmado`, `sem_confirmacao`, `substituido`), latência |
| `actuator_confirmations` | confirmações do atuador, LEDs derivados, correspondência com o comando, flag de mensagem retida |
| `sensor_readings` | leituras brutas do LDR (somente com o patch) |
| `connectivity_events` | conexão/desconexão do broker, presença (LWT), falhas de confirmação, silêncio |
| `alert_rules` / `alerts` | regras configuráveis e histórico de alertas (um aberto por regra) |
| `devices` | dispositivos vistos e última atividade |
| `shade_events` | **reservada** para o servomotor (não implementado no firmware; nada a preenche) |
| `v_events` (view) | linha do tempo unificada |

Todas as tabelas têm `is_demo`, chaves estrangeiras para a mensagem de origem e índices por `(is_demo, tempo)`.
O estado ao vivo é reconstruído do banco na inicialização, então reinícios não perdem nada.

**Backup e restauração** (com Docker Compose):

```bash
./scripts/backup.sh                     # backups/luz_AAAAMMDD_HHMMSS.dump (mantém 30; KEEP=n para mudar)
./scripts/restore.sh backups/luz_….dump # substitui os dados (pede confirmação)
```

Fora do Docker: `pg_dump -Fc -d luz > luz.dump` e `pg_restore --clean -d luz luz.dump`. Para agendar, use cron no host
(ex.: `0 3 * * * /caminho/scripts/backup.sh`).

## 6. Como o comando × confirmação é tratado

1. Comando recebido → `scene_commands.status = aguardando`.
2. Confirmação **não retida** com a mesma cena (considerando o truncamento de 15 caracteres do atuador) dentro de 5 min →
   `confirmado`, com latência; comandos anteriores ainda pendentes viram `substituido`.
3. Se a regra "Atuador não confirmou o comando" estiver ativa com um prazo, comandos vencidos viram `sem_confirmacao`,
   geram evento de falha e alerta. Uma confirmação tardia ainda casa e encerra o alerta.
4. Mensagem **retida** entregue na (re)assinatura é gravada como `retido_inicial`: indica o último estado do atuador,
   mas com horário real desconhecido, e não confirma nenhum comando.

## 7. Alertas

Regras padrão (editáveis na aba **Alertas**):

| Regra | Padrão | Observação |
|---|---|---|
| Cena `extrema` | **ativa** | categoria definida pelo próprio firmware |
| Cena `escuro` | inativa | idem |
| Leitura bruta acima / abaixo | inativa, limite **vazio** | o projeto não define; exige o patch de telemetria |
| Sem mensagens do sensor / atuador | inativa, prazo **vazio** | silêncio pode ser normal (publicação só na mudança) |
| Atuador não confirmou | inativa, prazo **vazio** | não definido no firmware |
| Backend desconectado do broker | **ativa** | detecção direta |
| Dispositivo offline (LWT) | **ativa** | só dispara com o patch de presença |

Regras com limite vazio não podem ser ativadas (a API responde 422). A aba também mostra o histórico de alertas e os
**períodos de exposição intensa** (trechos contínuos em `alta`/`extrema`).

## 8. API

| Método | Rota | |
|---|---|---|
| GET | `/api/health`, `/api/config`, `/api/state` | saúde, contrato do firmware, estado ao vivo |
| GET | `/api/readings`, `/api/commands`, `/api/confirmations`, `/api/connectivity`, `/api/messages`, `/api/events`, `/api/alerts` | `from`, `to` (ISO 8601), `limit`, `offset` + filtros |
| GET | `/api/readings/series` | agregação mín/média/máx por intervalo (`bucket` automático) |
| GET | `/api/stats` | mín, máx, média, quantidade, taxa de confirmação, latência |
| GET | `/api/analytics/scenes` | intervalos, distribuição por tempo e períodos intensos |
| GET/POST/PUT/DELETE | `/api/alert-rules[/{id}]` | regras |
| POST | `/api/alerts/{id}/ack` | reconhecer alerta |
| GET | `/api/export/{dataset}?format=csv\|json` | `readings`, `commands`, `confirmations`, `connectivity`, `messages`, `alerts`, `events` (streaming) |
| WS | `/ws` | eventos `state`, `command`, `confirmation`, `reading`, `connectivity`, `alert`, `message_invalid` |

Período padrão: últimas 24 h.

## 9. Testes

```bash
cd backend
export TEST_DATABASE_URL=postgresql://luz:SENHA@localhost:5432/luz_test   # banco descartável: o schema é recriado
pytest -q
```

44 testes cobrem: classificação e mapeamento de LEDs idênticos ao firmware; validação de payloads válidos e inválidos;
persistência e casamento comando × confirmação; mensagens retidas; comandos substituídos; reconstrução do estado após
reinício; alertas (cena, limite, prazo de confirmação, broker); isolamento do modo demonstração; consultas por período,
paginação, estatísticas e análise de cenas; exportação CSV/JSON; WebSocket; e **integração MQTT real** com um broker local
(amqtt), publicando os payloads do firmware com os client IDs dos dispositivos, incluindo queda do broker e reconexão automática.

## 10. Limitações e segurança

- O HiveMQ público não tem autenticação: qualquer cliente pode publicar nesses tópicos. Mensagens fora do formato são
  registradas como inválidas; mensagens bem formadas de terceiros não são distinguíveis dos dispositivos.
  Para produção, use um cluster privado com usuário/senha e TLS (já suportado por variáveis de ambiente).
- O repositório original contém credenciais de Wi-Fi no código-fonte; recomenda-se removê-las e trocar a senha.
- A API não tem autenticação; exponha-a apenas em rede confiável ou atrás de um proxy autenticado.
- Durações de cena assumem que a cena vigente vale até a próxima transição; períodos com o sensor desligado só são
  distinguíveis com o patch de presença.

## 11. Servomotor (futuro)

Nada relativo ao servo é exibido como existente. A preparação consiste em: tabela `shade_events` (comando, posição,
confirmação), assinatura de todo `iot/luzambiente/#` (mensagens futuras já ficam guardadas como `nao_tratado`) e o
interpretador em `backend/app/parsing.py`, onde basta acrescentar o tópico e o formato quando forem definidos no firmware.
