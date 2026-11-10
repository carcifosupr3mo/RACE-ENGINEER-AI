import { useEffect, useState } from 'react'
import { wsUrl } from '../lib/api'

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
  return (
    <section className="panel" data-testid="live">
      {synth && <div className="synth" data-testid="synth-banner">DATI SINTETICI — NON PROVENGONO DA LE MANS ULTIMATE</div>}
      <h2>Live Telemetry</h2>
      {down && <p className="bad">Backend non raggiungibile…</p>}
      <p data-testid="state">{st?.state_label ?? '–'} <span className="mut">· {st?.effective_hz ?? 0} Hz · persi {st?.samples_lost ?? 0}</span></p>
      <EngineerBlock e={m?.engineer} />
      {v ? (
        <div className="grid4">
          <Big label="km/h" v={v.speed_kmh?.toFixed(0)} src={p.speed_kmh} id="speed" />
          <Big label="rpm" v={v.rpm?.toFixed(0)} src={p.rpm} />
          <Big label="marcia" v={v.gear} src={p.gear} />
          <Big label="giro" v={v.lap_number} src={p.lap_number} />
          <Bar label="Acceleratore" x={v.throttle} color="var(--ok)" /><Bar label="Freno" x={v.brake} color="var(--bad)" />
          <Bar label="Sterzo" x={(v.steering + 1) / 2} color="var(--acc)" />
        </div>) : <p className="mut">Nessun campione ricevuto.</p>}
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
        <span className="tag">rif. {e.reference?.reliability?.level} · {e.reference?.laps} giri</span> <span className="tag" data-testid="live-seq">v{e.reference?.version}</span>
        <a href="/driving-display" target="_blank" rel="noreferrer" data-testid="open-display">Apri Driving Display ↗</a></div>
      <div className="eng-row">
        <span>Delta: <b className="mono" data-testid="live-delta">{d?.available ? (d.to_ref_s > 0 ? '+' : '') + d.to_ref_s.toFixed(3) + ' s' : '–'}</b></span>
        <span>Curva: <b>{e.corner?.current ?? ('→ ' + (e.corner?.next ?? '–'))}</b></span>
        <span>Ultimo giro vs rif.: <b className="mono">{e.last_lap?.delta_s != null ? (e.last_lap.delta_s > 0 ? '+' : '') + e.last_lap.delta_s.toFixed(3) + ' s' : '–'}</b></span>
      </div>
      <div data-testid="live-suggestion" className={sug?.state === 'learning' ? 'mut' : ''}>
        {sug?.state === 'learning' ? sug.learning?.message : m ? <><b>{m.text}</b> <span className={'tag conf-' + m.confidence?.level}>affidabilità {m.confidence?.level}</span></> : 'Nessun miglioramento significativo rilevato'}
      </div>
      {e.alerts?.map((a: any) => <div key={a.id} className={a.level === 'info' ? 'mut' : 'bad'}>⚠ {a.text}</div>)}
      {e.ai_note && <div className="mut" data-testid="live-ai-note">AI ({e.ai_note.provider}, giro {e.ai_note.lap}): {e.ai_note.text}</div>}
    </div>)
}
