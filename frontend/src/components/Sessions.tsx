import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const SOURCE: Record<string, string> = { lmu_shm: 'Dal gioco, in diretta', duckdb_import: 'File importato da Le Mans Ultimate', synthetic: 'Dati di prova' }
const STATUS: Record<string, string> = { complete: 'Completa', incomplete: 'Incompleta', recording: 'In registrazione' }

export default function Sessions({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [files, setFiles] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const load = () => { api('/api/sessions').then(setRows); api('/api/duckdb/files').then(setFiles).catch(() => setFiles([])) }
  useEffect(load, [])
  const imp = async (path: string) => {
    setMsg('Sto importando il file…')
    try { const r = await api('/api/import/duckdb?path=' + encodeURIComponent(path), { method: 'POST' }); setMsg(`Sessione importata (${r.samples} letture). ${r.warnings.join(' ')}`); load() }
    catch (e: any) { setMsg('Non è stato possibile importare il file. ' + e.message) }
  }
  return (
    <section className="panel" data-testid="sessions">
      <h2>Sessioni registrate</h2>
      <p className="help">Ogni volta che guidi, l'app registra la sessione da sola. Premi «Analizza» per vedere i tuoi giri. Qui vedi solo le sessioni del simulatore scelto.</p>
      <table><thead><tr><th>Circuito</th><th>Auto</th><th>Tipo</th><th>Come è stata raccolta</th><th>Stato</th><th>Letture</th><th>Perse</th><th /></tr></thead>
        <tbody>{(rows ?? []).map(r => (
          <tr key={r.id}>
            <td>{r.is_synthetic ? <span className="tag syn">SINT</span> : null} {r.track}</td><td>{r.vehicle}</td><td>{r.session_type}</td>
            <td>{SOURCE[r.source] ?? r.source}</td><td>{STATUS[r.status] ?? r.status}</td><td>{r.samples}</td><td>{r.samples_lost}</td>
            <td><button disabled={r.status === 'recording'} onClick={() => onOpen(r.id)} data-testid="open-laps">Analizza</button></td>
          </tr>))}</tbody></table>
      {rows?.length === 0 && <p className="mut">Nessuna sessione registrata. Avvia il simulatore e entra in pista: la registrazione parte da sola.</p>}
      <h2 style={{ marginTop: 18 }}>Sessioni salvate da Le Mans Ultimate</h2>
      <p className="help">Le Mans Ultimate salva da solo alcuni file di telemetria. Puoi importarli per analizzare anche le guide fatte quando l'app era chiusa. I file originali non vengono mai modificati.</p>
      {files.length === 0 ? <p className="mut">Non abbiamo trovato file di Le Mans Ultimate su questo PC (il gioco potrebbe non essere installato).</p> :
        files.map(f => <div className="row" key={f.path}><span>{f.path.split(/[\\/]/).pop()}</span><button onClick={() => imp(f.path)}>Importa</button></div>)}
      {msg && <p className="mut">{msg}</p>}
    </section>)
}
