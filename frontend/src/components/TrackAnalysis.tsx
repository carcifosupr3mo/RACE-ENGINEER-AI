import { useEffect, useRef, useState } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { api } from '../lib/api'
import SessionPicker from './SessionPicker'

type C = { id: string; name?: string | null; apex_m: number; entry_m: number; exit_m: number; min_speed_kmh?: number }

/** Corner map editor: detected segments are provisional; saving a profile replaces them with user-confirmed names. */
export default function TrackAnalysis({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [rows, setRows] = useState<C[]>([])
  const [track, setTrack] = useState('')
  const [msg, setMsg] = useState('')
  const [report, setReport] = useState<any>(null)
  const [trace, setTrace] = useState<any>(null)
  const [repMsg, setRepMsg] = useState('')
  useEffect(() => {
    setData(null); setMsg(''); setReport(null); setTrace(null); setRepMsg('')
    if (!sessionId) return
    api(`/api/sessions/${sessionId}/report`).then(async r => {
      setReport(r)
      if (r.best_lap != null) setTrace(await api(`/api/sessions/${sessionId}/trace?laps=${r.best_lap}&step=2`))
    }).catch(e => setRepMsg(e.message))
    api('/api/sessions').then((ss: any[]) => setTrack(ss.find(s => s.id === sessionId)?.track ?? ''))
    api(`/api/sessions/${sessionId}/corners`).then(d => { setData(d); setRows(d.corners) }).catch(e => setMsg(e.message))
  }, [sessionId])
  const upd = (i: number, k: keyof C, v: any) => setRows(r => r.map((x, j) => j === i ? { ...x, [k]: v } : x))
  const save = async () => {
    try { await api(`/api/tracks/profile?track=${encodeURIComponent(track)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(rows.map(r => ({ ...r, id: r.name || r.id }))) }); setMsg('Profilo salvato'); }
    catch (e: any) { setMsg('Errore: ' + e.message) }
  }
  return (
    <section className="panel" data-testid="track">
      <h2>Analisi del circuito</h2>
      <p className="help">Qui vedi la pista disegnata con i punti dove vai forte (verde) e dove perdi tempo (rosso), confrontando tutti i tuoi giri validi di una sessione.</p>
      <div className="toolbar"><SessionPicker value={sessionId} onChange={onPick} /></div>
      {!sessionId && <p className="mut">Scegli una sessione qui sopra (le sessioni registrate sono in «Sessioni»).</p>}
      {repMsg && <p className="bad" data-testid="track-report-error">{repMsg}</p>}
      {report && <ZoneMap report={report} trace={trace} />}
      {data && data.corners.length === 0 && <p className="bad" data-testid="no-corners">Nessuna curva rilevata su questo giro di riferimento: il profilo non può essere salvato. Scegli una sessione con almeno un giro completo.</p>}
      {data && data.corners.length > 0 && <details data-testid="profile-editor"><summary><b>Dai un nome alle curve</b> (facoltativo: es. «Curva 1», «Parabolica»)</summary>
        <p className="mut">{data.provisional ? 'Curve PROVVISORIE rilevate dal giro di riferimento: i numeri reali delle curve non sono noti. Assegna nomi/numeri e salva il profilo.' : 'Profilo circuito confermato dall\'utente.'}</p>
        <table><thead><tr><th>Id</th><th>Nome / numero</th><th>Ingresso m</th><th>Apice m</th><th>Uscita m</th><th>V min</th></tr></thead>
          <tbody>{rows.map((r, i) => <tr key={r.id + i}><td>{r.id}</td>
            <td><input value={r.name ?? ''} placeholder="es. T1" onChange={e => upd(i, 'name', e.target.value)} style={{ width: 90 }} /></td>
            {(['entry_m', 'apex_m', 'exit_m'] as const).map(k => <td key={k}><input type="number" value={Math.round(r[k])} onChange={e => upd(i, k, +e.target.value)} style={{ width: 80 }} /></td>)}
            <td className="mono">{r.min_speed_kmh?.toFixed(0) ?? '–'}</td></tr>)}</tbody></table>
        <button onClick={save} disabled={rows.length === 0} data-testid="save-profile">Salva profilo circuito</button></details>}
      {msg && <p className="mut" data-testid="track-msg">{msg}</p>}
    </section>)
}

const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t)
/** green (no time lost) -> amber -> red (a lot of time lost on a normal lap) */
const zoneColor = (lost: number | null) => {
  if (lost == null) return '#667788'
  const t = Math.min(1, lost / 0.25)
  return t < 0.5 ? `rgb(${lerp(61, 255, t * 2)},${lerp(220, 176, t * 2)},${lerp(132, 32, t * 2)})` : `rgb(255,${lerp(176, 77, (t - 0.5) * 2)},${lerp(32, 79, (t - 0.5) * 2)})`
}
const sec = (x: number) => x.toFixed(2).replace('.', ',') + ' s'

/** The circuit drawn from the best lap, every zone coloured by how much time you leave there on an average lap. */
function ZoneMap({ report, trace }: { report: any; trace: any }) {
  const div = useRef<HTMLDivElement | null>(null)
  const comparable = report.laps.length >= 2
  const zones: any[] = report.zones
  const ranked = [...zones].sort((a, b) => b.consistency_loss_s - a.consistency_loss_s)
  const worst = comparable ? ranked.filter(z => z.consistency_loss_s >= 0.03).slice(0, 4) : []
  const best = comparable ? [...ranked].reverse().filter(z => z.kind === 'corner').slice(0, 3) : []
  const lap = trace && report.best_lap != null ? trace.laps[report.best_lap] : null
  useEffect(() => {
    const el = div.current
    if (!el || !lap?.pos_x_m) return
    const d: number[] = trace.distance_m
    const data: any[] = zones.map(z => {
      const idx = d.map((m, i) => (m >= z.start_m && m <= z.end_m + 2 ? i : -1)).filter(i => i >= 0)
      return { x: idx.map(i => lap.pos_x_m[i]), y: idx.map(i => lap.pos_z_m[i]), mode: 'lines', line: { color: zoneColor(comparable ? z.consistency_loss_s : null), width: 9 },
        hoverinfo: 'text', text: `${z.label}: ${comparable ? 'perdi in media ' + sec(z.consistency_loss_s) : 'servono 2+ giri per il confronto'}`, showlegend: false }
    })
    const ann = zones.filter(z => z.kind === 'corner').map(z => {
      const i = Math.min(d.length - 1, Math.round((z.apex_m ?? (z.start_m + z.end_m) / 2) / (d[1] - d[0] || 2)))
      return lap.pos_x_m[i] == null ? null : { x: lap.pos_x_m[i], y: lap.pos_z_m[i], text: z.label, showarrow: false, font: { size: 11, color: '#e6ebf0' }, yshift: 14, bgcolor: 'rgba(11,13,16,0.6)' }
    }).filter(Boolean)
    Plotly.react(el, data, { height: 460, margin: { l: 6, r: 6, t: 6, b: 6 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#0e1216', showlegend: false,
      xaxis: { visible: false, scaleanchor: 'y' }, yaxis: { visible: false }, annotations: ann as any, hovermode: 'closest' }, { displayModeBar: false, responsive: true })
  }, [report, trace])
  return (
    <div data-testid="zone-map-box">
      <h3>Mappa: dove guadagni e dove perdi</h3>
      {lap?.pos_x_m ? <div ref={div} data-testid="zone-map" /> : <p className="mut">Mappa non disponibile per questa sessione (mancano le posizioni).</p>}
      <div className="legend"><i style={{ background: zoneColor(0) }} />perdi poco o niente <i style={{ background: zoneColor(0.125) }} />qualcosa <i style={{ background: zoneColor(0.25) }} />molto tempo perso</div>
      {!comparable && <p className="warn">C'è un solo giro valido: per colorare la pista servono almeno 2 giri completi da confrontare.</p>}
      <div className="cols2">
        <div><h3>Dove perdi più tempo</h3>
          {worst.length === 0 ? <p className="ok">{comparable ? 'Nessuna zona con perdite importanti: guidi in modo molto costante.' : '–'}</p> :
            <ol data-testid="worst-zones">{worst.map(z => <li key={z.id}><b>{z.label}</b>: in media perdi <b className="bad">{sec(z.consistency_loss_s)}</b> rispetto al tuo meglio (giro {z.best_lap}).</li>)}</ol>}</div>
        <div><h3>Le tue curve migliori</h3>
          {best.length === 0 ? <p className="mut">–</p> :
            <ol data-testid="best-zones">{best.map(z => <li key={z.id}><b>{z.label}</b>: molto costante (perdi solo {sec(z.consistency_loss_s)} in media).</li>)}</ol>}</div>
      </div>
      <details open><summary><b>Tutti i dati, zona per zona</b></summary>
        <table data-testid="zone-table"><thead><tr><th>Zona</th><th>Tipo</th><th>Da → a (m)</th><th>Il tuo meglio</th><th>Tempo medio</th><th>Perdi in media</th><th>Giro migliore qui</th></tr></thead>
          <tbody>{zones.map(z => <tr key={z.id}><td><b>{z.label}</b></td><td>{z.kind === 'corner' ? 'Curva' : 'Rettilineo'}</td>
            <td className="mono">{Math.round(z.start_m)} → {Math.round(z.end_m)}</td><td className="mono">{sec(z.best_s)}</td><td className="mono">{sec(z.mean_s)}</td>
            <td className="mono" style={{ color: comparable ? zoneColor(z.consistency_loss_s) : undefined }}>{comparable ? sec(z.consistency_loss_s) : '–'}</td><td>giro {z.best_lap}</td></tr>)}</tbody></table>
        <p className="mut">«Perdi in media» = quanto tempo in più della tua versione migliore di quella zona impieghi in un giro normale. Verde = costante, rosso = lì c'è più da guadagnare.</p>
      </details>
    </div>)
}
