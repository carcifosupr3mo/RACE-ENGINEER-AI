import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function Sessions({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [files, setFiles] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const load = () => { api('/api/sessions').then(setRows); api('/api/duckdb/files').then(setFiles).catch(() => setFiles([])) }
  useEffect(load, [])
  const imp = async (path: string) => {
    setMsg('Importazione…')
    try { const r = await api('/api/import/duckdb?path=' + encodeURIComponent(path), { method: 'POST' }); setMsg(`Importata: ${r.samples} campioni. ${r.warnings.join(' ')}`); load() }
    catch (e: any) { setMsg('Errore: ' + e.message) }
  }
  return (
    <section className="panel" data-testid="sessions">
      <h2>Sessioni registrate</h2>
      <p className="help">Ogni volta che guidi, l'app registra la sessione. Apri una sessione per analizzarne i giri.</p>
      <table><thead><tr><th>Circuito</th><th>Vettura</th><th>Tipo</th><th>Origine</th><th>Stato</th><th>Campioni</th><th>Persi</th><th /></tr></thead>
        <tbody>{(rows ?? []).map(r => (
          <tr key={r.id}>
            <td>{r.is_synthetic ? <span className="tag syn">SINT</span> : null} {r.track}</td><td>{r.vehicle}</td><td>{r.session_type}</td>
            <td>{r.source}</td><td>{r.status}</td><td>{r.samples}</td><td>{r.samples_lost}</td>
            <td><button disabled={r.status === 'recording'} onClick={() => onOpen(r.id)} data-testid="open-laps">Analizza</button></td>
          </tr>))}</tbody></table>
      {rows?.length === 0 && <p className="mut">Nessuna sessione registrata.</p>}
      <h2 style={{ marginTop: 18 }}>File DuckDB nativi di LMU</h2>
      {files.length === 0 ? <p className="mut">Nessun file trovato (cartella UserData/Telemetry non disponibile).</p> :
        files.map(f => <div className="row" key={f.path}><span>{f.path.split(/[\\/]/).pop()}</span><button onClick={() => imp(f.path)}>Importa</button></div>)}
      {msg && <p className="mut">{msg}</p>}
    </section>)
}
