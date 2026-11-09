import { useEffect, useState } from 'react'
import { api } from './lib/api'
import Live from './components/Live'
import Sessions from './components/Sessions'
import LapAnalyzer from './components/LapAnalyzer'

const SECTIONS: [string, string, number | null][] = [
  ['overview', 'Overview', null], ['live', 'Live Telemetry', null], ['sessions', 'Sessions', null],
  ['laps', 'Lap Analyzer', null], ['track', 'Track Analysis', 3], ['ai', 'Race Engineer AI', 4],
  ['setup', 'Setup Advisor', 5], ['tyre', 'Tyre & Fuel', 6], ['driver', 'Driver Development', 7], ['settings', 'Settings', null],
]

function Planned({ phase, name }: { phase: number; name: string }) {
  return <section className="panel"><h2>{name}</h2><p className="mut">Non ancora implementato (Fase {phase} della roadmap). Nessun dato è mostrato finché la funzione non esiste.</p></section>
}

export default function App() {
  const [sec, setSec] = useState('overview')
  const [session, setSession] = useState<string | null>(null)
  const [health, setHealth] = useState<any>(null)
  useEffect(() => { api('/api/health').then(setHealth).catch(() => setHealth(null)) }, [])
  const openLaps = (sid: string) => { setSession(sid); setSec('laps') }
  return (
    <div className="shell">
      <nav>
        <h1>Race Engineer <b>AI</b></h1>
        {SECTIONS.map(([id, label, ph]) => (
          <button key={id} className={sec === id ? 'on' : ''} onClick={() => setSec(id)} data-testid={'nav-' + id}>
            {label}{ph ? <span className="phase">F{ph}</span> : null}
          </button>))}
      </nav>
      <main>
        {sec === 'overview' && <Overview health={health} go={setSec} />}
        {sec === 'live' && <Live />}
        {sec === 'sessions' && <Sessions onOpen={openLaps} />}
        {sec === 'laps' && <LapAnalyzer sessionId={session} onPick={setSession} />}
        {sec === 'settings' && <Settings health={health} />}
        {SECTIONS.filter(s => s[2] && s[0] === sec).map(s => <Planned key={s[0]} phase={s[2]!} name={s[1]} />)}
      </main>
    </div>
  )
}

function Overview({ health, go }: { health: any; go: (s: string) => void }) {
  return (
    <section className="panel">
      <h2>Overview</h2>
      <p>Backend: {health ? <span className="ok">online · v{health.version} · {health.platform}</span> : <span className="bad">non raggiungibile</span>}</p>
      <p className="mut">Stato della verifica: l'acquisizione da Le Mans Ultimate reale <b>non è ancora verificata</b>. I dati sintetici sono sempre marcati.</p>
      <button onClick={() => go('live')}>Live Telemetry</button> <button onClick={() => go('sessions')}>Sessions</button>
    </section>)
}

function Settings({ health }: { health: any }) {
  return (
    <section className="panel"><h2>Settings</h2>
      <div className="row"><span>Accesso LAN</span><span>{health?.lan_enabled ? 'ATTIVO (token richiesto)' : 'disattivato (solo localhost)'}</span></div>
      <p className="mut">LAN si attiva solo avviando il backend con <code>--lan</code>. Provider AI, obiettivi e profili: fasi successive.</p>
    </section>)
}
