import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { Alerts } from './components/Alerts'
import { History } from './components/History'
import { Overview } from './components/Overview'
import { System } from './components/System'
import { Status } from './components/ui'
import { toLocalInput } from './format'
import type { AppConfig, Range } from './types'
import { useLive, useNow, useThrottled } from './useLive'

const PRESETS: [string, number][] = [
  ['15 min', 15 * 60e3], ['1 h', 3600e3], ['6 h', 6 * 3600e3], ['24 h', 24 * 3600e3], ['7 dias', 7 * 86400e3], ['30 dias', 30 * 86400e3],
]
type Tab = 'visao' | 'historico' | 'alertas' | 'sistema'
const TABS: [Tab, string][] = [['visao', 'Visão geral'], ['historico', 'Histórico'], ['alertas', 'Alertas'], ['sistema', 'Sistema']]

export default function App() {
  const { state: live, wsStatus, version } = useLive()
  const now = useNow(1000)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('visao')
  const [preset, setPreset] = useState<number | null>(3600e3)
  const [custom, setCustom] = useState<{ from: string; to: string }>(() => ({
    from: toLocalInput(new Date(Date.now() - 3600e3)), to: toLocalInput(new Date()),
  }))

  useEffect(() => {
    api.get<AppConfig>('/api/config').then(setConfig).catch((e) => setConfigError(String(e.message ?? e)))
  }, [])

  // Em período "ao vivo", cada novo evento desloca a janela (no máximo a cada 2 s).
  const liveTick = useThrottled(version, 2000)
  const range: Range = useMemo(() => {
    if (preset !== null) {
      const to = new Date()
      return { from: new Date(to.getTime() - preset), to, live: true }
    }
    return { from: new Date(custom.from), to: new Date(custom.to), live: false }
  }, [preset, custom, preset !== null ? liveTick : 0])

  // Histórico paginado usa janela fixa (não desloca enquanto o usuário navega nas páginas).
  const [historyNonce, setHistoryNonce] = useState(0)
  const stableRange: Range = useMemo(() => {
    if (preset !== null) {
      const to = new Date()
      return { from: new Date(to.getTime() - preset), to, live: false }
    }
    return { from: new Date(custom.from), to: new Date(custom.to), live: false }
  }, [preset, custom, historyNonce])

  const openAlerts = live?.open_alerts.length ?? 0

  if (configError) return <div className="app"><div className="banner warn" style={{ marginTop: 20 }}><b>Backend indisponível:</b>&nbsp;{configError}</div></div>
  if (!config || !live) return <div className="app"><div className="empty" style={{ minHeight: '60vh' }}>Conectando ao backend…</div></div>

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#21211f" /><circle cx="16" cy="16" r="5.5" fill="#b7d3f6" /><g stroke="#6da7ec" strokeWidth="2.2" strokeLinecap="round"><path d="M16 4.5v3M16 24.5v3M4.5 16h3M24.5 16h3M8 8l2 2M22 22l2 2M8 24l2-2M22 10l2-2" /></g></svg>
          <div><h1>Luz Ambiente · Telemetria</h1><small>ESP32 Sensor LDR → HiveMQ → ESP32 Atuador</small></div>
        </div>
        {live.demo && <Status tone="demo">Modo demonstração</Status>}
        <nav className="tabs" role="tablist">
          {TABS.map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
              {l}{k === 'alertas' && openAlerts > 0 && <span className="pill" style={{ marginLeft: 6, background: 'rgba(208,59,59,.25)', color: '#ef8a8a' }}>{openAlerts}</span>}
            </button>
          ))}
        </nav>
      </header>

      {live.demo && (
        <div className="banner demo" role="status">
          <Status tone="demo"><b>Dados sintéticos</b></Status>
          <span>O backend está em <code>DEMO_MODE</code>: um gerador local produz mensagens no formato real do firmware (inclusive a telemetria do patch opcional). Nada vem dos ESP32 e esses registros ficam separados (<code>is_demo</code>). Desative para usar o HiveMQ.</span>
        </div>
      )}
      {!live.demo && live.broker.status !== 'conectado' && (
        <div className="banner warn" role="alert">
          <Status tone="critical">Sem conexão com o broker</Status>
          <span>{live.broker.host}:{live.broker.port} — {live.broker.last_error ?? live.broker.status}. Reconexão automática em andamento; o histórico continua disponível.</span>
        </div>
      )}

      {tab !== 'sistema' && (
        <div className="filterbar">
          <span className="label">Período</span>
          <div className="chips" role="group" aria-label="Período">
            {PRESETS.map(([l, ms]) => (
              <button key={l} className="chip" aria-pressed={preset === ms} onClick={() => setPreset(ms)}>{l}</button>
            ))}
            <button className="chip" aria-pressed={preset === null} onClick={() => {
              setCustom({ from: toLocalInput(range.from), to: toLocalInput(range.to) }); setPreset(null)
            }}>Personalizado</button>
          </div>
          {preset === null && (
            <>
              <input type="datetime-local" value={custom.from} aria-label="De" onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
              <span className="muted">até</span>
              <input type="datetime-local" value={custom.to} aria-label="Até" onChange={(e) => setCustom({ ...custom, to: e.target.value })} />
            </>
          )}
          {preset !== null && <span className="small muted">atualiza ao vivo</span>}
        </div>
      )}

      {tab === 'visao' && <Overview live={live} config={config} range={range} refreshKey={liveTick} ws={wsStatus} now={now} />}
      {tab === 'historico' && <History range={stableRange} refreshKey={0} onRefresh={() => setHistoryNonce((n) => n + 1)} />}
      {tab === 'alertas' && <Alerts live={live} range={range} refreshKey={liveTick} />}
      {tab === 'sistema' && <System config={config} live={live} />}
    </div>
  )
}
