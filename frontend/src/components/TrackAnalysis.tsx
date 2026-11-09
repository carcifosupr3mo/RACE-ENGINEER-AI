import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import SessionPicker from './SessionPicker'

type C = { id: string; name?: string | null; apex_m: number; entry_m: number; exit_m: number; min_speed_kmh?: number }

/** Corner map editor: detected segments are provisional; saving a profile replaces them with user-confirmed names. */
export default function TrackAnalysis({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [rows, setRows] = useState<C[]>([])
  const [track, setTrack] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => {
    setData(null); setMsg('')
    if (!sessionId) return
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
      <h2>Track Analysis</h2>
      <div className="toolbar"><SessionPicker value={sessionId} onChange={onPick} /></div>
      {data && <>
        <p className="mut">{data.provisional ? 'Curve PROVVISORIE rilevate dal giro di riferimento: i numeri reali delle curve non sono noti. Assegna nomi/numeri e salva il profilo.' : 'Profilo circuito confermato dall\'utente.'}</p>
        <table><thead><tr><th>Id</th><th>Nome / numero</th><th>Ingresso m</th><th>Apice m</th><th>Uscita m</th><th>V min</th></tr></thead>
          <tbody>{rows.map((r, i) => <tr key={r.id + i}><td>{r.id}</td>
            <td><input value={r.name ?? ''} placeholder="es. T1" onChange={e => upd(i, 'name', e.target.value)} style={{ width: 90 }} /></td>
            {(['entry_m', 'apex_m', 'exit_m'] as const).map(k => <td key={k}><input type="number" value={Math.round(r[k])} onChange={e => upd(i, k, +e.target.value)} style={{ width: 80 }} /></td>)}
            <td className="mono">{r.min_speed_kmh?.toFixed(0) ?? '–'}</td></tr>)}</tbody></table>
        <button onClick={save} data-testid="save-profile">Salva profilo circuito</button></>}
      {msg && <p className="mut" data-testid="track-msg">{msg}</p>}
    </section>)
}
