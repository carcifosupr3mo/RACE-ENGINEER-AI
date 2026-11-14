import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

export type UpdateStatus = {
  state: string; current: string; latest: string | null; notes: string; progress: number | null; bytes: number; total: number; step: number
  message: string; error: string | null; error_code: string | null; auto: boolean; dismissed: boolean; can_install: boolean; manual_reason: string
  releases_url: string; release_url: string | null; last_result: { ok: boolean; from: string; to: string; error: string | null; rolled_back: boolean } | null
}
const BUSY = ['checking', 'downloading', 'verifying', 'installing', 'restarting']
export const STEPS = ['Controllo aggiornamenti', 'Download della nuova versione', 'Verifica dell\'integrità', 'Installazione', 'Riavvio dell\'app']
const mb = (n: number) => (n / 1e6).toFixed(1) + ' MB'

/** Polls the update state. Fast while work is running, slow otherwise; keeps trying while the app restarts. */
export function useUpdate() {
  const [st, setSt] = useState<UpdateStatus | null>(null)
  const [lost, setLost] = useState(false)
  const stRef = useRef<UpdateStatus | null>(null)
  const timer = useRef<any>(null)
  const count = useRef(0)
  const alive = useRef(true)
  const tick = () => {
    clearTimeout(timer.current)
    api('/api/update/status').then((s: UpdateStatus) => { stRef.current = s; setSt(s); setLost(false) }).catch(() => setLost(true)).finally(() => {
      if (!alive.current) return
      count.current++
      const busy = stRef.current && BUSY.includes(stRef.current.state)
      timer.current = setTimeout(tick, busy ? 400 : count.current < 20 ? 1500 : 30000)       // the start-up check runs in the background: look again a few times
    })
  }
  useEffect(() => { alive.current = true; tick(); return () => { alive.current = false; clearTimeout(timer.current) } }, [])
  return { st, lost, poll: tick, setSt }
}

export function UpdateBanner({ st, poll }: { st: UpdateStatus | null; poll: () => void }) {
  const r = st?.last_result
  if (!r) return null
  const done = async () => { await api('/api/update/ack', { method: 'POST' }).catch(() => {}); poll() }
  return (
    <div className={'banner ' + (r.ok ? 'okb' : 'badb')} role="status" data-testid="update-result">
      <span>{r.ok ? `Aggiornamento completato: ora usi la versione ${r.to}. I tuoi dati e le tue impostazioni sono rimasti al loro posto.`
        : `${r.error ?? "L'aggiornamento non è riuscito."} ${r.rolled_back ? 'Stai usando la versione precedente, funziona come prima.' : ''}`}</span>
      <button onClick={done}>OK</button>
    </div>)
}

/** Centre pop-up (auto updates OFF) and the dedicated update screen (while an update runs). */
export default function UpdateGate({ st, lost, poll }: { st: UpdateStatus | null; lost: boolean; poll: () => void }) {
  const [err, setErr] = useState('')
  const [started, setStarted] = useState(false)
  if (!st) return null
  const working = ['downloading', 'verifying', 'installing', 'restarting'].includes(st.state)
  const failed = st.state === 'error' && st.error_code !== 'offline' && (started || st.step >= 2)
  const start = async () => { setErr(''); setStarted(true); try { await api('/api/update/start', { method: 'POST' }); poll() } catch (e: any) { setErr(e.message); setStarted(false) } }
  const skip = async () => { await api('/api/update/skip', { method: 'POST' }).catch(() => {}); poll() }

  if (working || failed) return <UpdateScreen st={st} lost={lost} err={err} retry={start} close={skip} />
  if (st.state === 'available' && !st.dismissed && (!st.auto || !st.can_install)) {
    const manual = !st.can_install
    return (
      <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="upd-title" data-testid="update-popup">
        <div className="modal">
          <h2 id="upd-title" className="hero">Nuovo aggiornamento disponibile</h2>
          <p>È disponibile una nuova versione dell'applicazione. Vuoi installarla adesso?</p>
          <div className="versions"><div><span className="mut">Versione installata</span><b>{st.current}</b></div><div><span className="mut">Nuova versione</span><b className="ok">{st.latest}</b></div></div>
          {st.notes && <><h3>Novità</h3><pre className="notes" data-testid="update-notes">{st.notes}</pre></>}
          {manual && <p className="warn">{st.manual_reason}</p>}
          {err && <p className="bad">{err}</p>}
          <div className="btns">
            {manual ? <a className="btn primary" href={st.release_url ?? st.releases_url} target="_blank" rel="noreferrer">Apri la pagina di download</a>
              : <button className="primary" onClick={start} data-testid="update-go">AGGIORNA</button>}
            <button onClick={skip} data-testid="update-skip">SALTA PER ORA</button>
          </div>
          <p className="mut small">I tuoi dati, le sessioni e le impostazioni non vengono toccati dall'aggiornamento.</p>
        </div>
      </div>)
  }
  return null
}

function UpdateScreen({ st, lost, err, retry, close }: { st: UpdateStatus; lost: boolean; err: string; retry: () => void; close: () => void }) {
  const failed = st.state === 'error'
  const pct = st.progress == null ? null : Math.round(st.progress * 100)
  const step = failed ? Math.max(1, st.step) : st.step
  return (
    <div className="overlay full" role="dialog" aria-modal="true" aria-labelledby="upd-h" data-testid="update-screen">
      <div className="modal wide">
        <h2 id="upd-h" className="hero">{failed ? "L'aggiornamento non è riuscito" : 'Aggiornamento in corso'}</h2>
        <div className="versions"><div><span className="mut">Versione attuale</span><b>{st.current}</b></div><div><span className="mut">Nuova versione</span><b className="ok">{st.latest}</b></div></div>
        <ol className="stepper">{STEPS.map((s, i) => <li key={s} className={failed && i + 1 === step ? 'bad' : i + 1 < step ? 'done' : i + 1 === step ? 'now' : ''}>{s}</li>)}</ol>
        {!failed && <>
          <div className="progress" role="progressbar" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}><i style={{ width: (pct ?? (st.state === 'restarting' ? 100 : 0)) + '%' }} /></div>
          <p className="status" data-testid="update-message">{st.message}{pct != null && st.state !== 'restarting' ? ` ${pct}%` : ''}{st.state === 'downloading' && st.total ? ` (${mb(st.bytes)} di ${mb(st.total)})` : ''}</p>
          {(st.state === 'restarting' || lost) && <p className="mut">L'app si chiude e si riapre da sola. Se dopo un minuto non vedi nulla, riaprila dal collegamento sul desktop: l'aggiornamento riprende da dove era.</p>}
        </>}
        {failed && <>
          <p className="bad" data-testid="update-error">{st.error ?? err}</p>
          <p className="mut">Non preoccuparti: l'app non è stata modificata e puoi continuare a usarla come prima.</p>
          <div className="btns"><button className="primary" onClick={retry}>Riprova</button><button onClick={close}>Continua senza aggiornare</button></div>
        </>}
      </div>
    </div>)
}
