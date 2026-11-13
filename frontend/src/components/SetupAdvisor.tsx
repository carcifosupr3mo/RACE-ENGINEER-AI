import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import SessionPicker from './SessionPicker'

export default function SetupAdvisor({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [text, setText] = useState('')
  const [setupId, setSetupId] = useState<string | null>(null)
  const [info, setInfo] = useState<any>(null)
  const [laps, setLaps] = useState<any[]>([])
  const [lap, setLap] = useState<number | null>(null)
  const [advice, setAdvice] = useState<any>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setLaps([]); setAdvice(null); if (!sessionId) return
    api(`/api/sessions/${sessionId}/laps`).then(r => { const v = r.laps.filter((l: any) => l.valid_for_analysis && l.number !== r.summary.best_lap); setLaps(v); setLap(v[0]?.number ?? null) })
  }, [sessionId])
  const imp = async () => {
    setErr('')
    try { let raw: any = text; try { const j = JSON.parse(text); if (j && typeof j === 'object') raw = j } catch { /* not JSON: send the text as is (.svm) */ }; const r = await api('/api/setups/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ raw, session_id: sessionId }) }); setSetupId(r.id); setInfo(r) }
    catch (e: any) { setErr('Setup non importato: ' + e.message) }
  }
  const run = async () => {
    setErr('')
    try { setAdvice(await api(`/api/setups/${setupId}/advice?session_id=${sessionId}&lap=${lap}`)) } catch (e: any) { setErr(e.message) }
  }
  return (
    <section className="panel" data-testid="setup">
      <h2>Consigli sull'assetto</h2>
      <p className="help">Suggerimenti su come cambiare l'assetto, in base ai dati della sessione.</p>
      <p className="warn">Formato dei setup LMU non verificato: accetta JSON o testo .svm (copia fedele conservata); il parser è generico. Nessuna modifica automatica; nessun valore viene proposto senza limiti min/max verificati nel setup stesso.</p>
      <div className="toolbar"><SessionPicker value={sessionId} onChange={onPick} /></div>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={6} placeholder="Incolla il JSON del setup (copia: l'originale non viene mai modificato)" style={{ width: '100%' }} data-testid="setup-json" />
      <div className="toolbar"><button onClick={imp} disabled={!text}>Importa</button>
        {setupId && <><label className="inl">Giro <select value={lap ?? ''} onChange={e => setLap(+e.target.value)}>{laps.map(l => <option key={l.number} value={l.number}>{l.number}</option>)}</select></label><button onClick={run} disabled={!sessionId || lap == null}>Analizza vs giro migliore</button></>}</div>
      {info && <p className="mut">Parametri con limiti verificati: {info.parameters_with_limits} · altri valori: {info.other_values}{info.warning ? ' — ' + info.warning : ''}</p>}
      {err && <p className="bad">{err}</p>}
      {advice && <div data-testid="advice">
        <h3>Ipotesi (compatibilità, non causalità)</h3>
        {advice.hypotheses.length === 0 && <p className="mut">Nessuna osservazione collegabile a un'area di setup.</p>}
        {advice.hypotheses.map((h: any, i: number) => <div className="msg" key={i}><b>{h.finding}</b> → {h.area}<div className="mut">{h.note}</div>{h.proposal && <div className="warn">{h.proposal}</div>}</div>)}
        <h3>Proposte numeriche</h3>
        {advice.proposals.length === 0 ? <p className="mut">Nessuna proposta: mancano limiti verificati o passo dichiarato.</p> :
          <table><thead><tr><th>Parametro</th><th>Attuale</th><th>Proposto</th><th>Limiti</th><th>Effetto atteso</th><th>Compromessi</th><th>Confidenza</th></tr></thead>
            <tbody>{advice.proposals.map((p: any, i: number) => <tr key={i}><td>{p.label ?? p.parameter}</td><td>{p.current}</td><td>{p.proposed}</td><td>{p.limits_verified.join('–')}</td><td>{p.expected_effect}</td><td>{p.trade_offs}</td><td>{p.confidence}</td></tr>)}</tbody></table>}
      </div>}
    </section>)
}
