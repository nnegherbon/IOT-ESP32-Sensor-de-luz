const dtf = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
})
const tf = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const dshort = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
const nf = new Intl.NumberFormat('pt-BR')
const nf1 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

export const fmtDateTime = (iso: string | null | undefined) => (iso ? dtf.format(new Date(iso)) : '—')
export const fmtTime = (iso: string | Date) => tf.format(typeof iso === 'string' ? new Date(iso) : iso)
export const fmtShort = (iso: string | Date) => dshort.format(typeof iso === 'string' ? new Date(iso) : iso)
export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? '—' : nf.format(n))
export const fmtNum1 = (n: number | null | undefined) => (n === null || n === undefined ? '—' : nf1.format(n))

export function fmtDuration(seconds: number): string {
  if (!isFinite(seconds)) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}min ${s % 60 ? `${s % 60}s` : ''}`.trim()
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ${m % 60 ? `${m % 60}min` : ''}`.trim()
  const d = Math.floor(h / 24)
  return `${d}d ${h % 24 ? `${h % 24}h` : ''}`.trim()
}

export function fmtAgo(iso: string | null | undefined, now: number): string {
  if (!iso) return 'nunca'
  const diff = Math.max(0, (now - new Date(iso).getTime()) / 1000)
  if (diff < 2) return 'agora'
  return `há ${fmtDuration(diff)}`
}

/** Para exibir eixo de tempo coerente com o tamanho do período. */
export function tickFormatterFor(spanMs: number) {
  return (v: number) => (spanMs > 36 * 3600 * 1000 ? dshort.format(new Date(v)) : tf.format(new Date(v)))
}

export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
