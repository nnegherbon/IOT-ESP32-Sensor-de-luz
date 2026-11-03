import { useEffect, useState, type ReactNode } from 'react'
import { api, exportUrl, rangeParams } from '../api'
import { fmtDateTime, fmtNum } from '../format'
import { sceneLabel } from '../scenes'
import type { Page, Range } from '../types'
import { describeEvent } from './events'
import { Empty, Pager, Panel, SceneBadge } from './ui'

type Row = Record<string, unknown>
interface Col { h: string; r?: boolean; cell: (row: Row) => ReactNode }

const s = (v: unknown) => (v === null || v === undefined ? '—' : String(v))
const yes = (v: unknown) => (v ? 'sim' : 'não')
const led = (v: unknown) => (v ? '●' : '○')

const STATUS_LABEL: Record<string, string> = {
  aguardando: 'aguardando', confirmado: 'confirmado', sem_confirmacao: 'sem confirmação', substituido: 'substituído',
}

const DATASETS: { key: string; label: string; endpoint: string; filter?: { param: string; options: [string, string][] }; cols: Col[] }[] = [
  {
    key: 'readings', label: 'Leituras do LDR', endpoint: '/api/readings',
    cols: [
      { h: 'ID', cell: (r) => s(r.id) },
      { h: 'Recebida em', cell: (r) => fmtDateTime(r.received_at as string) },
      { h: 'Leitura (ADC)', r: true, cell: (r) => <span className="num">{fmtNum(r.raw as number)}</span> },
      { h: 'Cena (pelos limites)', cell: (r) => <SceneBadge cena={r.cena_computed as string} /> },
      { h: 'Cena reportada', cell: (r) => sceneLabel(r.cena_reported as string) },
      { h: 'Uptime (ms)', r: true, cell: (r) => <span className="num">{fmtNum(r.uptime_ms as number)}</span> },
    ],
  },
  {
    key: 'commands', label: 'Transições de cena', endpoint: '/api/commands',
    filter: { param: 'status', options: [['', 'todos'], ['confirmado', 'confirmados'], ['aguardando', 'aguardando'], ['sem_confirmacao', 'sem confirmação'], ['substituido', 'substituídos']] },
    cols: [
      { h: 'ID', cell: (r) => s(r.id) },
      { h: 'Recebido em', cell: (r) => fmtDateTime(r.received_at as string) },
      { h: 'Anterior', cell: (r) => (r.previous_cena ? <SceneBadge cena={r.previous_cena as string} /> : '—') },
      { h: 'Nova cena', cell: (r) => <SceneBadge cena={r.cena as string} /> },
      { h: 'Status', cell: (r) => STATUS_LABEL[r.status as string] ?? s(r.status) },
      { h: 'Confirmado em', cell: (r) => fmtDateTime(r.confirmed_at as string) },
      { h: 'Latência', r: true, cell: (r) => <span className="num">{r.latency_ms != null ? `${r.latency_ms} ms` : '—'}</span> },
    ],
  },
  {
    key: 'confirmations', label: 'Confirmações do atuador', endpoint: '/api/confirmations',
    cols: [
      { h: 'ID', cell: (r) => s(r.id) },
      { h: 'Recebida em', cell: (r) => fmtDateTime(r.received_at as string) },
      { h: 'Dispositivo', cell: (r) => <code>{s(r.device)}</code> },
      { h: 'Estado', cell: (r) => <code>{s(r.estado)}</code> },
      { h: 'LEDs 1·2·3·4', cell: (r) => <span className="num" aria-label="LEDs">{led(r.led1)} {led(r.led2)} {led(r.led3)} {led(r.led4)}</span> },
      { h: 'Retida', cell: (r) => yes(r.retained) },
      { h: 'Correspondência', cell: (r) => s(r.match_status).replaceAll('_', ' ') },
      { h: 'Comando', r: true, cell: (r) => s(r.command_id) },
    ],
  },
  {
    key: 'connectivity', label: 'Conectividade', endpoint: '/api/connectivity',
    filter: { param: 'component', options: [['', 'todos'], ['broker', 'broker'], ['sensor', 'sensor'], ['atuador', 'atuador']] },
    cols: [
      { h: 'Quando', cell: (r) => fmtDateTime(r.occurred_at as string) },
      { h: 'Componente', cell: (r) => s(r.component) },
      { h: 'Evento', cell: (r) => s(r.event).replaceAll('_', ' ') },
      { h: 'Detalhes', cell: (r) => <span className="payload mono small">{r.detail ? JSON.stringify(r.detail) : '—'}</span> },
    ],
  },
  {
    key: 'messages', label: 'Mensagens MQTT', endpoint: '/api/messages',
    filter: { param: 'parse_status', options: [['', 'todas'], ['ok', 'válidas'], ['invalido', 'inválidas'], ['nao_tratado', 'não tratadas'], ['erro_processamento', 'erros']] },
    cols: [
      { h: 'ID', cell: (r) => s(r.id) },
      { h: 'Recebida em', cell: (r) => fmtDateTime(r.received_at as string) },
      { h: 'Tópico', cell: (r) => <code className="small">{s(r.topic)}</code> },
      { h: 'Origem', cell: (r) => s(r.origin) },
      { h: 'QoS', r: true, cell: (r) => s(r.qos) },
      { h: 'Retida', cell: (r) => yes(r.retained) },
      { h: 'Status', cell: (r) => (r.parse_status === 'ok' ? 'ok' : <span className="error-text">{s(r.parse_status).replaceAll('_', ' ')}{r.error_reason ? `: ${r.error_reason}` : ''}</span>) },
      { h: 'Payload', cell: (r) => <div className="payload">{s(r.payload)}</div> },
    ],
  },
  {
    key: 'events', label: 'Linha do tempo', endpoint: '/api/events',
    filter: { param: 'category', options: [['', 'todos'], ['transicao_cena', 'transições'], ['confirmacao', 'confirmações'], ['conectividade', 'conectividade'], ['alerta', 'alertas'], ['mensagem_invalida', 'inválidas']] },
    cols: [
      { h: 'Quando', cell: (r) => fmtDateTime(r.occurred_at as string) },
      { h: 'Categoria', cell: (r) => s(r.category).replaceAll('_', ' ') },
      { h: 'Descrição', cell: (r) => { const d = describeEvent(r as never); return <><div className="row" style={{ gap: 5 }}>{d.title}</div>{d.sub && <div className="small muted">{d.sub}</div>}</> } },
    ],
  },
]

const PAGE = 50

export function History({ range, refreshKey, onRefresh }: { range: Range; refreshKey: number; onRefresh: () => void }) {
  const [key, setKey] = useState('commands')
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState('')
  const [data, setData] = useState<Page<Row> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ds = DATASETS.find((d) => d.key === key)!

  useEffect(() => { setOffset(0); setFilter('') }, [key])
  useEffect(() => { setOffset(0) }, [range, filter])

  useEffect(() => {
    let cancel = false
    const params = { ...rangeParams(range), limit: PAGE, offset, ...(ds.filter && filter ? { [ds.filter.param]: filter } : {}) }
    api.get<Page<Row>>(ds.endpoint, params)
      .then((d) => { if (!cancel) { setData(d); setError(null) } })
      .catch((e) => !cancel && setError(String(e.message ?? e)))
    return () => { cancel = true }
  }, [ds, range, offset, filter, refreshKey])

  return (
    <div className="stack">
      <Panel title="Histórico persistido"
        right={
          <div className="row">
            <button className="btn small" onClick={onRefresh}>Atualizar</button>
            <span className="small muted">Exportar período:</span>
            <a className="btn small" href={exportUrl(key, 'csv', range)}>CSV</a>
            <a className="btn small" href={exportUrl(key, 'json', range)}>JSON</a>
          </div>
        }>
        <div className="filterbar">
          <div className="chips" role="group" aria-label="Conjunto de dados">
            {DATASETS.map((d) => (
              <button key={d.key} className="chip" aria-pressed={d.key === key} onClick={() => setKey(d.key)}>{d.label}</button>
            ))}
          </div>
          {ds.filter && (
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtro">
              {ds.filter.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </div>
        {error && <div className="banner warn">{error}</div>}
        {data && data.items.length === 0 ? (
          <Empty title="Nenhum registro no período">
            {key === 'readings' && 'O firmware original não publica a leitura bruta; veja o patch opcional na aba Sistema.'}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>{ds.cols.map((c) => <th key={c.h} className={c.r ? 'r' : ''}>{c.h}</th>)}</tr></thead>
              <tbody>
                {data?.items.map((row, i) => (
                  <tr key={String(row.id ?? `${row.occurred_at}-${row.ref_id}-${i}`)}>
                    {ds.cols.map((c) => <td key={c.h} className={c.r ? 'r' : ''}>{c.cell(row)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager total={data.total} limit={PAGE} offset={offset} onChange={setOffset} />}
      </Panel>
    </div>
  )
}
