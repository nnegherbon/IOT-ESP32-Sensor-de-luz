# Luz Ambiente · Dashboard de Telemetria (protótipo)

> **Protótipo adiantado** do backend, banco e interface da N3, construído sobre o **contrato da N1**
> (`iot/luzambiente/...`). Na Unidade 3 ele será migrado ao [contrato v1](../contrato/v1/CONTRATO_v1.md)
> e ganhará o envio de comandos, o motor de decisão e o login.

Plataforma de telemetria para o projeto [IOT-ESP32-Sensor-de-luz](https://github.com/nnegherbon/IOT-ESP32-Sensor-de-luz):
sobe o broker Mosquitto local, grava todo o histórico em PostgreSQL e apresenta em tempo real a leitura do LDR, a cena,
o estado comandado × confirmado do atuador, a posição da sombra, a conectividade dos módulos, estatísticas e alertas.

```
ESP32 Sensor ──MQTT──▶ Mosquitto (docker compose, porta 1883) ──MQTT──▶ ESP32 Atuador
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
| Broker | Mosquitto local (`MQTT_HOST` no `.ino` = IP do PC), porta 1883, sem usuário/senha |
| Comando (sensor → atuador) | `iot/luzambiente/atuador/luz/comando` · `{"cena":"<cena>"}` · QoS 0, **só quando a cena muda** |
| Confirmação (atuador) | `iot/luzambiente/atuador/status` · `{"device":"atuador01","estado":"<cena>_executada"}` · **retida** |
| Telemetria (sensor) | `iot/luzambiente/sensor/telemetria` · `{"device","leitura","cena","uptime_ms"}` a cada 2 s |
| Presença (LWT, retida) | `iot/luzambiente/sensor/conexao` e `iot/luzambiente/atuador/conexao` · `{"device","status":"online\|offline"}` |
| Sombra (atuador, retida) | `iot/luzambiente/atuador/sombra` · `{"device":"atuador01","estado":"aberta\|fechada","graus":N}` |
| Client IDs | `SensorNode01` e `atuador01` |
| Leitura | `analogRead(34)` — ADC 12 bits, 0–4095, sem calibração para lux |
| Cenas | `escuro` < 150 · `ambiente` 150–399 · `alta` 400–999 · `extrema` ≥ 1000 |
| LEDs | escuro → LED 1 (GPIO27) · ambiente → LED 2 (GPIO26) · alta → LED 3 (GPIO25) · **extrema → os 4 LEDs** |
| Servo (GPIO18) | aberta 15° · fechada 120° · fecha **só na extrema** · PWM desligado após mover (não segura posição) |

Tudo isso está centralizado em `backend/app/firmware.py`.

**Consequências diretas (não contornadas com dados inventados):**

- A **cena** só é publicada na mudança; a leitura bruta vai a cada 2 s. Silêncio de comandos não implica desconexão:
  a presença vem do LWT.
- Os payloads não têm horário: o timestamp é o do recebimento no backend.
- O estado dos LEDs é **derivado** da cena confirmada pela lógica de `onMessage()`, não lido dos pinos.
- A posição da sombra é a **comandada**: o servo não tem sensor de posição.

### `firmware-patch/` (histórico)

Primeira versão aditiva da telemetria e da presença sobre o firmware da N1. Esse conteúdo já foi incorporado aos
firmwares em uso, em [`../firmware/n1/`](../firmware/n1/); use aqueles.

## 2. Execução rápida (Docker Compose)

```bash
cp .env.example .env          # defina ao menos POSTGRES_PASSWORD
docker compose up -d --build
# painel:  http://localhost:8080
# API:     http://localhost:8080/api/health
```

Serviços: `mosquitto` (broker MQTT, porta 1883 aberta na rede para os ESP32), `db` (PostgreSQL 16, volume `pgdata`), `backend` (assinante MQTT + API + WebSocket), `frontend` (nginx servindo o SPA
e fazendo proxy de `/api` e `/ws`). As migrações rodam automaticamente na subida do backend.

### Modo demonstração

Se o broker ou os dispositivos não estiverem acessíveis, defina `DEMO_MODE=true` no `.env`. Um gerador local produz mensagens
**no formato exato do firmware** (incluindo a telemetria e falhas ocasionais de confirmação) pelo mesmo pipeline de ingestão.
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
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | broker do compose; fora do Docker, `localhost` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` / `MQTT_TLS` | vazio / vazio / `false` | para um broker com autenticação (ex.: porta 8883 + TLS) |
| `HTTP_PORT` | `8080` | porta do painel no PC |
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
| `sensor_readings` | leituras brutas do LDR (telemetria a cada 2 s) |
| `connectivity_events` | conexão/desconexão do broker, presença (LWT), falhas de confirmação, silêncio |
| `alert_rules` / `alerts` | regras configuráveis e histórico de alertas (um aberto por regra) |
| `devices` | dispositivos vistos e última atividade |
| `shade_events` | posições da sombra publicadas pelo atuador (`kind='posicao'`, aberta/fechada, graus) |
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
| Leitura bruta acima / abaixo | inativa, limite **vazio** | o projeto não define |
| Sem mensagens do sensor / atuador | inativa, prazo **vazio** | silêncio pode ser normal (publicação só na mudança) |
| Atuador não confirmou | inativa, prazo **vazio** | não definido no firmware |
| Backend desconectado do broker | **ativa** | detecção direta |
| Dispositivo offline (LWT) | **ativa** | presença publicada pelos dois firmwares |

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
| GET | `/api/export/{dataset}?format=csv\|json` | `readings`, `commands`, `confirmations`, `connectivity`, `messages`, `alerts`, `events` (streaming). CSV para Excel pt-BR: `;`, BOM UTF-8, horários de Brasília. JSON: um registro por linha, horários ISO 8601 em UTC |
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

- O Mosquitto local não tem usuário nem senha e escuta na rede (porta 1883): qualquer dispositivo da mesma rede pode
  publicar nesses tópicos. Mensagens fora do formato são registradas como inválidas; mensagens bem formadas de
  terceiros não são distinguíveis dos dispositivos. Para produção, use usuário/senha e TLS (já suportado por variáveis
  de ambiente).
- Os ESP32 usam o IP fixo do PC: se ele mudar (DHCP), as placas param de conectar até o firmware ser regravado.
- As credenciais de Wi-Fi ficam só na cópia local dos `.ino`; no repositório, são placeholders.
- A API não tem autenticação; exponha-a apenas em rede confiável ou atrás de um proxy autenticado.
- Durações de cena assumem que a cena vigente vale até a próxima transição; os períodos com o sensor desligado aparecem
  pela presença (LWT).
- Os dados só são coletados enquanto o PC, o Docker e as duas placas estão ligados.

## 11. Servomotor (sombra)

O atuador publica a posição em `iot/luzambiente/atuador/sombra` (retida) ao conectar e após cada movimento. O backend
grava em `shade_events`, mantém a última posição no estado ao vivo, e a aba **Sistema** mostra a configuração do servo
(GPIO, ângulos, regra de fechamento, alimentação) e a última posição recebida. O SG90 original queimou; até o servo
novo (MG90S) ser instalado, a posição continua sendo publicada, mas fisicamente nada se move.
