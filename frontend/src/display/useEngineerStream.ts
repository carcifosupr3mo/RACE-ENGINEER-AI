import { useEffect, useRef, useState } from 'react'
import { api, tok, wsUrl } from '../lib/api'

/** One shared stream for the Driving Display: the SAME /ws/live socket the dashboard uses (field `engineer`).
 *  Auto-reconnects with back-off, marks the data stale when nothing arrives, never invents values. */
export interface Stream {
  connected: boolean
  stale: boolean
  everConnected: boolean
  /** the PC refuses this browser: no / wrong access token (LAN mode) */
  authError: 'missing' | 'wrong' | null
  engineer: any | null
  sample: any | null
  status: any | null
  map: any | null
  trail: number[][]
  lastEvents: any[]
  ageMs: number
}

export const STALE_MS = 2500

export function nextBackoff(prev: number): number {
  return Math.min(5000, Math.round(prev * 1.6))
}

export function useEngineerStream(): Stream {
  const [s, setS] = useState<Stream>({ connected: false, stale: true, everConnected: false, authError: null, engineer: null, sample: null, status: null, map: null, trail: [], lastEvents: [], ageMs: Infinity })
  const last = useRef(0)
  const mapVer = useRef('')
  const lap = useRef<number | null>(null)
  const trail = useRef<number[][]>([])

  useEffect(() => {
    let ws: WebSocket | null = null, timer: any, alive = true, back = 800
    const loadMap = (ver: string) => {
      if (ver === mapVer.current) return
      mapVer.current = ver
      api('/api/engineer/map').then(m => alive && setS(p => ({ ...p, map: m }))).catch(() => { mapVer.current = '' })
    }
    const open = () => {
      if (!alive) return
      try { ws = new WebSocket(wsUrl()) } catch { timer = setTimeout(open, back); back = nextBackoff(back); return }
      ws.onopen = () => {
        back = 800
        api('/api/engineer/state?full=1').then(f => {          // seed: map + the trail of the lap in progress (real positions)
          if (!alive) return
          trail.current = f.trail || []
          mapVer.current = f.map_version
          setS(p => ({ ...p, map: f.map, trail: trail.current.slice() }))
        }).catch(() => {})
      }
      ws.onmessage = e => {
        let m: any
        try { m = JSON.parse(e.data) } catch { return }
        last.current = Date.now()
        const en = m.engineer
        if (en?.lap?.number !== lap.current) { lap.current = en?.lap?.number ?? null; trail.current = [] }
        const p = en?.position
        if (p && p.x != null && p.z != null) {
          const t = trail.current
          if (!t.length || Math.abs(p.lap_dist_m - t[t.length - 1][2]) >= 3) { t.push([p.x, p.z, p.lap_dist_m]); if (t.length > 6000) t.shift() }
        }
        if (en?.map_version) loadMap(en.map_version)
        setS(prev => ({ ...prev, connected: true, stale: false, everConnected: true, authError: null, engineer: en ?? null, sample: m.sample, status: m.status,
                        trail: trail.current, lastEvents: m.events?.length ? m.events : prev.lastEvents, ageMs: 0 }))
      }
      ws.onclose = () => {
        setS(prev => ({ ...prev, connected: false, stale: true }))
        if (!last.current) {                                   // never got data: is the PC refusing us (access token)?
          fetch('/api/health' + (tok() ? '?token=' + encodeURIComponent(tok()!) : '')).then(r => {
            if (alive) setS(p => ({ ...p, authError: r.status === 403 ? (tok() ? 'wrong' : 'missing') : null }))
          }).catch(() => {})
        }
        if (alive) { timer = setTimeout(open, back); back = nextBackoff(back) }
      }
      ws.onerror = () => { try { ws?.close() } catch { /* ignore */ } }
    }
    open()
    const tick = setInterval(() => {
      const age = last.current ? Date.now() - last.current : Infinity
      setS(prev => (prev.stale === age > STALE_MS && Math.abs((prev.ageMs === Infinity ? 1e9 : prev.ageMs) - age) < 400) ? prev : { ...prev, stale: age > STALE_MS, ageMs: age })
    }, 500)
    return () => { alive = false; clearTimeout(timer); clearInterval(tick); ws?.close() }
  }, [])
  return s
}
