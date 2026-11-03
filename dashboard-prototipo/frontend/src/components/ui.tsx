import type { ReactNode } from 'react'
import { sceneColor, sceneLabel } from '../scenes'

export function Panel(props: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${props.className ?? ''}`}>
      {(props.title || props.right) && (
        <div className="panel-head">
          {props.title && <h2 className="panel-title">{props.title}</h2>}
          {props.sub && <span className="panel-sub">{props.sub}</span>}
          {props.right && <><span className="spacer" />{props.right}</>}
        </div>
      )}
      {props.children}
    </section>
  )
}

export type Tone = 'good' | 'warning' | 'critical' | 'neutral' | 'demo'

const paths: Record<Tone, ReactNode> = {
  good: <path d="M4 8.2l2.6 2.6L12 5.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />,
  warning: <><path d="M8 2.5l6 10.5H2z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M8 6.5v3M8 11.3v.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></>,
  critical: <><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></>,
  neutral: <circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.5 2" />,
  demo: <><rect x="2.5" y="2.5" width="11" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M6 5.5l4 2.5-4 2.5z" fill="currentColor" /></>,
}

export function StatusIcon({ tone, size = 16 }: { tone: Tone; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">{paths[tone]}</svg>
}

/** Status sempre com ícone + rótulo (nunca só cor). */
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`status ${tone}`}><StatusIcon tone={tone} />{children}</span>
}

export function SceneBadge({ cena }: { cena: string | null | undefined }) {
  return (
    <span className="scene-badge">
      <span className="scene-dot" style={{ background: sceneColor(cena) }} />
      {sceneLabel(cena)}
    </span>
  )
}

export function SceneDot({ cena }: { cena: string | null | undefined }) {
  return <span className="scene-dot" style={{ background: sceneColor(cena), display: 'inline-block' }} />
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><div><b>{title}</b>{children}</div></div>
}

export function Pager(props: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  const { total, limit, offset, onChange } = props
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))
  return (
    <div className="pager">
      <span className="num">{total === 0 ? '0 registros' : `${offset + 1}–${Math.min(offset + limit, total)} de ${total.toLocaleString('pt-BR')}`}</span>
      <span className="spacer" />
      <button className="btn small" disabled={offset === 0} onClick={() => onChange(0)}>«</button>
      <button className="btn small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Anterior</button>
      <span className="num">{page}/{pages}</span>
      <button className="btn small" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Próxima</button>
      <button className="btn small" disabled={offset + limit >= total} onClick={() => onChange((pages - 1) * limit)}>»</button>
    </div>
  )
}

export function Switch(props: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className="switch" title={props.label}>
      <input type="checkbox" checked={props.checked} disabled={props.disabled} onChange={(e) => props.onChange(e.target.checked)} aria-label={props.label} />
      <span />
    </label>
  )
}

export function Icon({ name }: { name: 'scene' | 'check' | 'plug' | 'bell' | 'bug' }) {
  const d: Record<string, ReactNode> = {
    scene: <path d="M8 2v2M8 12v2M2 8h2M12 8h2M3.8 3.8l1.4 1.4M10.8 10.8l1.4 1.4M3.8 12.2l1.4-1.4M10.8 5.2l1.4-1.4M8 5.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />,
    check: <path d="M3.5 8.3l2.8 2.8L12.5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />,
    plug: <path d="M6 2v3M10 2v3M4.5 5h7v2.5a3.5 3.5 0 01-7 0zM8 11v3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />,
    bell: <path d="M4 11V7.5a4 4 0 018 0V11l1 1.5H3zM6.5 14h3" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />,
    bug: <path d="M8 2.5l5.5 10h-11zM8 6.5v3M8 11.2v.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />,
  }
  return <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">{d[name]}</svg>
}
