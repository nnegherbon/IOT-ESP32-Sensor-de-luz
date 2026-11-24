-- N3: contrato v1.1, decisão no backend, ciclo de comando com cmd_id, notificações externas.

-- Comandos publicados pelo backend (R4, R7, R8). cmd_id = chave de idempotência e de correlação com o ack.
CREATE TABLE commands (
    cmd_id          TEXT PRIMARY KEY CHECK (cmd_id ~ '^c-[0-9]{8}-[0-9]{6}$'),
    device          TEXT NOT NULL,
    origem          TEXT NOT NULL CHECK (origem IN ('auto', 'manual')),
    acao            TEXT NOT NULL CHECK (acao IN ('aplicar', 'definir_modo')),
    cena            TEXT,
    sombra          TEXT,
    modo            TEXT,
    duracao_s       INTEGER,
    payload         JSONB NOT NULL,
    requested_by    TEXT NOT NULL,              -- usuário da interface ou 'regra:<nome>'
    reason          TEXT,                        -- por que a regra decidiu (ex.: leitura 1240 >= 1040)
    status          TEXT NOT NULL DEFAULT 'enviado'
                    CHECK (status IN ('enviado', 'recebido', 'executado', 'confirmado', 'rejeitado',
                                      'sem_confirmacao', 'falha_envio')),
    motivo          TEXT,                        -- motivo da rejeição (ack) ou da falha
    sent_at         TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ,                 -- ack "recebido"
    executed_at     TIMESTAMPTZ,                 -- ack "executado" ou "rejeitado"
    confirmed_at    TIMESTAMPTZ,                 -- estado retido com ultimo_cmd_id = cmd_id
    retries         SMALLINT NOT NULL DEFAULT 0,
    duplicate_acks  SMALLINT NOT NULL DEFAULT 0,
    latency_ms      INTEGER,                     -- sent_at -> confirmed_at
    scene_command_id BIGINT REFERENCES scene_commands(id) ON DELETE SET NULL,
    is_demo         BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX commands_time_idx ON commands (is_demo, sent_at DESC);
CREATE INDEX commands_open_idx ON commands (is_demo, sent_at) WHERE status IN ('enviado', 'recebido', 'executado');

-- Cada ack recebido (inclusive repetidos), para auditoria do ciclo.
CREATE TABLE command_acks (
    id          BIGSERIAL PRIMARY KEY,
    message_id  BIGINT REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    cmd_id      TEXT NOT NULL,
    device      TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    resultado   TEXT NOT NULL,
    motivo      TEXT,
    known       BOOLEAN NOT NULL,                -- existe em commands?
    is_demo     BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX command_acks_cmd_idx ON command_acks (cmd_id);

-- Estado publicado pelo atuador (modo, cena, LEDs, sombra).
CREATE TABLE actuator_states (
    id            BIGSERIAL PRIMARY KEY,
    message_id    BIGINT REFERENCES mqtt_messages(id) ON DELETE CASCADE,
    device        TEXT NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL,
    modo          TEXT NOT NULL,
    cena          TEXT,
    leds          BOOLEAN[] NOT NULL,
    sombra        TEXT,
    servo_graus   SMALLINT,
    manual_restante_s INTEGER,
    ultimo_cmd_id TEXT,
    motivo_seguro TEXT,
    retained      BOOLEAN NOT NULL,
    is_demo       BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX actuator_states_time_idx ON actuator_states (is_demo, received_at DESC);

-- Configuração da regra remota (R8), alterável pela interface por um administrador.
CREATE TABLE decision_config (
    id            SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled       BOOLEAN NOT NULL DEFAULT true,
    sensor        TEXT NOT NULL DEFAULT 'sensor01',
    atuador       TEXT NOT NULL DEFAULT 'atuador01',
    limite_ambiente INTEGER NOT NULL DEFAULT 150,
    limite_alta     INTEGER NOT NULL DEFAULT 400,
    limite_extrema  INTEGER NOT NULL DEFAULT 1000,
    histerese       INTEGER NOT NULL DEFAULT 40 CHECK (histerese BETWEEN 0 AND 500),
    confirmacao_s   NUMERIC(5, 1) NOT NULL DEFAULT 3 CHECK (confirmacao_s BETWEEN 0 AND 600),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by    TEXT NOT NULL DEFAULT 'padrão',
    CHECK (0 < limite_ambiente AND limite_ambiente < limite_alta AND limite_alta < limite_extrema
           AND limite_extrema < 4095)
);
INSERT INTO decision_config DEFAULT VALUES;

-- Notificações externas enviadas (R15).
CREATE TABLE notifications (
    id         BIGSERIAL PRIMARY KEY,
    sent_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel    TEXT NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    ok         BOOLEAN NOT NULL,
    error      TEXT,
    alert_id   BIGINT REFERENCES alerts(id) ON DELETE SET NULL,
    is_demo    BOOLEAN NOT NULL DEFAULT false
);

-- Ações de usuários autenticados (login, comandos, mudanças de configuração).
CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    username   TEXT NOT NULL,
    role       TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     JSONB,
    ok         BOOLEAN NOT NULL DEFAULT true
);

-- Novos tipos de alerta: falha do sensor e comando rejeitado/sem confirmação no contrato v1.
ALTER TABLE alert_rules DROP CONSTRAINT alert_rules_kind_check;
ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_kind_check CHECK (kind IN (
    'scene', 'raw_above', 'raw_below', 'silence', 'confirmation_timeout', 'broker_disconnected', 'device_offline',
    'sensor_fault', 'command_failed', 'safe_mode'));
INSERT INTO alert_rules (kind, name, enabled, severity, params, builtin) VALUES
  ('sensor_fault', 'Falha do sensor de luz (leitura implausível)', true, 'critico', '{}', true),
  ('command_failed', 'Comando rejeitado ou sem confirmação do atuador', true, 'aviso', '{}', true),
  ('safe_mode', 'Atuador entrou em modo seguro', true, 'critico', '{}', true);
UPDATE alert_rules SET name = 'Dispositivo anunciou offline (LWT)' WHERE kind = 'device_offline';
UPDATE alert_rules SET params = '{"component": "sensor", "seconds": 10}', enabled = true
 WHERE kind = 'silence' AND params->>'component' = 'sensor';
UPDATE alert_rules SET params = '{"component": "atuador", "seconds": 90}', enabled = true
 WHERE kind = 'silence' AND params->>'component' = 'atuador';

-- A tabela de sombra deixa de ser "reservada": o estado v1 também a preenche.
COMMENT ON TABLE shade_events IS 'Posição comandada da sombra (servo), da N1 (tópico sombra) e da v1 (estado).';

-- Linha do tempo: inclui os comandos v1.
CREATE OR REPLACE VIEW v_events AS
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
      FROM mqtt_messages WHERE parse_status IN ('invalido', 'erro_processamento')
    UNION ALL
    SELECT sent_at, 'comando', 0, is_demo,
           jsonb_build_object('cmd_id', cmd_id, 'origem', origem, 'acao', acao, 'cena', cena, 'modo', modo,
                              'status', status, 'motivo', motivo, 'por', requested_by, 'latencia_ms', latency_ms)
      FROM commands;
