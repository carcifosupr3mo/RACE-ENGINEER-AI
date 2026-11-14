import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export type Conn = { state: 'ok' | 'waiting' | 'problem' | 'not_supported'; label: string; detail: string }
export type Sim = {
  id: string; name: string; short: string; color: string; status: 'supported' | 'planned' | 'evaluating'; status_label: string
  description: string; how: string; connection: Conn | null; selectable: boolean; steps: string[]; tech: Record<string, string>
}
export type SimsState = { selected: string | null; first_run: boolean; sims: Sim[]; connection: Conn | null }

type Ctx = { data: SimsState | null; error: string; choose: (id: string) => Promise<void>; refresh: () => void; current: Sim | null }
const C = createContext<Ctx>({ data: null, error: '', choose: async () => {}, refresh: () => {}, current: null })
export const useSims = () => useContext(C)

/** Loads the simulator list + the saved choice once, then keeps the connection state fresh. The choice itself lives in the app's database (not in the browser). */
export function SimsProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<SimsState | null>(null)
  const [error, setError] = useState('')
  const refresh = useCallback(() => { api('/api/sims').then(d => { setData(d); setError('') }).catch(e => setError(e.message)) }, [])
  useEffect(() => { refresh(); const t = setInterval(refresh, 4000); return () => clearInterval(t) }, [refresh])
  const choose = useCallback(async (id: string) => {
    try { setData(await api('/api/sims/selected', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id }) })); setError('') }
    catch (e: any) { setError(e.message) }
  }, [])
  const current = data?.sims.find(s => s.id === data.selected) ?? null
  return <C.Provider value={{ data, error, choose, refresh, current }}>{children}</C.Provider>
}

/** Neutral monogram badge: official game logos are trademarks and are not bundled. */
export function SimBadge({ sim, size = 56 }: { sim: Pick<Sim, 'short' | 'color' | 'name'>; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" role="img" aria-label={sim.name} className="badge">
      <rect width="56" height="56" rx="12" fill={sim.color} />
      <path d="M0 40 L56 30 L56 56 L0 56Z" fill="rgba(0,0,0,.22)" />
      <text x="28" y="33" textAnchor="middle" fontSize={sim.short.length > 3 ? 15 : 19} fontWeight="700" fill="#fff" fontFamily="Segoe UI, system-ui, sans-serif">{sim.short}</text>
    </svg>)
}
