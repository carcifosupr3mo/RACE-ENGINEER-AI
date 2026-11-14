import { useEffect, useState } from 'react'
import { api } from '../lib/api'

/** How to open the Driving Display (same backend, same state): second monitor on this PC or a browser on the LAN. */
export default function DisplayInfo() {
  const [i, setI] = useState<any>(null)
  useEffect(() => { api('/api/display/info').then(setI).catch(() => setI(null)) }, [])
  return (
    <section className="panel" data-testid="display-info">
      <h2>Schermo di guida</h2>
      <p className="help">Una schermata grande e semplice da leggere in pista, con i consigli dell'ingegnere. Puoi metterla su un secondo monitor o su un altro PC/tablet.</p>
      <p>È la <b>stessa</b> app, mostrata in grande e senza distrazioni, pensata per un monitor esterno da 10–13″.</p>
      <h3>Secondo monitor collegato al PC</h3>
      <p>Apri <a href="/driving-display" target="_blank" rel="noreferrer" data-testid="display-link">/driving-display</a> in una finestra e trascinala sul secondo monitor (F11 per il tutto schermo). Nell'icona vicino all'orologio trovi anche la voce «Apri lo schermo di guida».</p>
      <h3>Un altro PC o tablet nella tua rete di casa</h3>
      {i?.lan_enabled
        ? <>{(i.lan_urls || []).map((u: string) => <div key={u}><code>{u}</code></div>)}<p className="mut">L'indirizzo contiene un codice segreto di accesso: tienilo privato. L'altro dispositivo mostra solo i risultati calcolati da questo PC.</p></>
        : <p className="mut" data-testid="display-lan-off">Gli altri dispositivi per ora non possono collegarsi (solo questo PC). Per permetterlo vai in <b>Impostazioni → Display in rete</b> e premi «Accendi» (o usa la voce ON/OFF nel menu dell'icona vicino all'orologio): l'indirizzo da aprire sull'altro schermo compare lì.</p>}
      <details><summary>Dettagli tecnici</summary><p className="mut">Indirizzi condivisi: <code>{i?.api ?? '/api/engineer/state'}</code> · flusso <code>/ws/live</code> (campo <code>engineer</code>).</p></details>
    </section>)
}
