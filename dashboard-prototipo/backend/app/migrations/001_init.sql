-- Esquema inicial da telemetria do projeto IOT-ESP32-Sensor-de-luz
-- Todas as tabelas de dados possuem is_demo para isolar o modo demonstração.

CREATE TABLE devices (
    id            SMALLSERIAL PRIMARY KEY,
    role          TEXT NOT NULL CHECK (role IN ('sensor', 'atuador')),
    device_key    TEXT NOT NULL,
    description   TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (role, device_key)
);
COMMENT ON COLUMN devices.device_key IS
  'Atuador: campo "device" do payload. Sensor: client ID do firmware (SensorNode01), inferido pelo tópico porque o payload não traz identificação.';

-- Toda mensagem recebida, inclusive inválidas e tópicos ainda não tratados.
CREATE TABLE mqtt_messages (
    id            BIGSERIAL PRIMARY KEY,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    topic         TEXT NOT NULL,
    origin        TEXT NOT NULL,
    payload       TEXT,
    payload_bytes INTEGER NOT NULL,
    qos           SMALLINT,
    retained      BOOLEAN NOT NULL DEFAULT false,
    parse_status  TEXT NOT NULL CHECK (parse_status IN ('ok', 'invalido', 'nao_tratado', 'erro_processamento')),
    error_reason  TEXT,
    error_details JSONB,
    is_demo       BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX mqtt_messages_time_idx   ON mqtt_messages (is_demo, received_at DESC);
CREATE INDEX mqtt_messages_status_idx ON mqtt_messages (is_demo, parse_status, received_at DESC);
CREATE INDEX mqtt_messages_topic_idx  ON mqtt_messages (topic, received_at DESC);

-- Comandos de cena publicados pelo sensor (= transições de cena).
CREATE TABLE scene_commands (
    id              BIGSERIAL PRIMARY KEY,
    message_id      BIGINT NOT NULL REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    device_id       SMALLINT REFERENCES devices(id),
    received_at     TIMESTAMPTZ NOT NULL,
    cena            TEXT NOT NULL,
    known_scene     BOOLEAN NOT NULL,
    previous_cena   TEXT,
    status          TEXT NOT NULL DEFAULT 'aguardando'
                    CHECK (status IN ('aguardando', 'confirmado', 'sem_confirmacao', 'substituido')),
    confirmed_at    TIMESTAMPTZ,
    confirmation_id BIGINT,
    latency_ms      INTEGER,
    is_demo         BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX scene_commands_time_idx    ON scene_commands (is_demo, received_at DESC);
CREATE INDEX scene_commands_pending_idx ON scene_commands (is_demo, received_at) WHERE status = 'aguardando';

-- Confirmações publicadas pelo atuador. LEDs derivados da lógica de onMessage().
CREATE TABLE actuator_confirmations (
    id           BIGSERIAL PRIMARY KEY,
    message_id   BIGINT NOT NULL REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    device_id    SMALLINT REFERENCES devices(id),
    received_at  TIMESTAMPTZ NOT NULL,
    estado       TEXT NOT NULL,
    cena         TEXT NOT NULL,
    known_scene  BOOLEAN NOT NULL,
    retained     BOOLEAN NOT NULL,
    led1         BOOLEAN NOT NULL,
    led2         BOOLEAN NOT NULL,
    led3         BOOLEAN NOT NULL,
    led4         BOOLEAN NOT NULL,
    command_id   BIGINT REFERENCES scene_commands(id) ON DELETE SET NULL,
    match_status TEXT NOT NULL
                 CHECK (match_status IN ('confirmou_comando', 'sem_comando_correspondente', 'retido_inicial')),
    is_demo      BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX actuator_confirmations_time_idx ON actuator_confirmations (is_demo, received_at DESC);
ALTER TABLE scene_commands
    ADD CONSTRAINT scene_commands_confirmation_fk
    FOREIGN KEY (confirmation_id) REFERENCES actuator_confirmations(id) ON DELETE SET NULL;

-- Leituras brutas do LDR. Só são preenchidas se o sensor publicar no tópico
-- opcional de telemetria (patch em firmware-patch/). O firmware original não publica.
CREATE TABLE sensor_readings (
    id            BIGSERIAL PRIMARY KEY,
    message_id    BIGINT NOT NULL REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    device_id     SMALLINT REFERENCES devices(id),
    received_at   TIMESTAMPTZ NOT NULL,
    raw           SMALLINT NOT NULL CHECK (raw BETWEEN 0 AND 4095),
    cena_computed TEXT NOT NULL,
    cena_reported TEXT,
    uptime_ms     BIGINT,
    is_demo       BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX sensor_readings_time_idx ON sensor_readings (is_demo, received_at DESC);

CREATE TABLE connectivity_events (
    id          BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    component   TEXT NOT NULL CHECK (component IN ('broker', 'sensor', 'atuador', 'backend')),
    event       TEXT NOT NULL,
    detail      JSONB,
    is_demo     BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX connectivity_events_time_idx ON connectivity_events (is_demo, occurred_at DESC);

CREATE TABLE alert_rules (
    id         SERIAL PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('scene', 'raw_above', 'raw_below', 'silence',
                                             'confirmation_timeout', 'broker_disconnected', 'device_offline')),
    name       TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT false,
    severity   TEXT NOT NULL DEFAULT 'aviso' CHECK (severity IN ('info', 'aviso', 'critico')),
    params     JSONB NOT NULL DEFAULT '{}'::jsonb,
    builtin    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
    id              BIGSERIAL PRIMARY KEY,
    rule_id         INTEGER REFERENCES alert_rules(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('aberto', 'encerrado')),
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at       TIMESTAMPTZ,
    message         TEXT NOT NULL,
    context         JSONB,
    acknowledged_at TIMESTAMPTZ,
    is_demo         BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX alerts_time_idx ON alerts (is_demo, opened_at DESC);
CREATE UNIQUE INDEX alerts_one_open_per_rule ON alerts (rule_id, is_demo) WHERE status = 'aberto';

-- PREPARAÇÃO PARA O SERVOMOTOR (README: "em desenvolvimento").
-- Nenhum código preenche esta tabela hoje; ela existe para que, quando o
-- firmware definir tópico e formato, a ingestão seja só um novo parser.
CREATE TABLE shade_events (
    id           BIGSERIAL PRIMARY KEY,
    message_id   BIGINT REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    received_at  TIMESTAMPTZ NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('comando', 'posicao', 'confirmacao')),
    command      TEXT,
    position_deg NUMERIC(5, 1),
    payload      JSONB,
    is_demo      BOOLEAN NOT NULL DEFAULT false
);
COMMENT ON TABLE shade_events IS 'Reservada para o servomotor de sombreamento. Não implementado no firmware atual.';

-- Linha do tempo unificada para o histórico de eventos.
CREATE VIEW v_events AS
    SELECT received_at AS occurred_at, 'transicao_cena' AS category, id AS ref_id, is_demo,
           jsonb_build_object('cena', cena, 'anterior', previous_cena, 'conhecida', known_scene,
                              'status', status, 'latencia_ms', latency_ms) AS detail
      FROM scene_commands
    UNION ALL
    SELECT received_at, 'confirmacao', id, is_demo,
           jsonb_build_object('cena', cena, 'estado', estado, 'retida', retained, 'correspondencia', match_status,
                              'leds', jsonb_build_array(led1, led2, led3, led4))
      FROM actuator_confirmations
    UNION ALL
    SELECT occurred_at, 'conectividade', id, is_demo,
           jsonb_build_object('componente', component, 'evento', event) || COALESCE(detail, '{}'::jsonb)
      FROM connectivity_events
    UNION ALL
    SELECT opened_at, 'alerta', id, is_demo,
           jsonb_build_object('mensagem', message, 'severidade', severity, 'status', status, 'encerrado_em', closed_at)
      FROM alerts
    UNION ALL
    SELECT received_at, 'mensagem_invalida', id, is_demo,
           jsonb_build_object('topico', topic, 'motivo', error_reason, 'payload', left(payload, 200))
      FROM mqtt_messages WHERE parse_status IN ('invalido', 'erro_processamento');

-- Regras padrão. Limites numéricos ficam NULOS: o projeto não os define.
-- A regra de cena extrema usa a categoria definida no próprio firmware.
INSERT INTO alert_rules (kind, name, enabled, severity, params, builtin) VALUES
  ('scene', 'Luminosidade extrema (cena "extrema" do firmware)', true, 'critico', '{"scenes": ["extrema"]}', true),
  ('scene', 'Luminosidade insuficiente (cena "escuro" do firmware)', false, 'aviso', '{"scenes": ["escuro"]}', true),
  ('raw_above', 'Leitura bruta acima do limite', false, 'aviso', '{"threshold": null}', true),
  ('raw_below', 'Leitura bruta abaixo do limite', false, 'aviso', '{"threshold": null}', true),
  ('silence', 'Sem mensagens do sensor', false, 'aviso', '{"component": "sensor", "seconds": null}', true),
  ('silence', 'Sem mensagens do atuador', false, 'aviso', '{"component": "atuador", "seconds": null}', true),
  ('confirmation_timeout', 'Atuador não confirmou o comando', false, 'critico', '{"ms": null}', true),
  ('broker_disconnected', 'Backend desconectado do broker MQTT', true, 'critico', '{}', true),
  ('device_offline', 'Dispositivo anunciou offline (LWT, requer patch)', true, 'critico', '{}', true);
