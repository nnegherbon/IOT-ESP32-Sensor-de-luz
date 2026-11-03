export type SceneKey = 'escuro' | 'ambiente' | 'alta' | 'extrema'

export interface Scene {
  key: SceneKey
  label: string
  lower: number | null
  upper: number | null
  order: number
  leds: boolean[]
}

export interface Led {
  id: number
  name: string
  gpio: number
  const: string
}

export interface AppConfig {
  demo: boolean
  mqtt: { enabled: boolean; host: string; port: number; tls: boolean; subscription: string; auth: boolean }
  firmware: {
    topics: {
      command: string
      actuator_status: string
      optional: { sensor_telemetry: string; sensor_connection: string; actuator_connection: string }
    }
    device_ids: { sensor: string; actuator: string }
    adc: { min: number; max: number; unit: string }
    scenes: Scene[]
    leds: Led[]
  }
  features: { servo: boolean }
}

export type CommandStatus = 'aguardando' | 'confirmado' | 'sem_confirmacao' | 'substituido'

export interface CommandView {
  id: number
  cena: string
  known_scene: boolean
  at: string
  previous: string | null
  status: CommandStatus
  confirmed_at: string | null
  latency_ms: number | null
}

export interface ConfirmationView {
  id: number
  cena: string
  estado: string
  at: string
  retained: boolean
  match_status: 'confirmou_comando' | 'sem_comando_correspondente' | 'retido_inicial'
  command_id: number | null
  leds: boolean[]
  known_scene: boolean
}

export interface ReadingView {
  id: number
  raw: number
  cena_computed: string
  cena_reported: string | null
  at: string
  uptime_ms: number | null
}

export interface Presence {
  status: 'online' | 'offline'
  at: string
  retained?: boolean
}

export type BrokerStatus = 'conectado' | 'desconectado' | 'conectando' | 'desativado' | 'demo'

export interface Alert {
  id: number
  rule_id: number | null
  kind: string
  severity: 'info' | 'aviso' | 'critico'
  status: 'aberto' | 'encerrado'
  opened_at: string
  closed_at: string | null
  message: string
  context: Record<string, unknown> | null
  acknowledged_at: string | null
  is_demo?: boolean
}

export type SyncState =
  | 'sem_dados'
  | 'aguardando_confirmacao'
  | 'sem_confirmacao'
  | 'sincronizado'
  | 'sem_comando'
  | 'divergente'

export interface LiveState {
  now: string
  demo: boolean
  started_at: string
  broker: {
    status: BrokerStatus
    since: string
    host: string | null
    port: number | null
    last_error: string | null
    attempts: number
  }
  sensor: {
    last_message_at: string | null
    last_command: CommandView | null
    last_reading: ReadingView | null
    telemetry_seen: boolean
    presence: Presence | null
  }
  actuator: {
    device: string | null
    last_message_at: string | null
    confirmed: ConfirmationView | null
    presence: Presence | null
  }
  sync: SyncState
  last_message_at: string | null
  stats: { recebidas: number; invalidas: number; erros: number; nao_tratadas: number }
  open_alerts: Alert[]
  ws_clients: number
}

export interface Page<T> {
  total: number
  limit: number
  offset: number
  from: string
  to: string
  items: T[]
}

export interface Stats {
  from: string
  to: string
  readings: { min: number | null; max: number | null; avg: number | null; count: number; first_at: string | null; last_at: string | null }
  commands: {
    count: number
    confirmed: number
    unconfirmed: number
    pending: number
    latency_avg_ms: number | null
    latency_p95_ms: number | null
    latency_max_ms: number | null
  }
  confirmations: number
  messages: { count: number; invalid: number; errors: number }
  alerts: number
}

export interface SeriesPoint {
  t: string
  min: number
  max: number
  avg: number
  n: number
}

export interface Series {
  bucket_s: number
  from: string
  to: string
  points: SeriesPoint[]
}

export interface SceneInterval {
  cena: string
  start: string
  end: string
  duration_s: number
}

export interface SceneAnalysis {
  from: string
  to: string
  covered_s: number
  intervals: SceneInterval[]
  intervals_total: number
  distribution: { cena: string; duration_s: number; count: number; share: number }[]
  intense_periods: { start: string; end: string; duration_s: number; extrema_s: number; cenas: string[] }[]
}

export interface EventRow {
  occurred_at: string
  category: 'transicao_cena' | 'confirmacao' | 'conectividade' | 'alerta' | 'mensagem_invalida'
  ref_id: number
  detail: Record<string, unknown>
}

export interface AlertRule {
  id: number
  kind: 'scene' | 'raw_above' | 'raw_below' | 'silence' | 'confirmation_timeout' | 'broker_disconnected' | 'device_offline'
  name: string
  enabled: boolean
  severity: 'info' | 'aviso' | 'critico'
  params: Record<string, unknown>
  builtin: boolean
  created_at: string
  updated_at: string
}

export interface CommandRow {
  id: number
  received_at: string
  cena: string
  previous_cena: string | null
  known_scene: boolean
  status: CommandStatus
  confirmed_at: string | null
  latency_ms: number | null
}

export interface ConfirmationRow {
  id: number
  received_at: string
  device: string
  estado: string
  cena: string
  retained: boolean
  led1: boolean
  led2: boolean
  led3: boolean
  led4: boolean
  match_status: string
  command_id: number | null
}

export interface ReadingRow {
  id: number
  received_at: string
  raw: number
  cena_computed: string
  cena_reported: string | null
  uptime_ms: number | null
}

export interface MessageRow {
  id: number
  received_at: string
  topic: string
  origin: string
  qos: number | null
  retained: boolean
  parse_status: 'ok' | 'invalido' | 'nao_tratado' | 'erro_processamento'
  error_reason: string | null
  error_details: Record<string, unknown> | null
  payload: string | null
}

export interface Range {
  from: Date
  to: Date
  live: boolean
}
