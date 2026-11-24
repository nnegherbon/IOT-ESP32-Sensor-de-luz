import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { fmtDateTime } from '../format'
import type { LiveState } from '../types'
import type { SessionUser } from './Login'
import { Panel, SceneBadge, Status } from './ui'

interface Command {
  cmd_id: string
  device: string
  origem: 'auto' | 'manual'
  acao: 'aplicar' | 'definir_modo'
  cena: string | null
  modo: string | null
  duracao_s: number | null
  requested_by: string
  reason: string | null
  status: string
  motivo: string | null
  sent_at: string
  received_at: string | null
  executed_at: string | null
  confirmed_at: string | null
  retries: number
  duplicate_acks: number
  latency_ms: number | null
}

interface Decision {
  enabled: boolean
  limite_ambiente: number
  limite_alta: number
  limite_extrema: number
  histerese: number
  confirmacao_s: number
  updated_by: string
  updated_at: string | null
}

interface Estado {
  modo: 'auto' | 'manual' | 'seguro'
  cena: string | null
  leds: boolean[]
  sombra: string | null
  manual_restante_s: number | null
  ultimo_cmd_id: string | null
  motivo_seguro: string | null
  at: string
}

interface V1Snapshot {
  decision: Decision
  decided_scene: string | null
  sensors: Record<string, { online?: boolean; raw?: number; sensor_ok?: boolean; falha?: string | null; seq?: number; at?: string; fw?: string; ip?: string; perdidas?: number; hora_sync?: boolean }>
  actuators: Record<string, { online?: boolean; estado?: Estado; fw?: string; ip?: string; last_command?: Command }>
  publisher: boolean
}

const STEPS = ['enviado', 'recebido', 'executado', 'confirmado'] as const
const SCENES = ['escuro', 'ambiente', 'alta', 'extrema']

function statusTone(s: string) {
  if (s === 'confirmado') return 'good' as const
  if (s === 'rejeitado' || s === 'sem_confirmacao' || s === 'falha_envio') return 'critical' as const
  return 'warning' as const
}

const STATUS_LABEL: Record<string, string> = {
  enviado: 'enviado', recebido: 'recebido', executado: 'executado', confirmado: 'confirmado',
  rejeitado: 'rejeitado', sem_confirmacao: 'sem confirmação', falha_envio: 'falha no envio',
}

function Stepper({ c }: { c: Command }) {
  const reached = c.status === 'rejeitado' ? 2 : c.status === 'sem_confirmacao' || c.status === 'falha_envio' ? 0
    : STEPS.indexOf(c.status as typeof STEPS[number]) + 1
  return (
    <span className="stepper" aria-label={`ciclo: ${STATUS_LABEL[c.status] ?? c.status}`}>
      {STEPS.map((s, i) => <span key={s} className={`step ${i < reached ? 'on' : ''}`} title={s}>{s}</span>)}
    </span>
  )
}

export function Control({ live, user, refreshKey }: { live: LiveState; user: SessionUser; refreshKey: number }) {
  const v1 = (live as unknown as { v1: V1Snapshot | null }).v1
  const [commands, setCommands] = useState<Command[]>([])
  const [decision, setDecision] = useState<Decision | null>(null)
  const [draft, setDraft] = useState<Decision | null>(null)
  const [msg, setMsg] = useState<{ tone: 'good' | 'critical'; text: string } | null>(null)
  const [notif, setNotif] = useState<{ channels: string[]; items: { id: number; sent_at: string; channel: string; message: string; ok: boolean; error: string | null }[] } | null>(null)
  const [duracao, setDuracao] = useState(300)

  const load = useCallback(() => {
    api.get<Command[]>('/api/v1/commands', { limit: 12 }).then(setCommands).catch(() => {})
    api.get<typeof notif>('/api/v1/notifications', { limit: 5 }).then(setNotif).catch(() => {})
  }, [])
  useEffect(load, [load, refreshKey])
  useEffect(() => {
    api.get<Decision>('/api/v1/decision').then((d) => { setDecision(d); setDraft(d) }).catch(() => {})
  }, [])

  const sensor = v1?.sensors?.sensor01
  const act = v1?.actuators?.atuador01
  const est = act?.estado
  const can = user.can_command

  // O botão do modo só fica "ativo" quando o ATUADOR confirma o modo (estado retido);
  // até lá o botão clicado mostra "aguardando…". Some sozinho em 8 s se não houver confirmação.
  const [pendingMode, setPendingMode] = useState<'auto' | 'manual' | null>(null)
  useEffect(() => {
    if (pendingMode && est?.modo === pendingMode) setPendingMode(null)
  }, [est?.modo, pendingMode])
  useEffect(() => {
    if (!pendingMode) return
    const id = window.setTimeout(() => setPendingMode(null), 8000)
    return () => window.clearTimeout(id)
  }, [pendingMode])

  async function send(body: Record<string, unknown>, label: string) {
    setMsg(null)
    try {
      const c = await api.post<Command>('/api/v1/commands', body)
      if (c.status === 'falha_envio') setPendingMode(null)
      setMsg({ tone: c.status === 'falha_envio' ? 'critical' : 'good', text: `${label}: comando ${c.cmd_id} ${STATUS_LABEL[c.status]}. Acompanhe o ciclo abaixo.` })
      load()
    } catch (e) {
      setPendingMode(null)
      setMsg({ tone: 'critical', text: e instanceof Error ? e.message : String(e) })
    }
  }

  async function resend(cmdId: string) {
    try {
      await api.post(`/api/v1/commands/${cmdId}/reenviar`)
      setMsg({ tone: 'good', text: `Comando ${cmdId} reenviado com o mesmo cmd_id: o atuador deve responder o ack original sem executar de novo.` })
      window.setTimeout(load, 800)
    } catch (e) {
      setMsg({ tone: 'critical', text: e instanceof Error ? e.message : String(e) })
    }
  }

  async function saveDecision() {
    if (!draft) return
    try {
      const d = await api.put<Decision>('/api/v1/decision', {
        enabled: draft.enabled, limite_ambiente: draft.limite_ambiente, limite_alta: draft.limite_alta,
        limite_extrema: draft.limite_extrema, histerese: draft.histerese, confirmacao_s: draft.confirmacao_s,
      })
      setDecision(d); setDraft(d)
      setMsg({ tone: 'good', text: 'Regra salva no banco e aplicada.' })
    } catch (e) {
      setMsg({ tone: 'critical', text: e instanceof Error ? e.message : String(e) })
    }
  }

  async function testNotify() {
    try {
      await api.post('/api/v1/notifications/teste')
      setMsg({ tone: 'good', text: 'Notificação de teste enviada.' })
      load()
    } catch (e) {
      setMsg({ tone: 'critical', text: e instanceof Error ? e.message : String(e) })
    }
  }

  const modeTone = est?.modo === 'seguro' ? 'critical' : est?.modo === 'manual' ? 'warning' : 'good'

  return (
    <div className="stack">
      {msg && <div className={`banner ${msg.tone === 'good' ? 'ok' : 'warn'}`} role="status"><Status tone={msg.tone}>{msg.text}</Status></div>}

      <div className="grid g-3">
        <Panel title="Sensor de luz" sub="sensor01">
          <div className="big-value num">{sensor?.raw ?? '—'}</div>
          <p className="small muted">leitura bruta do LDR (ADC 0–4095)</p>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
            {sensor?.online === false ? <Status tone="critical">offline</Status> : sensor?.at ? <Status tone="good">online</Status> : <Status tone="neutral">sem dados</Status>}
            {sensor && sensor.sensor_ok === false && <Status tone="critical">falha: {sensor.falha}</Status>}
            {sensor?.hora_sync && <Status tone="good">hora NTP</Status>}
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>último contato {fmtDateTime(sensor?.at ?? null)} · seq {sensor?.seq ?? '—'}{sensor?.perdidas ? ` · ${sensor.perdidas} perdidas` : ''}</p>
        </Panel>

        <Panel title="Decisão do backend" sub="regra remota">
          <div style={{ fontSize: 22, margin: '6px 0' }}><SceneBadge cena={v1?.decided_scene} /></div>
          <p className="small muted">cena decidida com histerese de {decision?.histerese ?? '—'} e {decision?.confirmacao_s ?? '—'} s de confirmação</p>
          <p className="small" style={{ marginTop: 8 }}>{decision?.enabled ? 'A regra comanda o atuador em modo automático.' : 'Regra desligada: só comandos manuais.'}</p>
        </Panel>

        <Panel title="Sombra e LEDs" sub="atuador01">
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {act?.online === false ? <Status tone="critical">offline</Status> : <Status tone={modeTone}>modo {est?.modo ?? '—'}</Status>}
            {est?.modo === 'seguro' && est.motivo_seguro && <span className="small muted">({est.motivo_seguro})</span>}
          </div>
          <div style={{ fontSize: 20, margin: '10px 0' }}><SceneBadge cena={est?.cena} /></div>
          <div className="row" style={{ gap: 6 }}>
            {(est?.leds ?? [false, false, false, false]).map((on, i) => (
              <span key={i} className={`mini-led ${on ? 'on' : ''}`} title={`LED ${i + 1} ${on ? 'aceso' : 'apagado'}`}>LED {i + 1}</span>
            ))}
          </div>
          <p className="small" style={{ marginTop: 8 }}>Sombra <b>{est?.sombra ?? 'desconhecida'}</b>{est?.modo === 'manual' && est.manual_restante_s != null ? ` · manual por mais ${est.manual_restante_s} s` : ''}</p>
        </Panel>
      </div>

      <Panel title="Comandar a sombra" sub={can ? `logado como ${user.username} (admin)` : 'perfil operador: só visualização'}>
        {!can && <p className="note">Seu perfil é <b>operador</b>: você acompanha tudo, mas comandos e mudanças de regra exigem um usuário <b>admin</b>.</p>}
        <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="small muted">Modo:</span>
          <div className="mode-toggle" role="group" aria-label="Modo do atuador">
            <button className={`btn mode ${est?.modo === 'auto' ? 'active' : ''} ${pendingMode === 'auto' ? 'pending' : ''}`}
              aria-pressed={est?.modo === 'auto'} disabled={!can || est?.modo === 'seguro'}
              onClick={() => { setPendingMode('auto'); send({ acao: 'definir_modo', modo: 'auto' }, 'Modo automático') }}>
              Modo automático{pendingMode === 'auto' ? ' · aguardando…' : ''}
            </button>
            <button className={`btn mode ${est?.modo === 'manual' ? 'active' : ''} ${pendingMode === 'manual' ? 'pending' : ''}`}
              aria-pressed={est?.modo === 'manual'} disabled={!can || est?.modo === 'seguro'}
              onClick={() => { setPendingMode('manual'); send({ acao: 'definir_modo', modo: 'manual', duracao_s: duracao }, 'Modo manual') }}>
              Modo manual{pendingMode === 'manual' ? ' · aguardando…' : est?.modo === 'manual' && est.manual_restante_s != null ? ` · ${Math.ceil(est.manual_restante_s / 60)} min` : ''}
            </button>
          </div>
          <label className="small">manual por <select value={duracao} disabled={!can} onChange={(e) => setDuracao(Number(e.target.value))}>
            <option value={60}>1 min</option><option value={300}>5 min</option><option value={900}>15 min</option></select></label>
          {est?.modo === 'seguro' && <Status tone="critical">modo seguro: o atuador recusa comandos até a conexão voltar</Status>}
        </div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 12, alignItems: 'center' }}>
          <span className="small muted">Aplicar cena (no modo manual):</span>
          {SCENES.map((s) => (
            <button key={s} className={`btn scene-btn ${est?.cena === s ? 'active' : ''}`} aria-pressed={est?.cena === s} disabled={!can}
              onClick={() => send({ acao: 'aplicar', cena: s }, `Cena ${s}`)}>
              <SceneBadge cena={s} />{s === 'extrema' ? ' · fecha a sombra' : ''}
            </button>
          ))}
        </div>
        <p className="note">O modo e a cena destacados são os que o <b>atuador confirmou</b>. Em automático ele recusa cenas manuais (<code>modo_incompativel</code>); a recusa e o motivo aparecem no ciclo abaixo.</p>
      </Panel>

      <Panel title="Ciclo dos comandos" sub="enviado → recebido → executado → confirmado">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Comando</th><th>Origem</th><th>Ação</th><th>Ciclo</th><th>Situação</th><th>Latência</th><th></th></tr></thead>
            <tbody>
              {commands.length === 0 && <tr><td colSpan={7} className="muted">Nenhum comando ainda.</td></tr>}
              {commands.map((c) => (
                <tr key={c.cmd_id}>
                  <td className="mono small">{c.cmd_id}<br /><span className="muted">{fmtDateTime(c.sent_at)}</span></td>
                  <td className="small">{c.origem === 'auto' ? 'regra' : c.requested_by}</td>
                  <td className="small">{c.acao === 'aplicar' ? <SceneBadge cena={c.cena} /> : `modo ${c.modo}`}</td>
                  <td><Stepper c={c} /></td>
                  <td className="small"><Status tone={statusTone(c.status)}>{STATUS_LABEL[c.status] ?? c.status}</Status>
                    {c.motivo && <div className="muted">motivo: {c.motivo}</div>}
                    {c.retries > 0 && <div className="muted">retransmitido {c.retries}×</div>}
                    {c.duplicate_acks > 0 && <div className="muted">{c.duplicate_acks} ack(s) duplicado(s) ignorado(s)</div>}
                  </td>
                  <td className="num small">{c.latency_ms != null ? `${c.latency_ms} ms` : '—'}</td>
                  <td>{can && <button className="btn small" title="Teste de duplicidade (R10)" onClick={() => resend(c.cmd_id)}>Reenviar igual</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid g-2">
        <Panel title="Regra automática" sub={decision ? `alterada por ${decision.updated_by}` : ''}>
          {draft && (
            <div className="form-grid">
              <label className="field">Ambiente a partir de<input type="number" value={draft.limite_ambiente} disabled={!can} onChange={(e) => setDraft({ ...draft, limite_ambiente: Number(e.target.value) })} /></label>
              <label className="field">Alta a partir de<input type="number" value={draft.limite_alta} disabled={!can} onChange={(e) => setDraft({ ...draft, limite_alta: Number(e.target.value) })} /></label>
              <label className="field">Extrema a partir de (fecha a sombra)<input type="number" value={draft.limite_extrema} disabled={!can} onChange={(e) => setDraft({ ...draft, limite_extrema: Number(e.target.value) })} /></label>
              <label className="field">Histerese<input type="number" value={draft.histerese} disabled={!can} onChange={(e) => setDraft({ ...draft, histerese: Number(e.target.value) })} /></label>
              <label className="field">Confirmação (s)<input type="number" step="0.5" value={draft.confirmacao_s} disabled={!can} onChange={(e) => setDraft({ ...draft, confirmacao_s: Number(e.target.value) })} /></label>
              <label className="field">Regra ligada<select value={draft.enabled ? 'sim' : 'nao'} disabled={!can} onChange={(e) => setDraft({ ...draft, enabled: e.target.value === 'sim' })}><option value="sim">sim</option><option value="nao">não</option></select></label>
            </div>
          )}
          <button className="btn primary" style={{ marginTop: 12 }} disabled={!can} onClick={saveDecision}>Salvar regra</button>
        </Panel>

        <Panel title="Notificações no celular" sub={notif?.channels.length ? notif.channels.join(' · ') : 'nenhum canal configurado'}>
          <p className="small muted">Alertas críticos (sol extremo, sensor com falha, atuador em modo seguro, placa offline) saem também para o celular.</p>
          <ul className="small" style={{ paddingLeft: 18 }}>
            {(notif?.items ?? []).map((n) => (
              <li key={n.id}>{fmtDateTime(n.sent_at)} · {n.channel} · {n.ok ? 'entregue' : `falhou: ${n.error}`} — {n.message}</li>
            ))}
            {notif && notif.items.length === 0 && <li className="muted">nenhuma notificação enviada ainda</li>}
          </ul>
          <button className="btn" disabled={!can || !notif?.channels.length} onClick={testNotify}>Enviar notificação de teste</button>
        </Panel>
      </div>
    </div>
  )
}
