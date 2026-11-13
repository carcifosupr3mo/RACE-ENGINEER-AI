import { useEffect, useState } from 'react'
import TrackMap from './TrackMap'
import { useEngineerStream } from './useEngineerStream'
import { deltaClass, fmtDelta, fmtTime, gearLabel, levelClass } from './format'
import './display.css'

/** Driving Display = a presentation mode of the SAME app. It computes nothing: every number comes from the shared engineer state. */
export default function DrivingDisplay() {
  const st = useEngineerStream()
  const [full, setFull] = useState(!!document.fullscreenElement)
  const toggleFull = () => { try { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen() } catch { /* not supported */ } }
  useEffect(() => {      // F = fullscreen (also for kiosk-less browsers on a tablet/Raspberry); screen kept awake when the browser allows it
    const onFs = () => setFull(!!document.fullscreenElement)
    const onKey = (ev: KeyboardEvent) => { if ((ev.key === 'f' || ev.key === 'F') && !ev.ctrlKey && !ev.metaKey && !ev.altKey) toggleFull() }
    let lock: any = null
    const wake = () => { try { (navigator as any).wakeLock?.request('screen').then((l: any) => { lock = l }).catch(() => {}) } catch { /* optional */ } }
    wake()
    const onVis = () => { if (document.visibilityState === 'visible') wake() }
    document.addEventListener('fullscreenchange', onFs); window.addEventListener('keydown', onKey); document.addEventListener('visibilitychange', onVis)
    return () => { document.removeEventListener('fullscreenchange', onFs); window.removeEventListener('keydown', onKey); document.removeEventListener('visibilitychange', onVis); try { lock?.release() } catch { /* ignore */ } }
  }, [])
  const [sel, setSel] = useState<string | null>(null)
  const e = st.engineer, inp = e?.inputs, d = e?.delta, c = e?.corner, sug = e?.suggestion
  const offline = !st.connected || st.stale
  const synth = !!(e?.synthetic || st.status?.synthetic)
  const acquiring = e?.connection?.acquiring
  const rpmFrac = inp?.rpm != null && inp?.max_rpm ? Math.min(1, inp.rpm / inp.max_rpm) : 0
  const selCorner = sel && st.map?.available ? st.map.corners.find((x: any) => x.id === sel) : null
  const selTarget = sel && st.map?.available ? st.map.targets?.find((x: any) => x.corner === sel) : null
  return (
    <div className={'drv' + (offline ? ' offline' : '') + (sug?.frozen ? ' busy' : '')} data-testid="driving-display">
      {synth && <div className="d-synth" data-testid="display-synth-banner">DATI SINTETICI — NON PROVENGONO DA LE MANS ULTIMATE</div>}
      <header className="d-top">
        <span className={'d-dot ' + (offline ? 'bad' : acquiring ? 'ok' : 'wait')} />
        <b data-testid="display-conn">{offline ? (st.everConnected ? 'CONNESSIONE PERSA — riconnessione…' : 'In attesa del PC…') : acquiring ? 'LIVE' : (st.status?.state_label || 'In attesa di LMU')}</b>
        <span className="d-mut">{e?.session?.track || '–'} · {e?.session?.vehicle || '–'}</span>
        <span className="d-chip" data-testid="display-mode" title={e?.session?.mode?.reason}>{e?.session?.mode?.label || '–'}</span>
        <span className="d-chip" data-testid="display-ref">rif. {e?.reference?.reliability?.level ?? '–'} · {e?.reference?.laps ?? 0} giri</span>
        <button className="d-link d-fs" data-testid="display-fullscreen" onClick={toggleFull} title="Tutto schermo (tasto F)">{full ? 'esci da tutto schermo' : 'tutto schermo'}</button>
        <a className="d-link" href="/app/">dashboard</a>
      </header>
      {offline && <div className="d-offline" data-testid="display-offline" role="alert">{st.everConnected ? 'Nessun dato dal PC: valori in pausa (ultimo stato mostrato attenuato)'
        : st.authError === 'missing' ? 'Il PC ti riconosce ma serve il codice di accesso: apri l\'indirizzo COMPLETO mostrato sul PC in Impostazioni → Display in rete (finisce con ?token=…), oppure copialo da lì.'
        : st.authError === 'wrong' ? 'Codice di accesso non valido (forse l\'app è stata riavviata o il codice è cambiato): riapri l\'indirizzo aggiornato mostrato sul PC in Impostazioni → Display in rete.'
        : 'Connessione al PC in corso…'}</div>}
      <div className="d-body">
        <section className="d-coach">
          <Corner c={c} />
          <Coach sug={sug} review={e?.review} calm={inp?.speed_kmh != null && inp.speed_kmh < CALM_KMH} />
          <Alerts alerts={e?.alerts} />
          <div className="d-last d-mut" data-testid="display-lastlap">
            ultimo {fmtTime(e?.lap?.last_s)} · migliore {fmtTime(e?.lap?.best_s)}
            {e?.last_lap?.delta_s != null && <> · giro {e.last_lap.lap}: {fmtDelta(e.last_lap.delta_s)} s</>}
          </div>
        </section>
        <section className="d-side">
          <div className={'d-delta ' + deltaClass(d?.to_ref_s)} data-testid="display-delta">
            <small>DELTA vs RIFERIMENTO{d?.ref_lap ? ` (giro ${d.ref_lap})` : ''}</small>
            <div>{d?.available ? fmtDelta(d.to_ref_s) : '–'}</div>
          </div>
          <div className="d-row3">
            <div className="d-box"><small>km/h</small><div data-testid="display-speed">{inp?.speed_kmh != null ? Math.round(inp.speed_kmh) : '–'}</div></div>
            <div className="d-box gear"><small>marcia</small><div data-testid="display-gear">{gearLabel(inp?.gear)}</div></div>
            <div className="d-box"><small>giro</small><div data-testid="display-lap">{e?.lap?.number ?? '–'}</div></div>
          </div>
          <div className="d-rpm" aria-label="giri motore"><i style={{ width: `${rpmFrac * 100}%` }} className={rpmFrac > 0.93 ? 'red' : ''} /></div>
          <div className="d-pedals">
            <Pedal label="gas" v={inp?.throttle} cls="thr" /><Pedal label="freno" v={inp?.brake} cls="brk" />
          </div>
          <div className="d-mapwrap">
            <TrackMap map={st.map} pos={e?.position ?? null} trail={st.trail} current={c?.current ?? null} next={c?.next ?? null} selected={sel} onSelect={setSel} />
            {selCorner && (
              <div className="d-corner-card" data-testid="corner-card">
                <b>Curva {selCorner.name || selCorner.id}</b>{selCorner.provisional && <span className="d-mut"> (numerazione provvisoria)</span>}
                <div>freno da {selCorner.entry_m.toFixed(0)} m · apice {selCorner.apex_m.toFixed(0)} m · vel. min {selCorner.min_speed_kmh?.toFixed?.(0) ?? '–'} km/h</div>
                {selTarget && <div className="d-mut">miglior passaggio: giro {selTarget.best_lap} · {selTarget.best_zone_s.toFixed(3)} s{selTarget.gain_vs_anchor_s ? ` (−${selTarget.gain_vs_anchor_s.toFixed(3)} s vs riferimento)` : ''}</div>}
              </div>)}
          </div>
        </section>
      </div>
    </div>)
}

function Pedal({ label, v, cls }: { label: string, v: number | null | undefined, cls: string }) {
  return <div className={'d-pedal ' + cls}><small>{label} {v != null ? Math.round(v * 100) + '%' : '–'}</small><div><i style={{ height: `${(v ?? 0) * 100}%` }} /></div></div>
}

function Corner({ c }: { c: any }) {
  return (
    <div className="d-corner" data-testid="display-corner">
      <span>{c?.current ? <>in curva <b>{c.current}</b> · {c.phase}</> : <>prossima <b>{c?.next ?? '–'}</b>{c?.dist_to_next_m != null ? ` tra ${c.dist_to_next_m.toFixed(0)} m` : ''}</>}</span>
    </div>)
}

/** The ONE main instruction (what / where / how / why / goal) or, between laps, the end-of-lap review. Everything comes from the shared state. */
const CALM_KMH = 30      // below this (pits, stopped, very slow) the long explanation is allowed; while driving only the short instruction is shown
function Coach({ sug, review, calm }: { sug: any, review: any, calm: boolean }) {
  if (!sug) return <div className="d-sug learning" data-testid="display-suggestion">In attesa dei dati…</div>
  if (sug.state === 'learning') return <div className="d-sug learning" data-testid="display-suggestion"><small>APPRENDIMENTO</small><div className="txt">{sug.learning?.message ?? 'Sto imparando il circuito'}</div></div>
  const m = sug.main, i = m?.instruction
  const showReview = !!review?.visible && !sug.frozen && review?.summary
  return (
    <>
      {showReview && (
        <div className="d-review" data-testid="display-review">
          <small>ANALISI GIRO {review.lap}{review.synthetic ? ' · DATI SINTETICI' : ''}{review.comparable === false ? ' · NON CONFRONTABILE' : ''}</small>
          <div className="rv-sum" data-testid="display-review-summary">{calm ? review.summary : String(review.summary).split('. ')[0] + '.'}</div>
        </div>)}
      {!m ? <div className="d-sug quiet" data-testid="display-suggestion"><small>ISTRUZIONE</small><div className="txt">Nessun miglioramento significativo rilevato</div></div> : (
        <div className={'d-sug ' + (sug.frozen ? 'frozen' : '')} data-testid="display-suggestion">
          <small>{i?.corner_label ?? 'ISTRUZIONE'}{sug.frozen ? ' · in guida' : ''}{i?.status && i.status !== 'nuovo' ? ` · ${i.status}` : ''}</small>
          <div className="txt" data-testid="display-suggestion-text">{i?.text ?? m.text}</div>
          {i && !sug.frozen && (
            <div className="d-detail" data-testid="display-instruction">
              <div className="d-how">{i.how}</div>
              {calm && (
                <div data-testid="display-explain">
                  {i.why && <div className="d-mut">Perché: {i.why}</div>}
                  {i.goal && <div className="d-goal">Obiettivo: {i.goal}</div>}
                  {i.habit_note && <div className="d-note" data-testid="display-habit">{i.habit_note}</div>}
                  {i.reassessment && <div className="d-note warn" data-testid="display-reassess">{i.reassessment}</div>}
                </div>)}
            </div>)}
          <div className="meta"><span className={'d-chip ' + levelClass(m.confidence?.level)}>affidabilità {m.confidence?.level}</span>
            {m.impact_s != null && <span className="d-mut">perdi {m.impact_s.toFixed(2)} s</span>}{m.repeat > 1 && <span className="d-mut">× {m.repeat} giri</span>}</div>
        </div>)}
    </>)
}

function Alerts({ alerts }: { alerts: any[] | undefined }) {
  if (!alerts?.length) return null
  return <div className="d-alerts" data-testid="display-alerts">{alerts.slice(0, 3).map(a => <div key={a.id} className={'d-alert ' + a.level}>{a.text}</div>)}</div>
}
