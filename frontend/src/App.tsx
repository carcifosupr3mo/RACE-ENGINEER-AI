import { useEffect, useState } from 'react'
import { api } from './lib/api'
import { SimsProvider, useSims } from './lib/sims'
import Home from './components/Home'
import SimMenu from './components/SimMenu'
import UpdateGate, { UpdateBanner, useUpdate } from './components/UpdateGate'
import Updates from './components/Updates'
import Live from './components/Live'
import Sessions from './components/Sessions'
import LapAnalyzer from './components/LapAnalyzer'
import Engineer from './components/Engineer'
import TyreFuel from './components/TyreFuel'
import Driver from './components/Driver'
import SetupAdvisor from './components/SetupAdvisor'
import TrackAnalysis from './components/TrackAnalysis'
import AiSettings from './components/AiSettings'
import LanSettings from './components/LanSettings'
import DisplayInfo from './components/DisplayInfo'

// [id, label, one-line description shown under the title]. Ids are stable (tests and links use them), only the words are plain Italian.
export const SECTIONS: [string, string, string][] = [
  ['overview', 'Home', 'Scegli il simulatore e inizia.'],
  ['live', 'Dati in diretta', 'Cosa sta facendo l\'auto in questo momento.'],
  ['display', 'Schermo di guida', 'Consigli su un secondo schermo mentre guidi.'],
  ['sessions', 'Le tue sessioni', 'Tutte le guide registrate.'],
  ['laps', 'Analisi dei giri', 'Confronta due giri e scopri dove perdi tempo.'],
  ['track', 'Analisi del circuito', 'Le curve del circuito e come le affronti.'],
  ['ai', 'Ingegnere di pista', 'Fai domande sulla tua guida.'],
  ['setup', 'Assetto dell\'auto', 'Idee per regolare l\'auto.'],
  ['tyre', 'Gomme e benzina', 'Consumi e quando fermarti ai box.'],
  ['driver', 'I tuoi progressi', 'Come stai migliorando nel tempo.'],
  ['settings', 'Impostazioni', 'Aggiornamenti, rete e assistente AI.'],
]

export default function App() {
  return <SimsProvider><Shell /></SimsProvider>
}

function Shell() {
  const [sec, setSec] = useState('overview')
  const [session, setSession] = useState<string | null>(null)
  const [health, setHealth] = useState<any>(null)
  const upd = useUpdate()
  const { current } = useSims()
  useEffect(() => { api('/api/health').then(setHealth).catch(() => setHealth(null)) }, [])
  const openLaps = (sid: string) => { setSession(sid); setSec('laps') }
  const meta = SECTIONS.find(s => s[0] === sec)!
  return (
    <div className="shell">
      <nav aria-label="Menu principale">
        <h1>Race Engineer <b>AI</b></h1>
        {SECTIONS.map(([id, label]) => (
          <button key={id} className={sec === id ? 'on' : ''} onClick={() => setSec(id)} data-testid={'nav-' + id} aria-current={sec === id ? 'page' : undefined}>{label}</button>))}
      </nav>
      <div className="mainwrap">
        <header className="topbar">
          <div><h1 className="pagetitle">{meta[1]}</h1><p className="mut small">{meta[2]}</p></div>
          <SimMenu />
        </header>
        <main>
          <UpdateBanner st={upd.st} poll={upd.poll} />
          {sec === 'overview' && <Home go={setSec} />}
          {sec === 'live' && <Live />}
          {sec === 'display' && <DisplayInfo />}
          {sec === 'sessions' && <Sessions onOpen={openLaps} />}
          {sec === 'laps' && <LapAnalyzer sessionId={session} onPick={setSession} />}
          {sec === 'setup' && <SetupAdvisor sessionId={session} onPick={setSession} />}
          {sec === 'track' && <TrackAnalysis sessionId={session} onPick={setSession} />}
          {sec === 'ai' && <Engineer sessionId={session} onPick={setSession} />}
          {sec === 'tyre' && <TyreFuel sessionId={session} onPick={setSession} />}
          {sec === 'driver' && <Driver sessionId={session} onPick={setSession} />}
          {sec === 'settings' && <Settings health={health} sim={current?.name ?? null} upd={upd} />}
        </main>
      </div>
      <UpdateGate st={upd.st} lost={upd.lost} poll={upd.poll} />
    </div>
  )
}

function Settings({ health, sim, upd }: { health: any; sim: string | null; upd: ReturnType<typeof useUpdate> }) {
  return (<>
    <section className="panel"><h2>Il tuo simulatore</h2>
      <div className="row"><span>Simulatore in uso</span><b>{sim ?? 'Nessuno scelto'}</b></div>
      <p className="help">Per cambiarlo usa il menu «Simulatore» in alto a destra. La scelta viene ricordata ogni volta che apri l'app, anche dopo un aggiornamento.</p>
      <div className="row"><span>Accesso da altri dispositivi</span><span>{health?.lan_enabled ? 'Attivo (serve un codice)' : 'Spento: solo questo PC'}</span></div>
    </section>
    <Updates st={upd.st} poll={upd.poll} />
    <LanSettings />
    <AiSettings />
  </>)
}
