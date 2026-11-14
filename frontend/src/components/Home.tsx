import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { SimBadge, useSims, type Sim } from '../lib/sims'

const DOT: Record<string, string> = { ok: 'ok', waiting: 'warn', problem: 'bad', not_supported: 'mut' }

function SimCard({ sim, selected, onChoose }: { sim: Sim; selected: boolean; onChoose: (id: string) => void }) {
  const can = sim.selectable
  return (
    <article className={'simcard' + (can ? '' : ' off') + (selected ? ' sel' : '')} data-testid={'sim-' + sim.id} aria-disabled={!can}>
      <div className="simcard-h"><SimBadge sim={sim} /><div><h3>{sim.name}</h3><span className={'chip ' + sim.status}>{sim.status_label}</span></div></div>
      <p>{sim.description}</p>
      <p className="mut small"><b>Collegamento:</b> {sim.how}</p>
      {can
        ? <button className="primary" onClick={() => onChoose(sim.id)} data-testid={'choose-' + sim.id}>{selected ? 'Scelto' : 'Scegli questo simulatore'}</button>
        : <button disabled>{sim.status === 'planned' ? 'In arrivo' : 'Da verificare'}</button>}
      <details><summary>Dettagli tecnici</summary>
        <dl className="tech">{Object.entries(sim.tech).map(([k, v]) => <div key={k}><dt>{TECH_LABEL[k] ?? k}</dt><dd>{v}</dd></div>)}</dl>
      </details>
    </article>)
}
const TECH_LABEL: Record<string, string> = { mechanism: 'Come si ottengono i dati', realtime: 'Dati in tempo reale', data: 'Dati disponibili', limits: 'Limiti', setup: 'Cosa serve nel gioco' }

/** Home: 1) pick the simulator (first start) 2) afterwards a single big card for the chosen one = the main way into the app. */
export default function Home({ go }: { go: (s: string) => void }) {
  const { data, error, choose, current } = useSims()
  const [changing, setChanging] = useState(false)
  const [info, setInfo] = useState<{ sessions: number; last: any } | null>(null)
  useEffect(() => {
    if (!data?.selected) return
    const load = () => api('/api/sessions').then(r => setInfo({ sessions: r.length, last: r[0] ?? null })).catch(() => {})
    load(); const t = setInterval(load, 5000); return () => clearInterval(t)
  }, [data?.selected])

  if (!data) return <section className="panel"><h2>Home</h2>{error ? <p className="bad">{error}</p> : <p className="mut">Caricamento…</p>}</section>
  const onChoose = async (id: string) => { await choose(id); setChanging(false) }
  const picking = data.first_run || changing

  return (<>
    {error && <p className="bad" data-testid="home-error">{error}</p>}
    {current && !picking && <ActiveSim go={go} onChange={() => setChanging(true)} info={info} />}
    {picking && (
      <section data-testid="sim-picker">
        <h2 className="hero">Scegli il tuo simulatore</h2>
        <p className="help">Seleziona il simulatore con cui giochi per iniziare a raccogliere e analizzare i tuoi dati di guida. Potrai cambiarlo in qualsiasi momento dal menu in alto a destra.</p>
        <p className="help"><b>Importante:</b> si possono scegliere solo i simulatori contrassegnati «Supportato», cioè quelli di cui l'app sa già leggere i dati. Gli altri sono in elenco per mostrarti cosa arriverà.</p>
        <div className="simgrid">{data.sims.map(s => <SimCard key={s.id} sim={s} selected={s.id === data.selected} onChoose={onChoose} />)}</div>
        {changing && <p><button onClick={() => setChanging(false)}>Annulla</button></p>}
      </section>)}
  </>)
}

function ActiveSim({ go, onChange, info }: { go: (s: string) => void; onChange: () => void; info: { sessions: number; last: any } | null }) {
  const { current, data } = useSims()
  if (!current) return null
  const c = data?.connection
  const connected = c?.state === 'ok'
  return (<>
    <section className="panel hero-card" data-testid="active-sim">
      <div className="hero-top">
        <SimBadge sim={current} size={84} />
        <div className="hero-main">
          <p className="eyebrow">Il tuo simulatore</p>
          <h2 className="hero" data-testid="active-sim-name">{current.name}</h2>
          <p className={'status ' + DOT[c?.state ?? 'waiting']} data-testid="active-sim-status"><i className={'dot ' + DOT[c?.state ?? 'waiting']} />{c?.label ?? 'Controllo in corso…'}</p>
          {c && !connected && <p className="mut">{c.detail}</p>}
        </div>
        <div className="hero-actions">
          <button className="primary big-btn" onClick={() => go('live')} data-testid="continue">{connected ? 'Apri simulatore' : 'Continua'}</button>
          <button onClick={onChange} data-testid="change-sim">Cambia simulatore</button>
        </div>
      </div>
      {!connected && current.steps.length > 0 && (
        <details open className="steps"><summary>Come collegare {current.name}</summary>
          <ol>{current.steps.map((s, i) => <li key={i}>{s}</li>)}</ol></details>)}
    </section>
    <div className="tiles">
      <section className="panel tile"><h3>Profilo caricato</h3>
        <p><b>{current.name}</b></p><p className="mut small">Impostazioni, sessioni e statistiche di questo gioco sono tenute separate da quelle degli altri simulatori.</p></section>
      <section className="panel tile"><h3>Raccolta dei dati</h3>
        <p><b>{connected ? 'Attiva' : 'In attesa del gioco'}</b></p>
        <p className="mut small">{info == null ? '…' : info.sessions === 0 ? 'Nessuna sessione registrata finora. Parte da sola quando entri in pista.' : `${info.sessions} ${info.sessions === 1 ? 'sessione registrata' : 'sessioni registrate'}. L'ultima: ${info.last.track || 'circuito sconosciuto'}.`}</p></section>
    </div>
    <h3 className="sect">Cosa vuoi fare?</h3>
    <div className="quick">
      <button onClick={() => go('live')}><b>Dati in diretta</b><span>Guarda cosa sta succedendo ora</span></button>
      <button onClick={() => go('sessions')}><b>Le tue sessioni</b><span>Rivedi e analizza le guide passate</span></button>
      <button onClick={() => go('ai')}><b>Ingegnere di pista</b><span>Fai domande e ricevi consigli</span></button>
      <button onClick={() => go('display')}><b>Schermo di guida</b><span>Mostra i consigli su un secondo schermo</span></button>
    </div>
  </>)
}
