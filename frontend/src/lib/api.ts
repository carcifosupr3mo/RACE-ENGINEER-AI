/** Access token of LAN mode: taken from the address (?token=...) and remembered by this browser, so the bare address works afterwards. */
export const tok = (): string | null => {
  const fromUrl = new URLSearchParams(location.search).get('token')
  try {
    if (fromUrl) { localStorage.setItem('re_token', fromUrl); return fromUrl }
    return localStorage.getItem('re_token')
  } catch { return fromUrl }
}
export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const t = tok()
  const url = path + (t ? (path.includes('?') ? '&' : '?') + 'token=' + t : '')
  const r = await fetch(url, init)
  if (!r.ok) {
    let d: any = null
    try { d = await r.json() } catch { /* ignore */ }
    throw new Error(typeof d?.detail === 'string' ? d.detail : JSON.stringify(d?.detail ?? r.statusText))
  }
  return r.json()
}
export const wsUrl = () => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/live' + (tok() ? '?token=' + tok() : '')
