import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import SessionPicker from './SessionPicker'

const f = (x: any, d = 2) => (x == null ? '–' : Number(x).toFixed(d))

export default function TyreFuel({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [fuel, setFuel] = useState<any>(null)
  const [tyre, setTyre] = useState<any>(null)
  const [target, setTarget] = useState(20)
  const [margin, setMargin] = useState(0.5)
  const [err, setErr] = useState('')
  useEffect(() => {
    setFuel(null); setTyre(null); setErr('')
    if (!sessionId) return
    api(`/api/sessions/${sessionId}/fuel?target_laps=${target}&margin_laps=${margin}`).then(setFuel).catch(e => setErr(e.message))
    api(`/api/sessions/${sessionId}/tyres`).then(setTyre).catch(e => setErr(e.message))
  }, [sessionId, target, margin])
  return (
    <section className="panel" data-testid="tyrefuel">
      <h2>Tyre &amp; Fuel</h2>
      <div className="toolbar"><SessionPicker value={sessionId} onChange={onPick} />
        <label className="inl">Giri obiettivo <input type="number" min={1} value={target} onChange={e => setTarget(+e.target.value)} style={{ width: 70 }} /></label>
        <label className="inl">Margine (giri) <input type="number" step={0.1} min={0} value={margin} onChange={e => setMargin(+e.target.value)} style={{ width: 70 }} /> <small className="mut">manuale</small></label></div>
      {err && <p className="bad">{err}</p>}
      {fuel && (fuel.available ? <div data-testid="fuel">
        <h3>Carburante</h3>
        {fuel.mean_l_per_lap ? <>
          <div className="row"><span>Consumo medio</span><span className="mono">{f(fuel.mean_l_per_lap, 3)} L/giro (±{f(fuel.std_l_per_lap, 3)}, n={fuel.n})</span></div>
          <div className="row"><span>Carburante attuale / giri residui</span><span className="mono">{f(fuel.current_fuel_l, 1)} L / {f(fuel.laps_remaining, 1)}</span></div>
          {fuel.plan && <div className="row"><span>Per {fuel.plan.target_laps} giri (+{fuel.plan.safety_margin_laps} margine)</span><span className="mono">{f(fuel.plan.fuel_with_margin_l, 1)} L · da aggiungere {f(fuel.plan.to_add_l, 1)} L</span></div>}
        </> : <p className="warn">{fuel.note}</p>}
        <p className="mut">Giri usati: {fuel.laps_used.join(', ') || '–'}. Esclusi: {fuel.excluded.map((e: any) => `${e.lap} (${e.reason})`).join('; ') || 'nessuno'}.</p>
      </div> : <p className="warn">Carburante non disponibile: {fuel.reason}</p>)}
      {tyre && (tyre.available ? <div data-testid="tyres">
        <h3>Pneumatici (ultimo giro valido)</h3>
        <table><thead><tr><th>Ruota</th><th>Pressione kPa</th><th>T sx/centro/dx °C</th><th>Carcassa °C</th><th>Usura</th></tr></thead>
          <tbody>{['fl', 'fr', 'rl', 'rr'].map(w => { const x = tyre.per_lap.at(-1).wheels[w]; return <tr key={w}><td>{w.toUpperCase()}</td><td>{f(x.pressure_kpa, 1)}</td><td>{f(x.temp_left_c, 1)} / {f(x.temp_center_c, 1)} / {f(x.temp_right_c, 1)}</td><td>{f(x.carcass_c, 1)}</td><td>{f(x.wear_end, 4)}</td></tr> })}</tbody></table>
        <p className="mut">Tendenze (pendenza per giro): {Object.entries(tyre.trends).slice(0, 4).map(([k, v]: any) => `${k} ${v.slope_per_lap}`).join(' · ') || 'servono ≥3 giri'}</p>
        {tyre.missing_channels.length > 0 && <p className="warn">Canali non disponibili: {tyre.missing_channels.join(', ')}</p>}
        <p className="mut">{tyre.note}</p>
      </div> : <p className="warn">Pneumatici non disponibili: {tyre.reason}</p>)}
    </section>)
}
