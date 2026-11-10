import { useMemo, useRef, useState } from 'react'
import { bounds, slicePoints } from './format'

/** Interactive track map drawn ONLY from measured positions of the reference lap (pos_x/pos_z) - no invented geometry.
 *  Pan (drag), zoom (wheel / pinch), tap a corner for its details, "segui" keeps the car centred. */
interface Props { map: any | null; pos: { x: number | null, z: number | null, lap_dist_m: number } | null; trail: number[][]; current: string | null; next: string | null
  selected: string | null; onSelect: (id: string | null) => void }

const ZCOL: Record<string, string> = { brake: 'var(--d-brake)', release: 'var(--d-release)', accel: 'var(--d-accel)' }

export default function TrackMap({ map, pos, trail, current, next, selected, onSelect }: Props) {
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 })
  const [follow, setFollow] = useState(false)
  const drag = useRef<{ x: number, y: number, tx: number, ty: number, cap: boolean } | null>(null)
  const pts: number[][] = map?.available ? map.points : trail
  const b = useMemo(() => bounds(pts.length ? pts : [[0, 0, 0], [1, 1, 1]]), [pts.length, map?.version])
  const W = Math.max(1, b.x1 - b.x0), H = Math.max(1, b.z1 - b.z0), pad = Math.max(W, H) * 0.08
  const vb = { x: b.x0 - pad, y: -(b.z1 + pad), w: W + 2 * pad, h: H + 2 * pad }
  const P = (x: number, z: number) => `${x},${-z}`
  const path = (a: number[][]) => a.map(p => P(p[0], p[1])).join(' ')
  const carC = pos && pos.x != null && pos.z != null ? [pos.x, pos.z] : null
  const k = view.k
  let cx = vb.x + vb.w / 2 - view.tx, cy = vb.y + vb.h / 2 - view.ty
  if (follow && carC) { cx = carC[0]; cy = -carC[1] }
  const w = vb.w / k, h = vb.h / k
  const viewBox = `${cx - w / 2} ${cy - h / 2} ${w} ${h}`
  const unit = Math.max(vb.w, vb.h) / 1000 / Math.sqrt(k)         // keeps strokes/labels readable at every zoom
  const zones: any[] = map?.available ? map.zones : []
  const onWheel = (e: React.WheelEvent) => setView(v => ({ ...v, k: Math.min(12, Math.max(1, v.k * (e.deltaY < 0 ? 1.2 : 1 / 1.2))) }))
  const down = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, cap: false } }   // capture only once it is a real drag, so a tap still reaches the corner
  const move = (e: React.PointerEvent) => {
    const d = drag.current; if (!d || follow) return
    const el = e.currentTarget as SVGSVGElement, r = el.getBoundingClientRect()
    if (!d.cap) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return
      d.cap = true; el.setPointerCapture?.(e.pointerId)
    }
    setView(v => ({ ...v, tx: d.tx + (e.clientX - d.x) * (w / r.width), ty: d.ty + (e.clientY - d.y) * (h / r.height) }))
  }
  const up = () => { drag.current = null }
  if (!pts.length) return <div className="d-map-empty" data-testid="map-empty">Sto costruendo la mappa dai dati reali di posizione: completa un giro.</div>
  return (
    <div className="d-map" data-testid="track-map-display">
      <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet" onWheel={onWheel} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
           onDoubleClick={() => { setView({ k: 1, tx: 0, ty: 0 }); setFollow(false) }} role="img" aria-label="Mappa del circuito">
        <polyline points={path(pts)} fill="none" stroke="var(--d-track)" strokeWidth={unit * 14} strokeLinecap="round" strokeLinejoin="round" />
        {zones.map((z, i) => <polyline key={i} data-zone={z.type} points={path(slicePoints(pts, z.from_m, z.to_m))} fill="none" stroke={ZCOL[z.type]}
                                       strokeWidth={unit * (z.type === 'brake' ? 10 : 7)} strokeLinecap="round" opacity={z.type === 'release' ? 0.9 : 0.85} />)}
        {map?.available && trail.length > 1 && <polyline points={path(trail)} fill="none" stroke="var(--d-trail)" strokeWidth={unit * 3} strokeLinecap="round" />}
        {map?.available && map.corners.map((c: any) => c.apex_xz && (
          <g key={c.id} transform={`translate(${c.apex_xz[0]},${-c.apex_xz[1]})`} onClick={e => { e.stopPropagation(); onSelect(selected === c.id ? null : c.id) }} style={{ cursor: 'pointer' }}
             data-testid={'corner-' + c.id}>
            <circle r={unit * (c.id === current ? 22 : 17)} className={'d-corner' + (c.id === current ? ' cur' : c.id === next ? ' nxt' : '') + (c.id === selected ? ' sel' : '')} />
            <text y={unit * 6} fontSize={unit * 17} textAnchor="middle" className="d-corner-t">{c.name || c.id.replace('P', '')}</text>
          </g>))}
        {carC && <circle cx={carC[0]} cy={-carC[1]} r={unit * 15} className="d-car" data-testid="car-marker" />}
      </svg>
      <div className="d-map-tools">
        <button onClick={() => setView(v => ({ ...v, k: Math.min(12, v.k * 1.4) }))} aria-label="Zoom +">+</button>
        <button onClick={() => setView(v => ({ ...v, k: Math.max(1, v.k / 1.4) }))} aria-label="Zoom −">−</button>
        <button className={follow ? 'on' : ''} onClick={() => setFollow(f => !f)} data-testid="map-follow">segui</button>
        <button onClick={() => { setView({ k: 1, tx: 0, ty: 0 }); setFollow(false) }}>reset</button>
      </div>
      <div className="d-legend"><i style={{ background: ZCOL.brake }} />frenata <i style={{ background: ZCOL.release }} />rilascio <i style={{ background: ZCOL.accel }} />accelerazione</div>
      {map?.synthetic && <div className="d-map-syn">mappa SINTETICA</div>}
    </div>)
}
