import { useEffect, useState } from 'react'
import { api, exportUrl, rangeParams } from '../api'
import { fmtDateTime, fmtDuration, fmtShort } from '../format'
import { SCENE_ORDER, sceneLabel } from '../scenes'
import type { Alert, AlertRule, LiveState, Page, Range, SceneAnalysis } from '../types'
import { Empty, Pager, Panel, SceneBadge, Status, Switch, type Tone } from './ui'

const SEV_TONE: Record<string, Tone> = { critico: 'critical', aviso: 'warning', info: 'neutral' }
const SEV_LABEL: Record<string, string> = { critico: 'Crítico', aviso: 'Aviso', info: 'Info' }

const KIND_HELP: Record<string, string> = {
  scene: 'Dispara enquanto a cena publicada pelo sensor estiver entre as selecionadas. As cenas e seus limites vêm do firmware.',
  raw_above: 'Requer telemetria bruta (patch do sensor). O projeto não define este limite — informe um valor ADC (0–4095).',
  raw_below: 'Requer telemetria bruta (patch do sensor). O projeto não define este limite — informe um valor ADC (0–4095).',
  silence: '',
  confirmation_timeout: 'Tempo máximo entre o comando do sensor e a confirmação do atuador. Não definido no firmware.',
  broker_disconnected: 'Dispara quando o backend perde a conexão com o broker MQTT.',
  device_offline: 'Dispara quando um dispositivo anuncia offline por LWT. Só funciona com o patch de presença.',
}

function RuleEditor({ rule, onSaved }: { rule: AlertRule; onSaved: (r: AlertRule) => void }) {
  const [params, setParams] = useState<Record<string, unknown>>(rule.params)
  const [severity, setSeverity] = useState(rule.severity)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setParams(rule.params); setSeverity(rule.severity) }, [rule])
  const dirty = JSON.stringify(params) !== JSON.stringify(rule.params) || severity !== rule.severity

  const save = async (enabled: boolean) => {
    setBusy(true)
    try {
      const r = await api.put<AlertRule>(`/api/alert-rules/${rule.id}`, { enabled, params, severity })
      onSaved(r); setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const num = (key: string, label: string, unit: string, min: number, max: number) => (
    <label className="row" style={{ gap: 6 }}>
      {label}
      <input type="number" min={min} max={max} value={params[key] == null ? '' : String(params[key])} placeholder="não definido"
        onChange={(e) => setParams({ ...params, [key]: e.target.value === '' ? null : Number(e.target.value) })} />
      <span className="muted">{unit}</span>
    </label>
  )

  return (
    <div className="rule">
      <Switch checked={rule.enabled} disabled={busy} label={`Ativar ${rule.name}`} onChange={(v) => save(v)} />
      <div>
        <div className="row" style={{ gap: 8 }}>
          <b style={{ fontWeight: 500 }}>{rule.name}</b>
          {rule.enabled ? <span className="pill">ativa</span> : <span className="pill muted">inativa</span>}
        </div>
        <div className="small muted">{rule.kind === 'silence'
          ? (params.component === 'sensor'
            ? 'Atenção: o firmware do sensor só publica quando a cena muda; silêncio longo pode ser normal com luz estável (sem o patch de telemetria).'
            : 'O atuador só publica ao confirmar um comando; silêncio é esperado quando a cena não muda.')
          : KIND_HELP[rule.kind]}</div>
        <div className="rule-params">
          {rule.kind === 'scene' && SCENE_ORDER.map((k) => {
            const list = (params.scenes as string[]) ?? []
            return (
              <label key={k} className="row" style={{ gap: 4 }}>
                <input type="checkbox" checked={list.includes(k)}
                  onChange={(e) => setParams({ scenes: e.target.checked ? [...list, k] : list.filter((x) => x !== k) })} />
                {sceneLabel(k)}
              </label>
            )
          })}
          {(rule.kind === 'raw_above' || rule.kind === 'raw_below') && num('threshold', rule.kind === 'raw_above' ? 'acima de' : 'abaixo de', 'ADC', 0, 4095)}
          {rule.kind === 'silence' && num('seconds', `sem mensagens do ${params.component} por mais de`, 's', 1, 604800)}
          {rule.kind === 'confirmation_timeout' && num('ms', 'sem confirmação após', 'ms', 50, 600000)}
          <label className="row" style={{ gap: 6 }}>
            severidade
            <select value={severity} onChange={(e) => setSeverity(e.target.value as AlertRule['severity'])}>
              <option value="info">info</option><option value="aviso">aviso</option><option value="critico">crítico</option>
            </select>
          </label>
        </div>
        {error && <div className="error-text" role="alert">{error}</div>}
      </div>
      <button className="btn small" disabled={!dirty || busy} onClick={() => save(rule.enabled)}>Salvar</button>
    </div>
  )
}

export function Alerts({ live, range, refreshKey }: { live: LiveState; range: Range; refreshKey: number }) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [hist, setHist] = useState<Page<Alert> | null>(null)
  const [offset, setOffset] = useState(0)
  const [analysis, setAnalysis] = useState<SceneAnalysis | null>(null)

  useEffect(() => { api.get<AlertRule[]>('/api/alert-rules').then(setRules).catch(() => {}) }, [])
  useEffect(() => { setOffset(0) }, [range])
  useEffect(() => {
    api.get<Page<Alert>>('/api/alerts', { ...rangeParams(range), limit: 25, offset }).then(setHist).catch(() => {})
  }, [range, offset, refreshKey])
  useEffect(() => {
    api.get<SceneAnalysis>('/api/analytics/scenes', rangeParams(range)).then(setAnalysis).catch(() => {})
  }, [range, refreshKey])

  const ack = async (id: number) => { await api.post(`/api/alerts/${id}/ack`) }

  return (
    <div className="stack">
      <div className="grid g-2">
        <Panel title="Alertas abertos" sub={`${live.open_alerts.length}`}>
          {live.open_alerts.length === 0 ? <Empty title="Nenhum alerta aberto" /> : live.open_alerts.map((a) => (
            <div className="alert-row" key={a.id}>
              <Status tone={SEV_TONE[a.severity]}>{SEV_LABEL[a.severity]}</Status>
              <div>
                <div>{a.message}</div>
                <div className="small muted">desde {fmtDateTime(a.opened_at)}{a.acknowledged_at && ' · reconhecido'}</div>
              </div>
              {!a.acknowledged_at && <button className="btn small" onClick={() => ack(a.id)}>Reconhecer</button>}
            </div>
          ))}
        </Panel>
        <Panel title="Períodos de exposição intensa" sub="trechos contínuos em cena alta ou extrema">
          {!analysis ? <div className="empty">Carregando…</div> : analysis.intense_periods.length === 0 ? (
            <Empty title="Nenhum período intenso no intervalo selecionado" />
          ) : (
            <div className="table-wrap scroll" style={{ maxHeight: 300 }}>
              <table>
                <thead><tr><th>Início</th><th>Fim</th><th className="r">Duração</th><th className="r">Em extrema</th><th>Cenas</th></tr></thead>
                <tbody>
                  {analysis.intense_periods.map((p) => (
                    <tr key={p.start}>
                      <td className="num">{fmtShort(p.start)}</td><td className="num">{fmtShort(p.end)}</td>
                      <td className="r num">{fmtDuration(p.duration_s)}</td><td className="r num">{fmtDuration(p.extrema_s)}</td>
                      <td><div className="row" style={{ gap: 4 }}>{p.cenas.map((c) => <SceneBadge key={c} cena={c} />)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Regras de alerta" sub="limites que o projeto não define começam vazios e precisam ser configurados">
        {rules.map((r) => (
          <RuleEditor key={r.id} rule={r} onSaved={(nr) => setRules((rs) => rs.map((x) => (x.id === nr.id ? nr : x)))} />
        ))}
      </Panel>

      <Panel title="Histórico de alertas"
        right={<div className="row"><a className="btn small" href={exportUrl('alerts', 'csv', range)}>CSV</a><a className="btn small" href={exportUrl('alerts', 'json', range)}>JSON</a></div>}>
        {hist && hist.items.length === 0 ? <Empty title="Nenhum alerta no período" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Severidade</th><th>Mensagem</th><th>Aberto em</th><th>Encerrado em</th><th className="r">Duração</th></tr></thead>
              <tbody>
                {hist?.items.map((a) => (
                  <tr key={a.id}>
                    <td><Status tone={SEV_TONE[a.severity]}>{SEV_LABEL[a.severity]}</Status></td>
                    <td>{a.message}{a.context && 'motivo_encerramento' in a.context && <div className="small muted">encerrado: {String(a.context.motivo_encerramento)}</div>}</td>
                    <td className="num">{fmtDateTime(a.opened_at)}</td>
                    <td className="num">{a.closed_at ? fmtDateTime(a.closed_at) : <span className="pill">aberto</span>}</td>
                    <td className="r num">{fmtDuration(((a.closed_at ? new Date(a.closed_at).getTime() : Date.now()) - new Date(a.opened_at).getTime()) / 1000)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hist && <Pager total={hist.total} limit={25} offset={offset} onChange={setOffset} />}
      </Panel>
    </div>
  )
}
