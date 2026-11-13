import { useState } from 'react'
import { api } from '../lib/api'
import SessionPicker from './SessionPicker'

const QUICK = ['Dove perdo tempo?', 'Qual è la curva peggiore?', 'Come posso migliorare la frenata?', 'Sto accelerando troppo tardi?', 'Sono costante?',
  'Qual è il mio miglior settore?', 'Quali errori ripeto?', 'Come posso migliorare il mio passo gara?', 'Come sono migliorato rispetto alla settimana precedente?']

export default function Engineer({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [q, setQ] = useState('')
  const [log, setLog] = useState<{ q: string; a?: any; err?: string }[]>([])
  const [busy, setBusy] = useState(false)
  const ask = async (text: string) => {
    if (!sessionId || !text.trim()) return
    setBusy(true); const i = log.length
    setLog(l => [...l, { q: text }])
    try { const a = await api('/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, question: text }) })
      setLog(l => l.map((x, k) => k === i ? { ...x, a } : x)) }
    catch (e: any) { setLog(l => l.map((x, k) => k === i ? { ...x, err: e.message } : x)) }
    setBusy(false); setQ('')
  }
  return (
    <section className="panel" data-testid="engineer">
      <h2>Ingegnere AI</h2>
      <p className="help">Fai domande in italiano sulla tua sessione: le risposte usano solo i dati misurati.</p>
      <div className="toolbar"><SessionPicker value={sessionId} onChange={onPick} /></div>
      <p className="mut">Le risposte usano solo fatti calcolati dai dati della sessione. Se un dato manca, viene dichiarato. L'AI esterna è opzionale (senza, risponde il motore a regole).</p>
      <div className="chips">{QUICK.map(x => <button key={x} disabled={!sessionId || busy} onClick={() => ask(x)}>{x}</button>)}</div>
      <form onSubmit={e => { e.preventDefault(); ask(q) }} className="toolbar" style={{ marginTop: 8 }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Scrivi una domanda…" style={{ flex: 1 }} data-testid="q" />
        <button disabled={!sessionId || busy}>Invia</button></form>
      {log.map((m, i) => <div key={i} className="msg">
        <div className="you">{m.q}</div>
        {m.err && <div className="bad">{m.err}</div>}
        {m.a && <Answer a={m.a} />}</div>)}
    </section>)
}

function Answer({ a }: { a: any }) {
  return (
    <div className="ans" data-testid="answer">
      <h4>Osservazioni misurate</h4>
      {a.observed.length ? <ul>{a.observed.map((o: any, i: number) => <li key={i}>{o.text} <small className="mut">[{o.facts.join(', ')}]</small></li>)}</ul> : <p className="mut">Nessuna osservazione misurata disponibile.</p>}
      {a.interpretation.length > 0 && <><h4>Interpretazione tecnica</h4><ul>{a.interpretation.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul></>}
      {a.suggestion.length > 0 && <><h4>Suggerimento</h4><ul>{a.suggestion.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul></>}
      {a.missing.length > 0 && <><h4>Dati mancanti</h4><ul>{a.missing.map((t: string, i: number) => <li key={i} className="warn">{t}</li>)}</ul></>}
      <h4>Confidenza</h4><p><span className={'tag conf-' + a.confidence.level}>{a.confidence.level}</span> <small className="mut">{a.confidence.reason}</small></p>
      <details><summary>Dati utilizzati ({a.data_used.length}) · generata da {a.generated_by}{a.llm?.rejected ? ' · risposta LLM respinta dal validatore' : ''}</summary>
        {Object.values(a.facts).map((f: any) => <div key={f.id} className="row"><span className="mono">{f.id}</span><span>{f.text} <i className={'src ' + f.provenance}>{f.provenance}</i></span></div>)}</details>
    </div>)
}
