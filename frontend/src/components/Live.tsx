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
