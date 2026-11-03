import { useEffect, useState } from 'react'
import { api, rangeParams } from '../api'
import { fmtAgo, fmtDateTime, fmtNum, fmtNum1 } from '../format'
import { SCENE_ORDER, SCENE_RANGE, sceneColor, sceneLabel } from '../scenes'
import type {
  AppConfig, CommandRow, ConfirmationRow, EventRow, LiveState, Page, Range, SceneAnalysis, Series, Stats,
} from '../types'
import { LuminosityChart, SceneDistribution, SceneStrip, StateHistoryChart } from './charts'
import { EventList } from './events'
import { Empty, Panel, SceneBadge, Status, type Tone } from './ui'
import type { WsStatus } from '../useLive'

const BOUNDS = [[0, 150], [150, 400], [400, 1000], [1000, 4096]]

function scalePos(raw: number) {
  const i = raw < 150 ? 0 : raw < 400 ? 1 : raw < 1000 ? 2 : 3
  const [lo, hi] = BOUNDS[i]
  return ((i + (raw - lo) / (hi - lo)) / 4) * 100
}

function LuminosityHero({ live, now }: { live: LiveState; now: number }) {
  const r = live.sensor.last_reading
  const cena = r?.cena_computed ?? live.sensor.last_command?.cena ?? null
  const active = SCENE_ORDER.indexOf(cena as never)
  return (
    <Panel title="Luminosidade atual" sub="leitura bruta do LDR · ADC 12 bits (0–4095), sem conversão para lux">
      {r ? (
        <div className="readout">
          <span className="big">{fmtNum(r.raw)}</span>
          <span className="unit">
            ADC bruto<br />{fmtAgo(r.at, now)}
          </span>
        </div>
      ) : (
        <div className="readout">
          <span className="big muted">—</span>
          <span className="unit" style={{ maxWidth: 360 }}>
            Valor analógico não publicado pelo firmware atual. A cena abaixo vem do comando do sensor.
          </span>
        </div>
      )}
      <div className="scale" aria-label="Faixas de classificação do firmware">
        <div className="scale-track">
          {SCENE_ORDER.map((k, i) => (
            <div key={k} className={`scale-seg ${i === active ? 'active' : ''}`} style={{ background: sceneColor(k) }} />
          ))}
          {r && <div className="scale-marker" style={{ left: `calc(${scalePos(r.raw)}% - 1px)` }} />}
        </div>
        <div className="scale-labels">
          {SCENE_ORDER.map((k, i) => (
            <div key={k} className={i === active ? 'active' : ''}><b>{sceneLabel(k)}</b><span className="num">{SCENE_RANGE[k]}</span></div>
          ))}
        </div>
      </div>
      {r?.cena_reported && r.cena_reported !== r.cena_computed && (
        <p className="note">O sensor reportou "{r.cena_reported}" mas a leitura {r.raw} classifica como "{r.cena_computed}".</p>
      )}
    </Panel>
  )
}

function SceneCard({ live, now }: { live: LiveState; now: number }) {
  const c = live.sensor.last_command
  return (
    <Panel title="Classificação luminosa" sub="cena publicada pelo sensor">
      {c ? (
        <>
          <div className="row" style={{ gap: 10 }}>
            <span className="scene-dot" style={{ background: sceneColor(c.cena), width: 16, height: 16, borderRadius: 4 }} />
            <div className="scene-name">{sceneLabel(c.cena)}</div>
          </div>
          <dl className="kv" style={{ marginTop: 10 }}>
            <dt>Faixa do firmware</dt><dd className="num">{SCENE_RANGE[c.cena] ?? 'cena desconhecida'}</dd>
            <dt>Desde</dt><dd>{fmtDateTime(c.at)}</dd>
            <dt>Duração</dt><dd>{fmtAgo(c.at, now).replace('há ', '')}</dd>
            <dt>Cena anterior</dt><dd>{c.previous ? <SceneBadge cena={c.previous} /> : '—'}</dd>
          </dl>
        </>
      ) : (
        <Empty title="Nenhum comando recebido ainda">O sensor publica somente quando a cena muda.</Empty>
      )}
    </Panel>
  )
}

const SYNC: Record<string, [Tone, string]> = {
  sincronizado: ['good', 'Confirmado pelo atuador'],
  aguardando_confirmacao: ['warning', 'Aguardando confirmação'],
  sem_confirmacao: ['critical', 'Atuador não confirmou'],
  divergente: ['critical', 'Estados divergentes'],
  sem_comando: ['neutral', 'Sem comando registrado'],
  sem_dados: ['neutral', 'Sem dados'],
}

function ActuatorCard({ live, config, now }: { live: LiveState; config: AppConfig; now: number }) {
  const cmd = live.sensor.last_command
  const conf = live.actuator.confirmed
  const [tone, label] = SYNC[live.sync]
  const leds = conf?.leds ?? [false, false, false, false]
  return (
    <Panel title="Estado dos atuadores" right={<Status tone={tone}>{label}</Status>}>
      <div className="cmp">
        <div>
          <div className="lbl">Comandado</div>
          <div className="val">{cmd ? <><span className="scene-dot" style={{ background: sceneColor(cmd.cena) }} />{sceneLabel(cmd.cena)}</> : '—'}</div>
          <div className="small muted">{cmd ? fmtAgo(cmd.at, now) : 'nenhum'}</div>
        </div>
        <div>
          <div className="lbl">Confirmado</div>
          <div className="val">{conf ? <><span className="scene-dot" style={{ background: sceneColor(conf.cena) }} />{sceneLabel(conf.cena)}</> : '—'}</div>
          <div className="small muted">
            {conf ? (conf.retained ? 'retido no broker' : fmtAgo(conf.at, now)) : 'nenhuma'}
            {cmd?.latency_ms != null && cmd.status === 'confirmado' && <> · <span className="num">{cmd.latency_ms} ms</span></>}
          </div>
        </div>
      </div>
      <div className="leds" role="list" aria-label="LEDs do atuador">
        {config.firmware.leds.map((l, i) => (
          <div key={l.id} role="listitem" className={`led ${leds[i] ? 'on' : ''}`}>
            <div className="led-bulb" />
            <span className="led-name">{l.name}</span>
            <span className="led-gpio">GPIO{l.gpio}</span>
            <span className="led-state">{leds[i] ? 'aceso' : 'apagado'}</span>
          </div>
        ))}
      </div>
      <p className="note">
        LEDs derivados da cena confirmada, conforme <code>onMessage()</code> do atuador (na cena extrema os quatro acendem).
        A confirmação informa a cena executada, não a leitura física dos pinos.
      </p>
    </Panel>
  )
}

function sensorStatus(live: LiveState, now: number): [Tone, string, string] {
  const s = live.sensor
  if (s.presence) return s.presence.status === 'online'
    ? ['good', 'Online', `anunciado ${fmtAgo(s.presence.at, now)} (LWT)`]
    : ['critical', 'Offline', `LWT recebido ${fmtAgo(s.presence.at, now)}`]
  if (s.telemetry_seen && s.last_reading) {
    const age = (now - new Date(s.last_reading.at).getTime()) / 1000
    return age < 15 ? ['good', 'Transmitindo', `telemetria ${fmtAgo(s.last_reading.at, now)}`]
      : ['warning', 'Sem telemetria recente', `última leitura ${fmtAgo(s.last_reading.at, now)}`]
  }
  return ['neutral', 'Presença desconhecida', `última mensagem ${fmtAgo(s.last_message_at, now)} · publica só quando a cena muda`]
}

function actuatorStatus(live: LiveState, now: number): [Tone, string, string] {
  const a = live.actuator
  if (a.presence?.status === 'offline') return ['critical', 'Offline', `LWT recebido ${fmtAgo(a.presence.at, now)}`]
  const last = `última confirmação ${a.confirmed?.retained ? '(retida)' : fmtAgo(a.last_message_at, now)}`
  if (live.sync === 'sem_confirmacao') return ['critical', 'Não confirmou o último comando', last]
  if (live.sync === 'aguardando_confirmacao') return ['warning', 'Aguardando confirmação', last]
  if (live.sync === 'sincronizado') return ['good', 'Respondendo', last]
  if (a.presence?.status === 'online') return ['good', 'Online', `anunciado ${fmtAgo(a.presence.at, now)}`]
  return ['neutral', a.last_message_at ? 'Sem comando para confirmar' : 'Sem mensagens', last]
}

function Connectivity({ live, ws, now }: { live: LiveState; ws: WsStatus; now: number }) {
  const b = live.broker
  const brokerTone: Tone = b.status === 'conectado' ? 'good' : b.status === 'demo' ? 'demo' : b.status === 'desativado' ? 'neutral' : b.status === 'conectando' ? 'warning' : 'critical'
  const brokerLabel = { conectado: 'Conectado', desconectado: 'Desconectado', conectando: 'Conectando…', desativado: 'Desativado', demo: 'Demonstração' }[b.status]
  const [sTone, sLabel, sDetail] = sensorStatus(live, now)
  const [aTone, aLabel, aDetail] = actuatorStatus(live, now)
  return (
    <Panel title="Conectividade">
      <div className="conn-list">
        <div className="conn-item">
          <span className="who">Backend ↔ broker MQTT</span><Status tone={brokerTone}>{brokerLabel}</Status>
          <span className="detail">
            {b.status === 'demo' ? 'gerador local, sem broker' : `${b.host ?? '—'}:${b.port ?? ''} · desde ${fmtAgo(b.since, now).replace('há ', '')}`}
            {b.last_error && b.status !== 'conectado' && <> · {b.last_error}{b.attempts > 1 && ` · tentativa ${b.attempts}`}</>}
          </span>
        </div>
        <div className="conn-item">
          <span className="who">ESP32 Sensor</span><Status tone={sTone}>{sLabel}</Status>
          <span className="detail">{sDetail}</span>
        </div>
        <div className="conn-item">
          <span className="who">ESP32 Atuador</span><Status tone={aTone}>{aLabel}</Status>
          <span className="detail">{live.actuator.device ? `${live.actuator.device} · ` : ''}{aDetail}</span>
        </div>
        <div className="conn-item">
          <span className="who">Painel em tempo real</span>
          <Status tone={ws === 'aberto' ? 'good' : ws === 'conectando' ? 'warning' : 'critical'}>{ws === 'aberto' ? 'Ao vivo' : ws === 'conectando' ? 'Conectando…' : 'Reconectando'}</Status>
          <span className="detail">Última mensagem MQTT: {fmtDateTime(live.last_message_at)}</span>
        </div>
      </div>
    </Panel>
  )
}

function StatTiles({ stats }: { stats: Stats | null }) {
  const r = stats?.readings
  const c = stats?.commands
  const rate = c && c.count ? (c.confirmed / c.count) * 100 : null
  const tiles: [string, string, string][] = [
    ['Mínima', fmtNum(r?.min), 'ADC bruto'],
    ['Máxima', fmtNum(r?.max), 'ADC bruto'],
    ['Média', fmtNum1(r?.avg), 'ADC bruto'],
    ['Leituras', fmtNum(r?.count), r?.count ? 'telemetria' : 'requer patch do sensor'],
    ['Transições', fmtNum(c?.count), 'comandos de cena'],
    ['Confirmadas', rate === null ? '—' : `${fmtNum1(rate)}%`, c?.latency_avg_ms != null ? `latência média ${fmtNum(Math.round(c.latency_avg_ms))} ms` : 'pelo atuador'],
  ]
  return (
    <div className="grid g-stats">
      {tiles.map(([l, v, h]) => (
        <div className="tile" key={l}><div className="lbl">{l}</div><div className="val">{v}</div><div className="hint">{h}</div></div>
      ))}
    </div>
  )
}

export function Overview(props: { live: LiveState; config: AppConfig; range: Range; refreshKey: number; ws: WsStatus; now: number }) {
  const { live, config, range, refreshKey, ws, now } = props
  const [stats, setStats] = useState<Stats | null>(null)
  const [series, setSeries] = useState<Series | null>(null)
  const [scenes, setScenes] = useState<SceneAnalysis | null>(null)
  const [cmds, setCmds] = useState<CommandRow[]>([])
  const [confs, setConfs] = useState<ConfirmationRow[]>([])
  const [events, setEvents] = useState<EventRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const p = rangeParams(range)
    let cancel = false
    Promise.all([
      api.get<Stats>('/api/stats', p),
      api.get<Series>('/api/readings/series', p),
      api.get<SceneAnalysis>('/api/analytics/scenes', p),
      api.get<Page<CommandRow>>('/api/commands', { ...p, limit: 1000 }),
      api.get<Page<ConfirmationRow>>('/api/confirmations', { ...p, limit: 1000 }),
      api.get<Page<EventRow>>('/api/events', { ...p, limit: 60 }),
    ]).then(([s, se, sc, c, cf, ev]) => {
      if (cancel) return
      setStats(s); setSeries(se); setScenes(sc)
      setCmds([...c.items].reverse()); setConfs([...cf.items].reverse()); setEvents(ev.items)
      setError(null)
    }).catch((e) => !cancel && setError(String(e.message ?? e)))
    return () => { cancel = true }
  }, [range, refreshKey])

  return (
    <div className="stack">
      {error && <div className="banner warn"><b>Erro ao consultar o histórico:</b> {error}</div>}
      <div className="grid g-hero">
        <LuminosityHero live={live} now={now} />
        <SceneCard live={live} now={now} />
        <ActuatorCard live={live} config={config} now={now} />
      </div>
      <StatTiles stats={stats} />
      <div className="grid g-main">
        <div className="stack">
          <Panel title="Luminosidade ao longo do tempo"
            sub={series && series.points.length ? `média por intervalo de ${series.bucket_s}s · faixa = mín–máx` : undefined}>
            <LuminosityChart series={series} range={range} />
          </Panel>
          <Panel title="Histórico de mudanças de estado" sub="comandado × confirmado">
            <StateHistoryChart commands={cmds} confirmations={confs} range={range} />
            <div style={{ marginTop: 12 }}><SceneStrip analysis={scenes} range={range} /></div>
          </Panel>
          <Panel title="Distribuição das cenas" sub="tempo em cada cena no período">
            <SceneDistribution analysis={scenes} />
          </Panel>
        </div>
        <div className="stack">
          <Connectivity live={live} ws={ws} now={now} />
          <Panel title="Histórico de eventos" sub="mais recentes primeiro">
            <div className="scroll">{events.length ? <EventList events={events} /> : <Empty title="Sem eventos no período" />}</div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
