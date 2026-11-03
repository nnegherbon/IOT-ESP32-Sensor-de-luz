import { useMemo } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fmtDateTime, fmtDuration, fmtNum, fmtShort, fmtTime, tickFormatterFor } from '../format'
import { SCENE_ORDER, SCENE_RANGE, sceneColor, sceneIndex, sceneLabel } from '../scenes'
import type { CommandRow, ConfirmationRow, Range, SceneAnalysis, Series } from '../types'
import { Empty } from './ui'

const AXIS = { stroke: 'var(--border-strong)', tick: { fill: 'var(--text-muted)', fontSize: 11 } }
const THRESHOLDS = [
  { v: 150, label: 'ambiente' },
  { v: 400, label: 'alta' },
  { v: 1000, label: 'extrema' },
]

interface TTProps { active?: boolean; payload?: { payload: Record<string, number> }[] }

function LumTooltip({ active, payload, bucket }: TTProps & { bucket: number }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const single = p.n === 1
  return (
    <div className="chart-tooltip">
      <div className="tt-title">{fmtDateTime(new Date(p.t).toISOString())}</div>
      {single ? (
        <div className="tt-row"><span>Leitura</span><span>{fmtNum(p.avg)}</span></div>
      ) : (
        <>
          <div className="tt-row"><span>Média</span><span>{fmtNum(p.avg)}</span></div>
          <div className="tt-row"><span>Mín – máx</span><span>{fmtNum(p.min)} – {fmtNum(p.max)}</span></div>
          <div className="tt-row"><span>Leituras</span><span>{fmtNum(p.n)}</span></div>
          <div className="tt-row muted"><span>Intervalo</span><span>{fmtDuration(bucket)}</span></div>
        </>
      )}
      <div className="tt-row"><span>Cena (média)</span><span>{sceneLabel(classify(p.avg))}</span></div>
    </div>
  )
}

function classify(raw: number) {
  return raw < 150 ? 'escuro' : raw < 400 ? 'ambiente' : raw < 1000 ? 'alta' : 'extrema'
}

export function LuminosityChart({ series, range }: { series: Series | null; range: Range }) {
  const data = useMemo(
    () => (series?.points ?? []).map((p) => ({ ...p, t: new Date(p.t).getTime(), band: [p.min, p.max] })),
    [series],
  )
  if (!series) return <div className="empty">Carregando…</div>
  if (!data.length)
    return (
      <Empty title="Sem leituras brutas do LDR neste período">
        O firmware original publica apenas a cena (quando muda) e não envia o valor analógico. Aplique o patch
        opcional <code>firmware-patch/Sensor_de_luz_telemetria.ino</code> para habilitar este gráfico.
      </Empty>
    )
  const span = range.to.getTime() - range.from.getTime()
  const maxVal = Math.max(...data.map((d) => d.max))
  const yMax = Math.min(4095, Math.max(1200, Math.ceil((maxVal * 1.1) / 100) * 100))
  const showBand = series.bucket_s > 1 && data.some((d) => d.n > 1)
  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={data} margin={{ top: 8, right: 92, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="t" type="number" scale="time" domain={[range.from.getTime(), range.to.getTime()]}
          tickFormatter={tickFormatterFor(span)} {...AXIS} minTickGap={40} />
        <YAxis domain={[0, yMax]} {...AXIS} width={48} tickFormatter={(v) => fmtNum(v)} />
        {THRESHOLDS.filter((t) => t.v <= yMax).map((t) => (
          <ReferenceLine key={t.v} y={t.v} stroke="var(--text-muted)" strokeDasharray="3 4" strokeOpacity={0.6}
            label={{ value: `${t.label} ≥ ${t.v}`, position: 'right', fill: 'var(--text-muted)', fontSize: 10 }} />
        ))}
        {showBand && (
          <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.16} isAnimationActive={false}
            activeDot={false} name="mín–máx" />
        )}
        <Line dataKey="avg" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false}
          activeDot={{ r: 4, stroke: 'var(--surface-1)', strokeWidth: 2 }} name="leitura" />
        <Tooltip content={<LumTooltip bucket={series.bucket_s} />}
          cursor={{ stroke: 'var(--text-muted)', strokeDasharray: '2 3' }} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

export function SceneDistribution({ analysis }: { analysis: SceneAnalysis | null }) {
  if (!analysis) return <div className="empty">Carregando…</div>
  if (!analysis.covered_s) return <Empty title="Sem transições de cena no período" />
  const rows = SCENE_ORDER.map((k) => analysis.distribution.find((d) => d.cena === k) ?? { cena: k, duration_s: 0, count: 0, share: 0 })
  const extra = analysis.distribution.filter((d) => sceneIndex(d.cena) < 0 && d.duration_s > 0)
  return (
    <div role="table" aria-label="Tempo em cada cena">
      {[...rows, ...extra].reverse().map((d) => (
        <div className="dist-row" role="row" key={d.cena}>
          <span role="cell" className="row" style={{ gap: 6 }}>
            <span className="scene-dot" style={{ background: sceneColor(d.cena) }} />{sceneLabel(d.cena)}
          </span>
          <div className="dist-bar" role="cell" title={`${(d.share * 100).toFixed(1)}%`}>
            <div style={{ width: `${d.share * 100}%`, background: sceneColor(d.cena) }} />
          </div>
          <span role="cell" className="num small r" style={{ textAlign: 'right' }}>
            {(d.share * 100).toFixed(1)}% · {fmtDuration(d.duration_s)}
            <span className="muted"> · {d.count}×</span>
          </span>
        </div>
      ))}
      <p className="note">Tempo calculado entre transições publicadas pelo sensor (ele só publica quando a cena muda).
        Períodos com o sensor desligado não são distinguíveis sem o patch de presença.</p>
    </div>
  )
}

export function SceneStrip({ analysis, range }: { analysis: SceneAnalysis | null; range: Range }) {
  if (!analysis || !analysis.intervals.length) return null
  const start = range.from.getTime()
  const total = Math.max(1, Math.min(range.to.getTime(), Date.now()) - start)
  const first = new Date(analysis.intervals[0].start).getTime()
  return (
    <div>
      <div className="timeline-strip" role="img" aria-label="Linha do tempo das cenas">
        {first > start && <div style={{ width: `${((first - start) / total) * 100}%`, background: 'transparent' }} title="sem dados" />}
        {analysis.intervals.map((iv, i) => (
          <div key={i}
            style={{ width: `${(iv.duration_s * 1000 / total) * 100}%`, background: sceneColor(iv.cena) }}
            title={`${sceneLabel(iv.cena)} · ${fmtShort(iv.start)} → ${fmtShort(iv.end)} (${fmtDuration(iv.duration_s)})`} />
        ))}
      </div>
      <div className="row small muted" style={{ justifyContent: 'space-between', marginTop: 4 }}>
        <span className="num">{fmtShort(range.from)}</span>
        <span className="legend">
          {SCENE_ORDER.map((k) => (
            <span key={k}><span className="scene-dot" style={{ background: sceneColor(k) }} />{sceneLabel(k)} <span className="muted num">{SCENE_RANGE[k]}</span></span>
          ))}
        </span>
        <span className="num">{fmtShort(range.to)}</span>
      </div>
    </div>
  )
}

function StateTooltip({ active, payload }: TTProps) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload as unknown as { t: number; y: number; kind: string; cena: string; extra?: string }
  return (
    <div className="chart-tooltip">
      <div className="tt-title">{fmtTime(new Date(p.t))}</div>
      <div className="tt-row"><span>{p.kind}</span><span>{sceneLabel(p.cena)}</span></div>
      {p.extra && <div className="tt-row muted"><span>{p.extra}</span></div>}
    </div>
  )
}

/** Histórico de estado: cena comandada (linha em degrau) × confirmada (pontos). */
export function StateHistoryChart(props: { commands: CommandRow[]; confirmations: ConfirmationRow[]; range: Range }) {
  const { range } = props
  const cmd = useMemo(() => {
    const pts = props.commands
      .filter((c) => sceneIndex(c.cena) >= 0)
      .map((c) => ({
        t: new Date(c.received_at).getTime(), y: sceneIndex(c.cena), cena: c.cena, kind: 'Comandada (sensor)',
        extra: c.status === 'confirmado' ? `confirmada em ${c.latency_ms} ms` : c.status.replace('_', ' '),
      }))
    if (pts.length) {
      const end = Math.min(range.to.getTime(), Date.now())
      pts.push({ ...pts[pts.length - 1], t: end, extra: 'vigente' })
    }
    return pts
  }, [props.commands, range])
  const conf = useMemo(() => props.confirmations
    .filter((c) => sceneIndex(c.cena) >= 0)
    .map((c) => ({
      t: new Date(c.received_at).getTime(), y: sceneIndex(c.cena), cena: c.cena, kind: 'Confirmada (atuador)',
      extra: c.retained ? 'mensagem retida' : c.match_status === 'confirmou_comando' ? 'casou com o comando' : 'sem comando correspondente',
    })), [props.confirmations])

  if (!cmd.length && !conf.length) return <Empty title="Sem comandos ou confirmações no período" />
  const span = range.to.getTime() - range.from.getTime()
  return (
    <>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span><svg width="18" height="8"><path d="M0 6h7V2h11" fill="none" stroke="var(--series-1)" strokeWidth="2" /></svg>Comandada pelo sensor</span>
        <span><svg width="10" height="10"><circle cx="5" cy="5" r="4" fill="var(--series-2)" stroke="var(--surface-1)" strokeWidth="1.5" /></svg>Confirmada pelo atuador</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={[range.from.getTime(), range.to.getTime()]}
            tickFormatter={tickFormatterFor(span)} {...AXIS} minTickGap={40} allowDuplicatedCategory={false} />
          <YAxis dataKey="y" type="number" domain={[-0.4, 3.4]} ticks={[0, 1, 2, 3]} width={74} {...AXIS}
            tickFormatter={(v) => sceneLabel(SCENE_ORDER[v])} />
          <Line data={cmd} dataKey="y" type="stepAfter" stroke="var(--series-1)" strokeWidth={2} dot={false}
            isAnimationActive={false} activeDot={{ r: 4 }} />
          <Scatter data={conf} dataKey="y" fill="var(--series-2)" stroke="var(--surface-1)" strokeWidth={1.5}
            isAnimationActive={false} shape="circle" />
          <Tooltip content={<StateTooltip />} cursor={{ stroke: 'var(--text-muted)', strokeDasharray: '2 3' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </>
  )
}
