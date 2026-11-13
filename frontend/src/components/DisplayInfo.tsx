import { useEffect, useState } from 'react'
import { api } from '../lib/api'

/** How to open the Driving Display (same backend, same state): second monitor on this PC or a browser on the LAN. */
export default function DisplayInfo() {
  const [i, setI] = useState<any>(null)
  useEffect(() => { api('/api/display/info').then(setI).catch(() => setI(null)) }, [])
  return (
    <section className="panel" data-testid="display-info">
      <h2>Display di guida</h2>
      <p className="help">Una schermata grande e semplice da leggere in pista, con i consigli dell'ingegnere. Puoi metterla su un secondo monitor o su un altro PC/tablet.</p>
      <p>Seconda modalità di presentazione della <b>stessa</b> app (stesso motore, stessa telemetria, stessi risultati della dashboard), pensata per un monitor esterno da 10–13″.</p>
      <h3>Secondo monitor collegato al PC</h3>
      <p>Apri <a href="/driving-display" target="_blank" rel="noreferrer" data-testid="display-link">/driving-display</a> in una finestra e trascinala sul secondo monitor (F11 per il tutto schermo). L'app desktop ha la voce di menu «Apri Driving Display» nella barra di sistema.</p>
      <h3>Browser in rete locale (Raspberry Pi, tablet)</h3>
      {i?.lan_enabled
        ? <>{(i.lan_urls || []).map((u: string) => <div key={u}><code>{u}</code></div>)}<p className="mut">L'indirizzo contiene il token di accesso: tienilo privato. Il Raspberry mostra soltanto i risultati calcolati dal PC.</p></>
        : <p className="mut" data-testid="display-lan-off">Accesso dalla rete locale disattivato (predefinito, solo questo PC). Per attivarlo vai in <b>Impostazioni → Display in rete (LAN)</b> e premi «Accendi» (o usa la voce ON/OFF nel menu dell'icona vicino all'orologio): l'indirizzo da aprire sull'altro schermo compare lì.</p>}
      <p className="mut">Endpoint condivisi: <code>{i?.api ?? '/api/engineer/state'}</code> · WebSocket <code>/ws/live</code> (campo <code>engineer</code>).</p>
    </section>)
}
