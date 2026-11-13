import { useEffect, useState } from 'react'
import { api } from '../lib/api'

/** ON/OFF for showing the Driving Display on another PC/tablet on the same network. No command line needed. */
export default function LanSettings() {
  const [lan, setLan] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const load = () => api('/api/lan').then(setLan).catch(e => setMsg(e.message))
  useEffect(() => { load() }, [])
  const set = async (enabled: boolean) => {
    setBusy(true); setMsg('')
    try {
      const r = await api('/api/lan', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }) })
      setLan(r)
      if (r.error) setMsg('Non riesco ad aprire la rete: ' + r.error)
    } catch (e: any) { setMsg(e.message) }
    setBusy(false)
  }
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => setMsg('Indirizzo copiato.')).catch(() => setMsg('Copia non riuscita: selezionalo a mano.'))
  const on = !!lan?.enabled
  return (
    <section className="panel" data-testid="lan-settings">
      <h2>Display in rete (LAN)</h2>
      <p className="mut">Mostra il Driving Display su un altro schermo o PC della stessa rete (Wi-Fi o cavo). Spento di default: quando è attivo
        serve un codice segreto (token) nell'indirizzo, quindi nessuno può entrare senza.</p>
      <div className="row"><span>Stato</span>
        <span>{on ? <b className="ok" data-testid="lan-state">ATTIVO</b> : <b data-testid="lan-state">SPENTO (solo questo PC)</b>}{' '}
          {lan?.available === false
            ? <span className="mut">non disponibile in questa modalità</span>
            : <button onClick={() => set(!on)} disabled={busy} data-testid="lan-toggle">{busy ? '…' : on ? 'Spegni' : 'Accendi'}</button>}</span></div>
      {on && <>
        {lan.urls?.length ? lan.urls.map((u: string) => (
          <div className="row" key={u}><span className="mono" style={{ wordBreak: 'break-all' }} data-testid="lan-url">{u}</span>
            <span><button onClick={() => copy(u)}>Copia</button></span></div>
        )) : <p className="warn">Nessun indirizzo di rete privato trovato: controlla di essere collegato al Wi-Fi o al cavo.</p>}
        <p className="mut">Apri uno di questi indirizzi dal browser dell'altro schermo/PC. L'indirizzo contiene il token: tienilo privato.</p>
        <p className="mut">{lan.firewall_hint}</p>
      </>}
      {msg && <p className="warn">{msg}</p>}
    </section>)
}
