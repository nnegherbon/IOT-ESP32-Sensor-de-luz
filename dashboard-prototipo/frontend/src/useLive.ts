import { useEffect, useRef, useState } from 'react'
import { api, wsUrl } from './api'
import type { LiveState } from './types'

export type WsStatus = 'conectando' | 'aberto' | 'fechado'

export interface LiveEvent {
  type: string
  data: unknown
  receivedAt: number
}

/**
 * Mantém o estado ao vivo via WebSocket, com reconexão automática.
 * `version` incrementa a cada evento de dados para que gráficos e tabelas
 * possam se atualizar (com debounce) sem polling.
 */
export function useLive() {
  const [state, setState] = useState<LiveState | null>(null)
  const [wsStatus, setWsStatus] = useState<WsStatus>('conectando')
  const [version, setVersion] = useState(0)
  const [lastEvent, setLastEvent] = useState<LiveEvent | null>(null)
  const retry = useRef(0)

  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let timer: number | undefined
    let ping: number | undefined

    const connect = () => {
      setWsStatus('conectando')
      ws = new WebSocket(wsUrl())
      ws.onopen = () => {
        retry.current = 0
        setWsStatus('aberto')
        ping = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25000)
      }
      ws.onmessage = (ev) => {
        let msg: { type: string; data: unknown }
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        if (msg.type === 'pong') return
        if (msg.type === 'state') {
          setState(msg.data as LiveState)
          return
        }
        setLastEvent({ ...msg, receivedAt: Date.now() })
        setVersion((v) => v + 1)
      }
      ws.onclose = () => {
        window.clearInterval(ping)
        setWsStatus('fechado')
        if (closed) return
        const delay = Math.min(15000, 500 * 2 ** retry.current++)
        timer = window.setTimeout(connect, delay)
      }
      ws.onerror = () => ws?.close()
    }

    // estado inicial via HTTP (útil se o WS demorar)
    api.get<LiveState>('/api/state').then((s) => setState((cur) => cur ?? s)).catch(() => {})
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      window.clearInterval(ping)
      ws?.close()
    }
  }, [])

  return { state, wsStatus, version, lastEvent }
}

/** Relógio que avança a cada `ms` para atualizar textos "há X s". */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [ms])
  return now
}

/** Retorna `value` somente após `ms` sem mudanças (no máximo uma vez a cada `ms`). */
export function useThrottled<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  const last = useRef(0)
  useEffect(() => {
    const wait = Math.max(0, last.current + ms - Date.now())
    const id = window.setTimeout(() => {
      last.current = Date.now()
      setV(value)
    }, wait)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}
