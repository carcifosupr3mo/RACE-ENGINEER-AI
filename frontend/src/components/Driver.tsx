import { useEffect, useState } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { api } from '../lib/api'
import { fmtTime } from '../lib/transform'
import SessionPicker from './SessionPicker'

export default function Driver({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [period, setPeriod] = useState('week')
  const [synth, setSynth] = useState(true)
  const [hist, setHist] = useState<any>(null)
  const [goals, setGoals] = useState<any[]>([])
  const [plan, setPlan] = useState<any>(null)
  const [form, setForm] = useState({ track: '', metric: 'best_lap_s', target: 0 })
  const [msg, setMsg] = useState('')
  const load = () => { api(`/api/driver/history?period=${period}&include_synthetic=${synth}`).then(setHist); api('/api/driver/goals').then(setGoals) }
  useEffect(load, [period, synth])
  useEffect(() => { setPlan(null); if (sessionId) api(`/api/sessions/${sessionId}/training`).then(setPlan).catch(e => setMsg(e.message)) }, [sessionId])
  useEffect(() => {
    const el = document.getElementById('hist-chart'); if (!el || !hist?.groups.length) return
    Plotly.react(el, hist.groups.map((g: any) => ({ x: g.series.map((s: any) => s.period), y: g.series.map((s: any) => s.best_time_s), mode: 'lines+markers', name: `${g.track}`, })),
      { height: 240, margin: { l: 50, r: 10, t: 10, b: 40 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#0e1216', font: { color: '#aab6c2', size: 10 }, yaxis: { title: 'miglior giro (s)', gridcolor: '#1b222a' }, xaxis: { gridcolor: '#1b222a' } }, { displayModeBar: false, responsive: true })
  }, [hist])
  const addGoal = async () => {
    try { await api(`/api/driver/goals?track=${encodeURIComponent(form.track)}&metric=${form.metric}&target=${form.target}`, { method: 'POST' }); setMsg('Obiettivo creato'); load() }
    catch (e: any) { setMsg('Non è stato possibile creare l\'obiettivo. ' + e.message) }
  }
  return (
    <section className="panel" data-testid="driver">
      <h2>I tuoi progressi</h2>
      <p className="help">Cosa allenare con priorità, in base ai tuoi giri registrati.</p>
      <div className="toolbar">
        <label className="inl">Periodo <select value={period} onChange={e => setPeriod(e.target.value)}><option value="day">giornaliero</option><option value="week">settimanale</option><option value="month">mensile</option></select></label>
        <label className="inl"><input type="checkbox" checked={synth} onChange={e => setSynth(e.target.checked)} /> includi sintetici</label></div>
      {hist?.groups.length ? <><div id="hist-chart" /> {hist.groups.map((g: any) => <p key={g.track + g.vehicle} className="mut">{g.track} · {g.vehicle}: {g.sessions.length} sessioni, miglior giro {fmtTime(Math.min(...g.sessions.map((s: any) => s.best_time_s)))}</p>)}</> : <p className="mut">Nessuna sessione con giri validi nello storico.</p>}
      <h3>Obiettivi</h3>
      <div className="toolbar"><input placeholder="Circuito (esatto)" value={form.track} onChange={e => setForm({ ...form, track: e.target.value })} />
        <select value={form.metric} onChange={e => setForm({ ...form, metric: e.target.value })}><option value="best_lap_s">miglior giro ≤ s</option><option value="lap_std_s">dev. std giri ≤ s</option><option value="slow_corner_loss_s">perdita media curve lente ≤ s</option></select>
        <input type="number" step={0.01} value={form.target} onChange={e => setForm({ ...form, target: +e.target.value })} style={{ width: 90 }} /><button onClick={addGoal} disabled={!form.track}>Crea</button></div>
      {goals.map(g => <div className="row" key={g.id}><span>{g.track} · {g.metric} ≤ {g.target}</span><span className="mono">{g.current != null ? g.current.toFixed(3) : 'nessun dato'} {g.progress != null ? `· ${(g.progress * 100).toFixed(0)}%` : ''} {g.achieved ? '✔' : ''}</span></div>)}
      <h3>Allenamento sui punti deboli misurati</h3>
      <SessionPicker value={sessionId} onChange={onPick} />
      {plan && (plan.available ? plan.items.length ? plan.items.map((it: any, i: number) => <div key={i} className="msg"><b>{it.title}</b><div className="mut">{it.drill}</div>
        <div className="mono mut">perdita media {it.facts.mean_loss_vs_best_lap_s?.toFixed(3) ?? '–'} s · σ frenata {it.facts.brake_start_std_m ?? '–'} m · σ v.min {it.facts.min_speed_std_kmh ?? '–'} km/h · {it.facts.laps_compared} giri</div></div>)
        : <p className="mut">Nessun punto debole oltre soglia.</p> : <p className="warn">Non disponibile: {plan.reason}</p>)}
      {msg && <p className="mut">{msg}</p>}
    </section>)
}
