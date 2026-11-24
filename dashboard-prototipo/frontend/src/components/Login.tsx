import { useState } from 'react'
import { api, setToken } from '../api'

export interface SessionUser {
  username: string
  role: 'admin' | 'operador'
  can_command: boolean
}

export function Login({ onLogin }: { onLogin: (u: SessionUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<{ token: string; user: SessionUser }>('/api/auth/login', { username, password })
      setToken(r.token)
      onLogin(r.user)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="panel login" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 18 }}>
          <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#21211f" /><circle cx="16" cy="16" r="5.5" fill="#f2c14e" /><g stroke="#e8a93f" strokeWidth="2.2" strokeLinecap="round"><path d="M16 4.5v3M16 24.5v3M4.5 16h3M24.5 16h3M8 8l2 2M22 22l2 2M8 24l2-2M22 10l2-2" /></g></svg>
          <div><h1>Luz Ambiente</h1><small>Proteção solar automática para plantas sensíveis</small></div>
        </div>
        <label className="field">Usuário
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="field">Senha
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="error-text" role="alert">{error}</p>}
        <button className="btn primary" type="submit" disabled={busy || !username || !password}>{busy ? 'Entrando…' : 'Entrar'}</button>
        <p className="note">Perfil <b>admin</b> comanda a sombra e altera a regra. Perfil <b>operador</b> só acompanha.</p>
      </form>
    </div>
  )
}
