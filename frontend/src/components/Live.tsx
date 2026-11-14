import { useEffect, useState } from 'react'
import { wsUrl } from '../lib/api'

const W = ['fl', 'fr', 'rl', 'rr'] as const
const WN: Record<string, string> = { fl: 'Ant. sx', fr: 'Ant. dx', rl: 'Post. sx', rr: 'Post. dx' }
const fmtT = (t: any) => {
  if (t == null || !(t > 0)) return '–'
  const m = Math.floor(t / 60), s = t - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}
const num = (x: any, d = 0) => (x == null || Number.isNaN(x) ? '–' : Number(x).toFixed(d))

/** What the car is doing right now, from the game's own flags (not from the connection state). */
function drivingState(v: any): { label: string; cls: string } {
  if (!v) return { label: '–', cls: 'mut' }
  if (v.in_pits) return { label: 'Ai box', cls: 'tag' }
  if (v.in_realtime === false) return { label: 'Fermo in garage o nel menu', cls: 'mut' }
  return { label: 'In pista', cls: 'tag conf-high' }
}

export default function Live() {
  const [m, setM] = useState<any>(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    let ws: WebSocket, timer: any, alive = true
    const open = () => {
      ws = new WebSocket(wsUrl())
      ws.onmessage = e => { setDown(false); setM(JSON.parse(e.data)) }
      ws.onclose = () => { if (alive) { setDown(true); timer = setTimeout(open, 1500) } }
    }
    open()
    return () => { alive = false; clearTimeout(timer); ws?.close() }
  }, [])
  const st = m?.status, v = m?.sample?.values, p = m?.sample?.provenance
  const synth = st?.synthetic || m?.sample?.source === 'synthetic'
  const ds = drivingState(v)
  const rpmFrac = v?.max_rpm > 0 ? Math.min(1, (v.rpm ?? 0) / v.max_rpm) : 0
  const lost = st?.samples_lost ?? 0
  return (
    <section className="panel" data-testid="live">
      {synth && <div className="synth" data-testid="synth-banner">DATI SINTETICI — NON PROVENGONO DA LE MANS ULTIMATE</div>}
      <h2>Dati in diretta</h2>
      <p className="help">Quello che sta facendo l'auto in questo momento, letto dal simulatore.</p>
      {down && <p className="bad">Non riceviamo più dati dall'app. Controlla che sia aperta: ci ricolleghiamo da soli.</p>}
      <p data-testid="state">{st?.state_label ?? '–'} {v && <span className={ds.cls} data-testid="drive-state">{ds.label}</span>}{' '}
        <span className="mut">· {st?.effective_hz ?? 0} letture al secondo{lost > 0 ? ` · letture perse ${lost}` : ''}
          {st?.pause_events > 0 ? ` · pause (garage/menu) ${st.pause_events}` : ''}</span></p>
      <EngineerBlock e={m?.engineer} />
      {v ? (<>
        <div className="grid4">
          <Big label="km/h" v={v.speed_kmh?.toFixed(0)} src={p.speed_kmh} id="speed" />
          <Big label="giri motore" v={v.rpm?.toFixed(0)} src={p.rpm} />
          <Big label="marcia" v={v.gear === -1 ? 'R' : v.gear === 0 ? 'N' : v.gear} src={p.gear} />
          <Big label="giro" v={v.lap_number} src={p.lap_number} />
        </div>
        <div className="rpmbar" title="Regime motore"><i style={{ width: `${rpmFrac * 100}%`, background: rpmFrac > 0.93 ? 'var(--bad)' : 'var(--acc)' }} /></div>
        <h3>Tempi</h3>
        <div className="grid4" data-testid="live-times">
          <Big label="giro in corso" v={fmtT(v.lap_time_s)} />
          <Big label="ultimo giro" v={fmtT(v.last_lap_time_s)} />
          <Big label="miglior giro" v={fmtT(v.best_lap_time_s)} />
          <Big label="settore" v={v.sector ?? '–'} />
        </div>
        <h3>Comandi</h3>
        <div className="grid4">
          <Bar label="Acceleratore" x={v.throttle} color="var(--ok)" /><Bar label="Freno" x={v.brake} color="var(--bad)" />
          <Bar label="Frizione" x={v.clutch} color="var(--mut)" />
          <Bar label="Sterzo (sx ↔ dx)" x={(v.steering + 1) / 2} color="var(--acc)" />
        </div>
        <h3>Vettura</h3>
        <div className="grid4">
          <Big label={`benzina L${v.fuel_capacity_l ? ' / ' + num(v.fuel_capacity_l, 0) : ''}`} v={num(v.fuel_l, 1)} />
          <Big label="acqua °C" v={num(v.water_temp_c)} />
          <Big label="olio °C" v={num(v.oil_temp_c)} />
          <Big label="freni: parte sul retrotreno %" v={v.brake_bias_rear != null ? num(v.brake_bias_rear * 100, 1) : '–'} />
        </div>
        {(v.overheating || v.parts_detached || v.damage_dent_max > 0) && (
          <p className="bad" data-testid="damage">
            {v.overheating ? '⚠ Surriscaldamento ' : ''}{v.parts_detached ? '⚠ Parti staccate ' : ''}{v.damage_dent_max > 0 ? `⚠ Danni carrozzeria (livello ${v.damage_dent_max})` : ''}
          </p>)}
        <h3>Gomme</h3>
        <div className="tyres" data-testid="live-tyres">
          {W.map(w => (
            <div className="tyre" key={w}>
              <b>{WN[w]}</b>
              <div className="mono">{num(v[`tyre_${w}_temp_center_c`])} °C <small className="mut">({num(v[`tyre_${w}_temp_left_c`])} · {num(v[`tyre_${w}_temp_right_c`])})</small></div>
              <div className="mono">{num(v[`tyre_${w}_pressure_kpa`])} kPa</div>
              <div className="mono">usura {v[`tyre_${w}_wear`] != null ? num((1 - v[`tyre_${w}_wear`]) * 100) + '% rimasto' : '–'}</div>
              <small className="mut">freno {num(v[`tyre_${w}_brake_temp_c`])} °C</small>
            </div>))}
        </div>
        <h3>Condizioni</h3>
        <div className="grid4">
          <Big label="aria °C" v={num(v.ambient_temp_c, 1)} /><Big label="pista °C" v={num(v.track_temp_c, 1)} />
          <Big label="pioggia %" v={v.rain != null ? num(v.rain * 100) : '–'} /><Big label="bagnato pista %" v={v.path_wetness_avg != null ? num(v.path_wetness_avg * 100) : '–'} />
        </div>
      </>) : <p className="mut">Non riceviamo ancora dati dal simulatore. Controlla che il gioco sia aperto e che «Enable Plugins» sia attivo, poi entra in pista: i dati compaiono qui appena l'auto si muove.</p>}
    </section>)
}
const Big = ({ label, v, src, id }: any) => <div className="big"><div data-testid={id}>{v ?? '–'}</div><small>{label} <i className={'src ' + src}>{src}</i></small></div>
const Bar = ({ label, x, color }: any) => <div><small>{label} {x != null ? (x * 100).toFixed(0) + '%' : '–'}</small><div className="bar"><i style={{ width: `${(x ?? 0) * 100}%`, background: color }} /></div></div>

/** The dashboard shows the SAME shared engineer state as the Driving Display (field `engineer` of the live stream). */
function EngineerBlock({ e }: { e: any }) {
  if (!e?.ready) return <div className="eng" data-testid="live-engineer"><small className="mut">Ingegnere di pista: in attesa dei dati di guida</small></div>
  const sug = e.suggestion, m = sug?.main, d = e.delta
  return (
    <div className="eng" data-testid="live-engineer">
      <div className="eng-h"><b>Ingegnere di pista</b> <span className="tag" data-testid="live-mode">{e.session?.mode?.label}</span>
        <span className="tag" title="Il tuo miglior passaggio, usato come confronto">riferimento {e.reference?.reliability?.level} · {e.reference?.laps} giri</span> <span className="tag" data-testid="live-seq">v{e.reference?.version}</span>
        <a href="/driving-display" target="_blank" rel="noreferrer" data-testid="open-display">Apri lo schermo di guida ↗</a></div>
      <div className="eng-row">
        <span>Differenza dal riferimento: <b className="mono" data-testid="live-delta">{d?.available ? (d.to_ref_s > 0 ? '+' : '') + d.to_ref_s.toFixed(3) + ' s' : '–'}</b></span>
        <span>Curva: <b>{e.corner?.current ?? ('→ ' + (e.corner?.next ?? '–'))}</b></span>
        <span>Ultimo giro rispetto al riferimento: <b className="mono">{e.last_lap?.delta_s != null ? (e.last_lap.delta_s > 0 ? '+' : '') + e.last_lap.delta_s.toFixed(3) + ' s' : '–'}</b></span>
      </div>
      <div data-testid="live-suggestion" className={sug?.state === 'learning' ? 'mut' : ''}>
        {sug?.state === 'learning' ? sug.learning?.message : m ? <><b>{m.instruction?.text ?? m.text}</b> <span className={'tag conf-' + m.confidence?.level}>affidabilità {m.confidence?.level}</span></> : 'Per ora non vedo nulla di importante da correggere'}
      </div>
      {m?.instruction && <div className="mut" data-testid="live-instruction">{m.instruction.how}{m.instruction.habit_note ? ' · ' + m.instruction.habit_note : ''}</div>}
      {e.review && <div className="mut" data-testid="live-review">Giro {e.review.lap}: {e.review.summary}</div>}
      {e.alerts?.map((a: any) => <div key={a.id} className={a.level === 'info' ? 'mut' : 'bad'}>⚠ {a.text}</div>)}
      {e.ai_note && <div className="mut" data-testid="live-ai-note">Assistente AI ({e.ai_note.provider}, giro {e.ai_note.lap}): {e.ai_note.text}</div>}
    </div>)
}
