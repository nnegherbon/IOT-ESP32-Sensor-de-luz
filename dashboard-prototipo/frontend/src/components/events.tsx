import type { ReactNode } from 'react'
import { fmtDateTime, fmtTime } from '../format'
import { sceneLabel } from '../scenes'
import type { EventRow } from '../types'
import { Icon, SceneDot } from './ui'

const CONN_LABEL: Record<string, string> = {
  conectado: 'Backend conectado ao broker',
  desconectado: 'Backend desconectado do broker',
  online: 'anunciou online',
  offline: 'anunciou offline (LWT)',
  falha_confirmacao: 'não confirmou o comando no prazo',
  silencio: 'sem mensagens além do limite',
  retomado: 'voltou a enviar mensagens',
}

const CMD_STATUS: Record<string, string> = {
  aguardando: 'aguardando confirmação', confirmado: 'confirmado', sem_confirmacao: 'sem confirmação', substituido: 'substituído',
}

const MATCH_LABEL: Record<string, string> = {
  confirmou_comando: 'confirmou o comando',
  sem_comando_correspondente: 'sem comando correspondente',
  retido_inicial: 'estado retido no broker (horário real desconhecido)',
}

export function describeEvent(e: EventRow): { icon: Parameters<typeof Icon>[0]['name']; title: ReactNode; sub?: string } {
  const d = e.detail as Record<string, unknown>
  switch (e.category) {
    case 'transicao_cena':
      return {
        icon: 'scene',
        title: <>Cena <SceneDot cena={d.anterior as string} /> {sceneLabel(d.anterior as string)} → <SceneDot cena={d.cena as string} /> <b>{sceneLabel(d.cena as string)}</b></>,
        sub: `Sensor · ${CMD_STATUS[d.status as string] ?? String(d.status)}${d.latencia_ms != null ? ` · ${d.latencia_ms} ms até confirmar` : ''}${d.conhecida === false ? ' · cena desconhecida pelo firmware' : ''}`,
      }
    case 'confirmacao': {
      const leds = (d.leds as boolean[]) ?? []
      const on = leds.map((v, i) => (v ? `LED ${i + 1}` : null)).filter(Boolean)
      return {
        icon: 'check',
        title: <>Atuador executou <SceneDot cena={d.cena as string} /> <b>{sceneLabel(d.cena as string)}</b></>,
        sub: `${MATCH_LABEL[d.correspondencia as string] ?? d.correspondencia} · acesos: ${on.length ? on.join(', ') : 'nenhum'}`,
      }
    }
    case 'conectividade': {
      const comp = d.componente as string
      const ev = d.evento as string
      const who = comp === 'broker' ? '' : comp === 'sensor' ? 'Sensor ' : 'Atuador '
      return { icon: 'plug', title: <>{who}{CONN_LABEL[ev] ?? ev}</>, sub: d.erro ? String(d.erro) : d.cena ? `cena ${sceneLabel(d.cena as string)}` : undefined }
    }
    case 'alerta':
      return { icon: 'bell', title: <>{String(d.mensagem)}</>, sub: `Alerta ${d.severidade} · ${d.status === 'aberto' ? 'aberto' : `encerrado ${d.encerrado_em ? fmtTime(d.encerrado_em as string) : ''}`}` }
    case 'mensagem_invalida':
      return { icon: 'bug', title: <>Mensagem inválida em <code>{String(d.topico).replace('iot/luzambiente/', '…/')}</code></>, sub: `${d.motivo} · ${d.payload ?? ''}` }
  }
}

export function EventList({ events }: { events: EventRow[] }) {
  return (
    <ul className="events">
      {events.map((e) => {
        const x = describeEvent(e)
        return (
          <li key={`${e.category}-${e.ref_id}`}>
            <span className="t" title={fmtDateTime(e.occurred_at)}>{fmtTime(e.occurred_at)}</span>
            <span className="ico"><Icon name={x.icon} /></span>
            <span>
              <span className="row" style={{ gap: 5 }}>{x.title}</span>
              {x.sub && <div className="sub">{x.sub}</div>}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
