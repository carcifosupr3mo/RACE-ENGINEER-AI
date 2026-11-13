import { useEffect, useMemo, useRef, useState } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { api } from '../lib/api'
import { deltaSeries, findingLabel, findingText, fmtTime, nearestIndex } from '../lib/transform'

const CH: { key: string; title: string; unit: string }[] = [
  { key: 'speed_kmh', title: 'Velocità', unit: 'km/h' }, { key: 'throttle', title: 'Acceleratore', unit: '0–1' },
  { key: 'brake', title: 'Freno', unit: '0–1' }, { key: 'steering', title: 'Sterzo', unit: '−1…1' },
  { key: 'rpm', title: 'RPM', unit: 'rpm' }, { key: 'gear', title: 'Marcia', unit: '' }, { key: 'delta', title: 'Delta tempo', unit: 's (+ = più lento)' },
]
const LAP_COLOR = '#38bdf8', REF_COLOR = '#ffb020'

export default function LapAnalyzer({ sessionId, onPick }: { sessionId: string | null; onPick: (id: string) => void }) {
  const [sessions, setSessions] = useState<any[]>([])
  const [laps, setLaps] = useState<any>(null)
  const [lap, setLap] = useState<number | null>(null)
  const [ref, setRef] = useState<number | null>(null)
  const [cmp, setCmp] = useState<any>(null)
  const [driving, setDriving] = useState<any>(null)
  const [trace, setTrace] = useState<any>(null)
  const [corners, setCorners] = useState<any>(null)
  const [err, setErr] = useState('')
  const [cursor, setCursor] = useState<number | null>(null)
  const [report, setReport] = useState<any>(null)
  const [repErr, setRepErr] = useState('')

  useEffect(() => { api('/api/sessions').then(r => setSessions(r.filter((s: any) => s.status !== 'recording'))) }, [])
  useEffect(() => {
    setLaps(null); setCmp(null); setTrace(null); setErr(''); setLap(null); setRef(null); setReport(null); setRepErr('')
    if (!sessionId) return
    api(`/api/sessions/${sessionId}/report`).then(setReport).catch(e => setRepErr(e.message))
    api(`/api/sessions/${sessionId}/laps`).then(r => {
      setLaps(r)
      const valid = r.laps.filter((l: any) => l.valid_for_analysis)
      setRef(r.summary.best_lap ?? null)
      setLap(valid.find((l: any) => l.number !== r.summary.best_lap)?.number ?? r.summary.best_lap ?? null)
    }).catch(e => setErr(e.message))
  }, [sessionId])
  useEffect(() => {
    if (!sessionId || lap == null || ref == null) return
    setErr('')
    Promise.all([
      api(`/api/sessions/${sessionId}/compare?lap=${lap}&ref=${ref}`),
      api(`/api/sessions/${sessionId}/trace?laps=${lap},${ref}&step=2`),
      api(`/api/sessions/${sessionId}/corners?ref=${ref}`),
      api(`/api/sessions/${sessionId}/driving?lap=${lap}&ref=${ref}`).catch(() => null),
    ]).then(([c, t, k, d]) => { setCmp(c); setTrace(t); setCorners(k); setDriving(d) }).catch(e => { setErr(e.message); setCmp(null); setTrace(null) })
  }, [sessionId, lap, ref])

  return (
    <section className="panel" data-testid="lap-analyzer">
      <h2>Analisi dei giri</h2>
      <p className="help">Guarda com'è andata la sessione (riepilogo qui sotto), poi scegli due giri per vedere in quale punto della pista perdi o guadagni tempo.</p>
      <div className="toolbar">
        <label>Sessione <select value={sessionId ?? ''} onChange={e => onPick(e.target.value)} data-testid="session-select">
          <option value="">—</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.is_synthetic ? '[SINT] ' : ''}{s.track} · {s.session_type} · {s.samples} camp.</option>)}</select></label>
        {laps && <>
          <label>Giro <select value={lap ?? ''} onChange={e => setLap(+e.target.value)} data-testid="lap-select">
            {laps.laps.filter((l: any) => l.valid_for_analysis).map((l: any) => <option key={l.number} value={l.number}>{l.number} · {fmtTime(l.time_s)}</option>)}</select></label>
          <label>Riferimento <select value={ref ?? ''} onChange={e => setRef(+e.target.value)} data-testid="ref-select">
            {laps.laps.filter((l: any) => l.valid_for_analysis).map((l: any) => <option key={l.number} value={l.number}>{l.number} · {fmtTime(l.time_s)}</option>)}</select></label></>}
      </div>
      {err && <p className="bad" data-testid="error">{err}</p>}
      {laps && <LapTable laps={laps} />}
      {report && <Report r={report} onPick={setLap} />}
      {repErr && <p className="mut" data-testid="report-error">Riepilogo sessione non disponibile: {repErr}</p>}
      {cmp && trace && corners && trace.laps[cmp.lap] && trace.laps[cmp.ref_lap] && <Analysis cmp={cmp} trace={trace} corners={corners} driving={driving} lap={cmp.lap} ref_={cmp.ref_lap} cursor={cursor} setCursor={setCursor} />}
    </section>)
}

function LapTable({ laps }: { laps: any }) {
  const s = laps.summary
  return (
    <div className="lapbox">
      <table data-testid="lap-table"><thead><tr><th>Giro</th><th>Tempo</th><th>Origine tempo</th><th>Stato</th><th>Motivi / note</th></tr></thead>
        <tbody>{laps.laps.map((l: any) => <tr key={l.number} className={l.valid_for_analysis ? '' : 'dim'}>
          <td>{l.number}</td><td>{fmtTime(l.time_s)}</td><td>{l.time_source}</td><td><span className={'tag ' + l.status}>{l.status}</span></td><td>{l.reasons.join(', ')}{l.notes?.length ? <span className="mut"> {l.reasons.length ? '· ' : ''}{l.notes.join(', ')}</span> : null}</td></tr>)}</tbody></table>
      <p className="mut">Migliore: giro {s.best_lap ?? '–'} ({fmtTime(s.best_time_s)}) · media {fmtTime(s.mean_time_s)} · dev.std {s.std_time_s != null ? s.std_time_s.toFixed(3) + ' s' : '–'} — calcolate solo su {s.laps_valid} giri validi (completi, senza pit, non invalidati).</p>
    </div>)
}

function Analysis({ cmp, trace, corners, driving, lap, ref_, cursor, setCursor }: any) {
  const grid: number[] = trace.distance_m
  const L = trace.laps[lap], R = trace.laps[ref_]
  const divs = useRef<Record<string, HTMLDivElement | null>>({})
  const mapDiv = useRef<HTMLDivElement | null>(null)
  const syncing = useRef(false)
  const delta = useMemo(() => deltaSeries(L.t, R.t), [L, R])
  const deltaMax = useMemo(() => Math.max(0, ...delta.filter((x): x is number => x != null).map(Math.abs)), [delta])
  const qualityBad = !L.quality.ok || !R.quality.ok

  useEffect(() => {
    const keys = CH.map(c => c.key)
    keys.forEach((k, idx) => {
      const el = divs.current[k]; if (!el) return
      const series = k === 'delta' ? [{ x: grid, y: delta, name: `Δ giro ${lap} vs ${ref_}`, line: { color: '#ff4d4f', width: 1.5 }, connectgaps: false }]
        : [{ x: grid, y: L[k], name: `Giro ${lap}`, line: { color: LAP_COLOR, width: 1.5, shape: k === 'gear' ? 'hv' : 'linear' }, connectgaps: false },
           { x: grid, y: R[k], name: `Rif. ${ref_}`, line: { color: REF_COLOR, width: 1.2, dash: 'dot', shape: k === 'gear' ? 'hv' : 'linear' }, connectgaps: false }]
      const shapes = corners.corners.map((c: any) => ({ type: 'rect', xref: 'x', yref: 'paper', x0: c.entry_m, x1: c.exit_m, y0: 0, y1: 1, fillcolor: 'rgba(120,140,160,0.10)', line: { width: 0 }, layer: 'below' }))
      const ann = idx === 0 ? corners.corners.map((c: any) => ({ x: c.apex_m, y: 1, yref: 'paper', text: c.name ?? c.id, showarrow: false, font: { size: 10, color: '#8593a1' }, yanchor: 'bottom' })) : []
      Plotly.react(el, series, {
        height: k === 'speed_kmh' ? 190 : 120, margin: { l: 52, r: 10, t: idx === 0 ? 18 : 4, b: idx === CH.length - 1 ? 30 : 4 },
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#0e1216', font: { color: '#aab6c2', size: 10 }, showlegend: idx === 0,
        legend: { orientation: 'h', y: 1.25, x: 0 }, hovermode: 'x', shapes, annotations: ann,
        xaxis: { gridcolor: '#1b222a', showticklabels: idx === CH.length - 1, title: idx === CH.length - 1 ? 'Distanza giro (m)' : undefined, zeroline: false },
        yaxis: { gridcolor: '#1b222a', title: { text: CH[idx].unit, font: { size: 9 } }, zeroline: k === 'delta', ...(k === 'delta' && deltaMax < 0.05 ? { range: [-0.05, 0.05] } : {}) },
      }, { displayModeBar: false, responsive: true })
      const any = el as any
      any.removeAllListeners?.('plotly_hover'); any.removeAllListeners?.('plotly_relayout'); any.removeAllListeners?.('plotly_unhover')
      any.on('plotly_hover', (e: any) => {
        const i = e.points?.[0]?.pointIndex; if (i == null) return
        setCursor(i)
        keys.forEach(o => { if (o !== k && divs.current[o]) try { Plotly.Fx.hover(divs.current[o], [{ curveNumber: 0, pointNumber: i }]) } catch { /* ignore */ } })
      })
      any.on('plotly_relayout', (e: any) => {
        if (syncing.current || e['xaxis.range[0]'] === undefined && !e['xaxis.autorange']) return
        syncing.current = true
        const upd = e['xaxis.autorange'] ? { 'xaxis.autorange': true } : { 'xaxis.range': [e['xaxis.range[0]'], e['xaxis.range[1]']] }
        Promise.all(keys.filter(o => o !== k).map(o => Plotly.relayout(divs.current[o], upd))).finally(() => { syncing.current = false })
      })
    })
  }, [grid, L, R, delta, corners, lap, ref_])

  useEffect(() => {   // track map
    const el = mapDiv.current; if (!el || !R.pos_x_m) return
    Plotly.react(el, [
      { x: R.pos_x_m, y: R.pos_z_m, mode: 'markers', marker: { size: 3, color: R.speed_kmh, colorscale: 'Viridis', showscale: false }, hoverinfo: 'skip', name: 'Giro rif.' },
      { x: [null], y: [null], mode: 'markers', marker: { size: 11, color: '#ff4d4f' }, name: 'cursore', hoverinfo: 'skip' },
    ], { height: 260, margin: { l: 4, r: 4, t: 4, b: 4 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#0e1216', showlegend: false,
      xaxis: { visible: false, scaleanchor: 'y' }, yaxis: { visible: false } }, { displayModeBar: false, responsive: true })
  }, [R])
  useEffect(() => {
    const el = mapDiv.current; if (!el || cursor == null || !R.pos_x_m || R.pos_x_m[cursor] == null) return
    try { Plotly.restyle(el, { x: [[R.pos_x_m[cursor]]], y: [[R.pos_z_m[cursor]]] }, [1]) } catch { /* ignore */ }
  }, [cursor, R])

  const zoomTo = (c: any) => { const r = [c.entry_m - 40, c.exit_m + 40]; CH.forEach(ch => Plotly.relayout(divs.current[ch.key], { 'xaxis.range': r })) }
  const reset = () => CH.forEach(ch => Plotly.relayout(divs.current[ch.key], { 'xaxis.autorange': true }))
  const ci = cursor != null ? cursor : null

  return (
    <div className="analysis">
      {qualityBad && <p className="bad">Qualità dell'allineamento insufficiente (copertura/buchi): confronto da non considerare affidabile.</p>}
      <p>Delta totale giro {lap} vs {ref_}: <b data-testid="total-delta">{cmp.total_delta_s != null ? (cmp.total_delta_s > 0 ? '+' : '') + cmp.total_delta_s.toFixed(3) + ' s' : '–'}</b>
        {' '}<span className="mut">· dati: {cmp.provenance}</span></p>
      <div className="cols">
        <div className="charts" data-testid="charts">{CH.map(c => <div key={c.key} ref={el => { divs.current[c.key] = el }} data-testid={'chart-' + c.key} />)}</div>
        <aside>
          <h3>Mappa</h3><div ref={mapDiv} data-testid="track-map" />
          {ci != null && <p className="mut mono">Cursore: {grid[ci]} m · {L.speed_kmh[ci] ?? '–'} km/h</p>}
          <h3>Curve {cmp.corners_provisional && <span className="tag syn" title="Numerazione provvisoria: nessun numero reale inventato">provvisorie</span>}</h3>
          <button onClick={reset}>Reset zoom</button>
          {corners.corners.map((c: any) => <div className="row link" key={c.id} onClick={() => zoomTo(c)}><span>{c.name ?? c.id}</span><span className="mono">{c.apex_m.toFixed(0)} m · {c.min_speed_kmh?.toFixed(0) ?? '–'} km/h</span></div>)}
        </aside>
      </div>
      <h3>Osservazioni misurate</h3>
      {cmp.findings.length === 0 ? <p className="mut" data-testid="no-findings">Nessuna differenza oltre soglia rispetto al riferimento.</p> :
        <table data-testid="findings"><thead><tr><th>Curva</th><th>Osservazione</th><th>Dati misurati</th><th>Variazione tempo zona</th></tr></thead>
          <tbody>{cmp.findings.map((f: any, i: number) => <tr key={i}><td>{f.corner}</td><td>{findingLabel(f.type)}</td><td className="mono">{findingText(f)}</td>
            <td className="mono">{f.time_impact_s != null ? (f.time_impact_s > 0 ? '+' : '') + f.time_impact_s.toFixed(3) + ' s' : '–'}</td></tr>)}</tbody></table>}
      {driving && <DrivingTable d={driving} />}
      <p className="mut">Le differenze sono misure rispetto al giro di riferimento; la variazione di tempo è attribuita per zona e non dimostra la causa. Soglie: frenata ±15 m, minima ≥2 km/h, uscita ≥3 km/h, gas ≥15 m.</p>
    </div>)
}

/** Per-corner driving analysis: same `driving.analyse` the live engineer / Driving Display use. */
function DrivingTable({ d }: any) {
  const t = (x: number | null | undefined) => x == null ? '–' : (x > 0 ? '+' : '') + x.toFixed(3)
  return (
    <div data-testid="driving">
      <h3>Analisi di guida per curva <span className="tag">{d.session_mode?.label}</span></h3>
      <table data-testid="driving-corners"><thead><tr><th>Curva</th><th>Freno (m)</th><th>Picco</th><th>Rilascio (m)</th><th>V ingresso</th><th>V min</th><th>Gas (m)</th><th>V uscita</th><th>Δ ingresso</th><th>Δ centro</th><th>Δ uscita</th></tr></thead>
        <tbody>{d.corners.map((r: any) => <tr key={r.corner}><td>{r.corner}</td><td className="mono">{r.lap.brake_start_m ?? '–'}</td><td className="mono">{r.lap.brake_peak ?? '–'}</td>
          <td className="mono">{r.lap.brake_release_m ?? '–'}</td><td className="mono">{r.lap.entry_speed_kmh ?? '–'}</td><td className="mono">{r.lap.min_speed_kmh ?? '–'}</td>
          <td className="mono">{r.lap.throttle_on_m ?? '–'}</td><td className="mono">{r.lap.exit_speed_kmh ?? '–'}</td>
          <td className="mono">{t(r.segments.entry.delta_s)}</td><td className="mono">{t(r.segments.mid.delta_s)}</td><td className="mono">{t(r.segments.exit.delta_s)}</td></tr>)}</tbody></table>
      {d.findings.length > 0 && <ul data-testid="driving-findings">{d.findings.map((f: any, i: number) => <li key={i}><b>{f.corner}</b> {f.label} <span className={'tag conf-' + f.confidence.level}>{f.confidence.level}</span>
        <span className="mut"> · {Object.entries(f.evidence).map(([k, v]) => `${k}=${v}`).join(', ')}{f.time_impact_s != null ? ` · ${t(f.time_impact_s)} s in ${f.phase}` : ''}</span></li>)}</ul>}
      {d.gains.length > 0 && <ul data-testid="driving-gains">{d.gains.map((g: any, i: number) => <li key={i} className="ok"><b>{g.corner}</b> {g.label}: −{g.time_gain_s.toFixed(3)} s</li>)}</ul>}
      <p className="mut">Una frenata più tardi non è automaticamente migliore: ogni curva è valutata sul tempo di ingresso, centro e uscita. Affidabilità del riferimento: {(d.reference_reliability * 100).toFixed(0)}%.</p>
    </div>)
}

const sgn = (x: number | null | undefined, d = 3) => x == null ? '–' : (x > 0 ? '+' : '') + x.toFixed(d)
const heat = (x: number | null) => x == null ? 'transparent' : x <= 0.005 ? 'rgba(52,211,153,0.35)' : `rgba(255,77,79,${Math.min(0.75, 0.12 + x * 1.6)})`

/** Whole-session view: ideal lap, where time is lost on every lap (heat map), advice sorted by gain. */
function Report({ r, onPick }: { r: any; onPick: (n: number) => void }) {
  const c = r.consistency
  return (
    <div data-testid="session-report">
      <h3>Riepilogo sessione</h3>
      <div className="grid4">
        <div className="big"><div data-testid="rep-best">{fmtTime(r.best_time_s)}</div><small>miglior giro (giro {r.best_lap})</small></div>
        <div className="big"><div data-testid="rep-ideal">{r.ideal_time_s != null ? fmtTime(r.ideal_time_s) : '–'}</div><small>giro ideale (migliori zone)</small></div>
        <div className="big"><div className="ok">{r.ideal_gain_s != null ? '−' + r.ideal_gain_s.toFixed(3) : '–'}</div><small>margine teorico (s)</small></div>
        <div className="big"><div>{c ? '±' + c.std_s.toFixed(3) : '–'}</div><small>costanza (dev.std s){c ? ` · ${c.within_0_5s_pct}% giri entro 0,5 s` : ''}</small></div>
      </div>
      {r.trend && <p className="mut">Andamento: <b>{r.trend.label}</b> ({sgn(r.trend.slope_s_per_lap)} s per giro).</p>}
      {r.skipped_laps?.length > 0 && <p className="mut">Giri esclusi per dati di posizione insufficienti: {r.skipped_laps.map((x: any) => x.lap).join(', ')}.</p>}
      {r.ideal_time_s == null && <p className="mut">Servono almeno 2 giri validi per calcolare giro ideale e margini.</p>}
      {r.advice.length > 0
        ? <><h4>Dove guadagnare, in ordine di importanza</h4>
          <ol data-testid="rep-advice">{r.advice.map((a: any, i: number) => <li key={i}><b className="ok">−{a.gain_s.toFixed(3)} s</b> {a.text}</li>)}</ol></>
        : r.ideal_time_s != null && <p className="ok" data-testid="rep-no-advice">Nessun margine misurabile oltre il rumore: i tuoi giri sono molto simili tra loro.</p>}
      <details open><summary>Mappa del tempo perso, giro per giro (secondi persi rispetto al tuo miglior passaggio in ogni zona)</summary>
        <div className="lapbox"><table data-testid="rep-heat"><thead><tr><th>Giro</th><th>Tempo</th><th>Δ miglior</th>
          {r.zones.map((z: any) => <th key={z.id} title={z.label}>{z.kind === 'corner' ? z.label : '▬'}</th>)}</tr></thead>
          <tbody>{r.laps.map((l: any) => <tr key={l.number} className="link" onClick={() => onPick(l.number)}>
            <td>{l.number}{l.is_best ? ' ★' : ''}</td><td className="mono">{fmtTime(l.time_s)}</td><td className="mono">{sgn(l.delta_best_s)}</td>
            {l.zones.map((x: number | null, i: number) => <td key={i} className="mono" style={{ background: heat(x) }}>{x == null ? '–' : x <= 0.005 ? '★' : x.toFixed(2)}</td>)}</tr>)}</tbody></table></div>
        <p className="mut">★ = il tuo miglior passaggio in quella zona · ▬ = rettilineo · clicca un giro per confrontarlo qui sotto.</p>
      </details>
      <p className="mut">{r.note}</p>
    </div>)
}
