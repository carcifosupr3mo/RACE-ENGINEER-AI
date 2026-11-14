/** Access token of LAN mode: taken from the address (?token=...) and remembered by this browser, so the bare address works afterwards. */
export const tok = (): string | null => {
  const fromUrl = new URLSearchParams(location.search).get('token')
  try {
    if (fromUrl) { localStorage.setItem('re_token', fromUrl); return fromUrl }
    return localStorage.getItem('re_token')
  } catch { return fromUrl }
}
/** A message a non-technical person can act on (never a raw status line or a JSON dump). */
export function friendlyError(status: number, detail: unknown): string {
  if (typeof detail === 'string' && detail && detail !== 'forbidden') return detail     // backend messages are written for people, in Italian
  if (status === 403) return "Questo indirizzo non ha il permesso di usare l'app. Se usi un altro PC, apri l'indirizzo completo che trovi in Impostazioni → «Display in rete»."
  if (status === 404) return 'Non abbiamo trovato quello che cerchi. Aggiorna la pagina e riprova.'
  if (status === 422) return 'Qualcosa nei dati inseriti non è corretto. Controlla e riprova.'
  return `Qualcosa non ha funzionato (codice ${status}). Riprova tra qualche istante; se succede ancora, riavvia l'app.`
}
export const OFFLINE_MSG = "Non riesco a parlare con l'app. Controlla che sia ancora aperta e riprova."
export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const t = tok()
  const url = path + (t ? (path.includes('?') ? '&' : '?') + 'token=' + t : '')
  let r: Response
  try { r = await fetch(url, init) } catch { throw new Error(OFFLINE_MSG) }
  if (!r.ok) {
    let d: any = null
    try { d = await r.json() } catch { /* ignore */ }
    throw new Error(friendlyError(r.status, d?.detail))
  }
  return r.json()
}
export const wsUrl = () => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/live' + (tok() ? '?token=' + tok() : '')
