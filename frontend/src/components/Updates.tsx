import { useState } from 'react'
import { api } from '../lib/api'
import type { UpdateStatus } from './UpdateGate'

/** Settings → Aggiornamenti */
export default function Updates({ st, poll }: { st: UpdateStatus | null; poll: () => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const check = async () => { setBusy(true); setMsg(''); try { await api('/api/update/check', { method: 'POST' }); poll() } catch (e: any) { setMsg(e.message) } setBusy(false) }
  const toggle = async () => { try { await api('/api/update/auto', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: !st?.auto }) }); poll() } catch (e: any) { setMsg(e.message) } }
  const start = async () => { try { await api('/api/update/start', { method: 'POST' }); poll() } catch (e: any) { setMsg(e.message) } }
  const s = st?.state
  const line = s === 'up_to_date' ? 'Hai già l\'ultima versione.' : s === 'available' ? `È disponibile la versione ${st?.latest}.`
    : s === 'offline' ? 'Non c\'è connessione a Internet: l\'app funziona normalmente e riproverà più tardi.' : s === 'checking' ? 'Controllo in corso…'
    : s === 'error' ? (st?.error ?? '') : 'Non ancora controllato in questa sessione.'
  return (
    <section className="panel" data-testid="updates">
      <h2>Aggiornamenti</h2>
      <p className="help">L'app controlla da sola se esiste una versione più nuova ogni volta che la apri. Vengono usate solo le versioni stabili pubblicate dal progetto.</p>
      <div className="row"><span>Versione installata</span><b data-testid="installed-version">{st?.current ?? '…'}</b></div>
      <div className="row"><span>Ultima versione disponibile</span><span data-testid="latest-version">{st?.latest ?? (s === 'up_to_date' ? 'nessuna più recente' : '—')}</span></div>
      <p data-testid="update-line" className={s === 'available' ? 'ok' : 'mut'}>{line}</p>
      <div className="row"><span>Aggiornamenti automatici<br /><small className="mut">Se attivi, le nuove versioni si scaricano e si installano da sole all'avvio. Se spenti, ti chiediamo prima.</small></span>
        <button role="switch" aria-checked={!!st?.auto} className={'switch' + (st?.auto ? ' on' : '')} onClick={toggle} data-testid="auto-update">{st?.auto ? 'Attivi' : 'Spenti'}</button></div>
      <div className="btns"><button onClick={check} disabled={busy || s === 'checking'} data-testid="check-update">{busy ? 'Controllo…' : 'Controlla aggiornamenti'}</button>
        {s === 'available' && st?.can_install && <button className="primary" onClick={start}>Installa ora</button>}
        {s === 'available' && !st?.can_install && <a className="btn" href={st?.release_url ?? st?.releases_url} target="_blank" rel="noreferrer">Apri la pagina di download</a>}</div>
      {s === 'available' && !st?.can_install && <p className="warn">{st?.manual_reason}</p>}
      {s === 'available' && st?.notes && <details open><summary>Novità della versione {st.latest}</summary><pre className="notes">{st.notes}</pre></details>}
      {msg && <p className="bad">{msg}</p>}
    </section>)
}
