import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const post = (path: string, body?: any, method = 'POST') => api(path, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

export default function AiSettings() {
  const [prov, setProv] = useState<any>(null)
  const [cfg, setCfg] = useState<any>(null)
  const [keys, setKeys] = useState<Record<string, string>>({ nvidia: '', groq: '' })
  const [test, setTest] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [endu, setEndu] = useState<any>(null)
  const load = () => {
    api('/api/ai/providers').then(setProv).catch(e => setMsg(e.message))
    api('/api/ai/settings').then(setCfg).catch(() => {})
    api('/api/endurance/status').then(setEndu).catch(() => {})
  }
  useEffect(load, [])
  const enabled = !!cfg?.enabled && cfg?.mode === 'free_multi'
  const toggle = async () => {
    await post('/api/ai/settings', { enabled: !enabled, mode: 'free_multi', providers: [], summary_interval_s: 300, max_calls_per_hour: 120 }, 'PUT')
    load()
  }
  const save = async (p: string) => {
    setMsg('')
    try {
      const r = await post('/api/ai/providers/key', { provider: p, key: keys[p] }, 'PUT')
      setKeys(k => ({ ...k, [p]: '' }))                        // the key never stays in the page state
      setMsg(r.stored ? `Chiave ${p} salvata in Gestione credenziali.` : `Non salvata: ${r.reason}`)
    } catch (e: any) { setMsg(e.message) }
    load()
  }
  const runTest = async () => { setBusy(true); setTest(null); try { setTest(await post('/api/ai/providers/test')) } catch (e: any) { setMsg(e.message) } setBusy(false); load() }
  return (
    <section className="panel" data-testid="ai-settings">
      <h2>AI gratuita (NVIDIA → Groq → analisi locale)</h2>
      <p className="mut">Solo modelli gratuiti, con limiti locali. Se nessun provider risponde, la gara continua con l'analisi locale. Le chiavi non vengono mai mostrate né salvate in chiaro.</p>
      <div className="row"><span>Provider AI online</span><span><button onClick={toggle} data-testid="ai-toggle">{enabled ? 'Disattiva' : 'Attiva'}</button> {enabled ? 'ATTIVO' : 'disattivato (solo locale)'}</span></div>
      {['nvidia', 'groq'].map(p => (
        <div className="row" key={p}>
          <span>{p.toUpperCase()} — {prov?.keys?.[p]?.configured ? <span className="ok">chiave presente ({prov.keys[p].source})</span> : <span className="warn">chiave mancante</span>}</span>
          <span><input type="password" autoComplete="off" placeholder="incolla la chiave" value={keys[p]} onChange={e => setKeys({ ...keys, [p]: e.target.value })} data-testid={'key-' + p} />
            <button disabled={keys[p].length < 8} onClick={() => save(p)}>Salva</button></span>
        </div>))}
      <p className="mut">In alternativa imposta le variabili d'ambiente <code>NVIDIA_API_KEY</code> / <code>GROQ_API_KEY</code>.</p>
      <button onClick={runTest} disabled={busy} data-testid="ai-test">{busy ? 'Test in corso…' : 'Prova reale (pochi token gratuiti)'}</button> {msg && <span className="warn">{msg}</span>}
      {test && <div data-testid="ai-test-result">
        <p><b>{test.summary}</b></p>
        {test.routes.map((r: any) => (
          <div className="row" key={r.route}><span>{r.route}</span>
            <span>{!r.configured ? <span className="warn">{r.how_to}</span> : r.ok ? <span className="ok">OK · {r.latency_s}s · {r.tokens} token</span> : r.tested ? <span className="bad">{r.error_kind}: {r.error}</span> : <span className="warn">{r.skipped || 'non provato'}</span>}</span></div>))}
      </div>}
      {prov && <details><summary>Stato route e quote</summary>
        {prov.routes.map((r: any) => <div className="row" key={r.route}><span>{r.route}</span><span className="mono">{r.configured ? (r.blocked_reason ? 'bloccata: ' + r.blocked_reason : 'pronta') : 'senza chiave'} · {r.usage.rpd}/{r.usage.limits.rpd ?? '∞'} richieste/giorno</span></div>)}
      </details>}
      {endu && <details><summary>Memoria di gara (locale)</summary>
        <div className="row"><span>Eventi / riepiloghi / giri / stint</span><span className="mono">{endu.memory.events} / {endu.memory.summaries} / {endu.memory.laps} / {endu.memory.stints}</span></div>
        <div className="row"><span>Coda AI in attesa</span><span className="mono">{endu.ai_queue ? endu.ai_queue.pending : 'AI non attiva'}</span></div>
      </details>}
    </section>)
}
