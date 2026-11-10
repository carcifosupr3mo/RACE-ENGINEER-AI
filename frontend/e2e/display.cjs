// Playwright end-to-end for the Driving Display against a running backend serving SYNTHETIC data (never LMU).
// Usage: node e2e/display.cjs http://127.0.0.1:8790 [screenshot-dir]
const { chromium } = require('playwright')
const fs = require('fs')
const base = process.argv[2] || 'http://127.0.0.1:8790'
const shots = process.argv[3] || '.'
const fail = []
const check = (name, ok, extra = '') => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (extra ? '  ' + extra : '')); if (!ok) fail.push(name) }
const INIT = () => {          // test hook: keep every WebSocket reachable and allow muting messages (simulates a stalled network)
  const Orig = window.WebSocket; window.__ws = []; window.__mute = false
  window.WebSocket = class extends Orig {
    constructor(...a) { super(...a); window.__ws.push(this) }
    set onmessage(f) { super.onmessage = e => { if (!window.__mute) f(e) } }
    get onmessage() { return super.onmessage }
  }
}
;(async () => {
  fs.mkdirSync(shots, { recursive: true })
  const b = await chromium.launch()
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 })
  await ctx.addInitScript(INIT)
  const p = await ctx.newPage()
  const errs = []; p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
  await p.goto(base + '/driving-display'); await p.waitForSelector('[data-testid=driving-display]')
  check('/driving-display renders the display (not the dashboard)', !(await p.$('nav h1')))
  check('synthetic banner is shown', await p.isVisible('[data-testid=display-synth-banner]'))
  await p.waitForFunction(() => /^\d+$/.test(document.querySelector('[data-testid=display-speed]')?.textContent || ''), null, { timeout: 20000 })
  check('live speed arrives over the shared WebSocket', true)
  const learn = await p.textContent('[data-testid=display-suggestion]')
  check('learning state is shown before there is a reference', /APPRENDIMENTO|Sto imparando|In attesa/.test(learn), learn.slice(0, 80))
  // wait for several laps (the synthetic game runs faster than real time) -> map + reference + suggestion
  await p.waitForSelector('[data-testid=track-map-display] [data-zone=brake]', { timeout: 120000 })
  check('map drawn from real positions with braking zones', true)
  check('release and acceleration zones drawn', (await p.$$('[data-zone=release]')).length > 0 && (await p.$$('[data-zone=accel]')).length > 0)
  check('corner markers + car marker', (await p.$$('[data-testid^=corner-]')).length >= 3 && await p.isVisible('[data-testid=car-marker]'))
  await p.waitForFunction(() => /CURVA P\d/.test(document.querySelector('[data-testid=display-suggestion]')?.textContent || ''), null, { timeout: 120000 })
  const sug = (await p.textContent('[data-testid=display-suggestion-text]')).trim()
  check('ONE main suggestion, tied to a corner, with confidence', /^CURVA P\d — /.test(sug) && /affidabilità (alta|media|bassa)/.test(await p.textContent('[data-testid=display-suggestion]')), sug)
  check('exactly one suggestion element', (await p.$$('[data-testid=display-suggestion]')).length === 1)
  // coaching: how / why / goal in Italian, text only (the detail is hidden while the driver is busy, so wait for a calm moment)
  await p.waitForSelector('[data-testid=display-instruction]', { timeout: 60000 })
  const det = await p.textContent('[data-testid=display-instruction]')
  check('instruction shows how / why / goal', /Perché:/.test(det) && /Obiettivo:/.test(det) && det.length > 40, det.slice(0, 90))
  check('no voice / audio element anywhere on the display', (await p.$$('audio, video')).length === 0)
  await p.waitForSelector('[data-testid=display-review]', { timeout: 90000 }).catch(() => {})
  const rv = await p.$('[data-testid=display-review-summary]')
  check('between laps the review of the last lap is shown (synthetic-labelled)', !!rv && /GIRO \d+ COMPLETATO/.test(await rv.textContent()) && /SINTETICI/.test(await p.textContent('[data-testid=display-review]')))
  const delta = await p.textContent('[data-testid=display-delta]')
  check('delta vs reference shown', /[+−]\d\.\d{3}/.test(delta), delta.replace(/\s+/g, ' '))
  check('session mode shown (practice for the synthetic session code)', /Prove libere/.test(await p.textContent('[data-testid=display-mode]')))
  // ---- interactivity
  const vb0 = await p.getAttribute('[data-testid=track-map-display] svg', 'viewBox')
  const box = await (await p.$('[data-testid=track-map-display] svg')).boundingBox()
  await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await p.mouse.wheel(0, -400); await p.waitForTimeout(300)
  check('map zoom (wheel) changes the view', (await p.getAttribute('[data-testid=track-map-display] svg', 'viewBox')) !== vb0)
  await p.dblclick('[data-testid=track-map-display] svg', { position: { x: 5, y: 5 } }); await p.waitForTimeout(200)
  await p.click('[data-testid^=corner-]'); await p.waitForSelector('[data-testid=corner-card]')
  check('tap a corner -> details (brake point, apex, min speed)', /freno da .* apice .* vel\. min/.test(await p.textContent('[data-testid=corner-card]')))
  // ---- fullscreen + unattended use
  await p.click('[data-testid=display-fullscreen]'); await p.waitForTimeout(400)
  check('fullscreen button enters fullscreen', await p.evaluate(() => !!document.fullscreenElement))
  await p.keyboard.press('f'); await p.waitForTimeout(400)
  check('F key leaves fullscreen', await p.evaluate(() => !document.fullscreenElement))
  check('display needs no continuous interaction (delta and map render with zero input)', (await p.$$('[data-testid=display-delta]')).length === 1 && await p.isVisible('[data-testid=track-map-display]'))
  // ---- coherence with the dashboard (same engine, same state)
  const dash = await ctx.newPage(); await dash.addInitScript(INIT); await dash.goto(base + '/app/'); await dash.click('[data-testid=nav-live]'); await dash.waitForSelector('[data-testid=live-suggestion]')
  await dash.waitForFunction(() => /Prove libere/.test(document.querySelector('[data-testid=live-mode]')?.textContent || ''), null, { timeout: 20000 })
  const dm = (await dash.textContent('[data-testid=live-mode]')).trim(), pm = (await p.textContent('[data-testid=display-mode]')).trim()
  check('dashboard and display show the same session mode', dm === pm, `${dm} | ${pm}`)
  const state = await p.evaluate(() => fetch('/api/engineer/state').then(r => r.json()))
  const ck = await p.evaluate(() => fetch('/api/engineer/checklist').then(r => r.json()))
  check('live-check on synthetic data is labelled SYNTHETIC and never real', ck.verdict === 'SYNTHETIC_NOT_REAL' && ck.data_provenance === 'synthetic' && ck.steps.map.status === 'ok' && ck.steps.braking_points.status === 'ok', ck.verdict)
  const dsug = ((await dash.textContent('[data-testid=live-suggestion]')) || '').trim()
  const dsug2 = ((await p.textContent('[data-testid=display-suggestion-text]')) || '').trim()
  const t = state.suggestion.main && state.suggestion.main.text
  const ti = state.suggestion.main && state.suggestion.main.instruction && state.suggestion.main.instruction.text
  check('dashboard live panel, display and REST state show the same suggestion', !!t && !!ti && dsug.includes(ti) && dsug2 === ti, `${dsug.slice(0, 60)} | ${dsug2} | ${t} | ${ti}`)
  const cs = await p.evaluate(() => fetch('/api/coach/summary').then(r => r.json()))
  check('coach memory reachable and flagged synthetic', cs.synthetic === true && cs.laps_analysed >= 1 && Object.keys(cs.tips_by_status).length >= 1, JSON.stringify(cs.tips_by_status))
  check('dashboard links to the Driving Display', await dash.isVisible('[data-testid=open-display]'))
  await dash.click('[data-testid=nav-display]'); await dash.waitForSelector('[data-testid=display-info]')
  check('Driving Display info page explains second monitor and LAN opt-in', /secondo monitor/i.test(await dash.textContent('[data-testid=display-info]')) && await dash.isVisible('[data-testid=display-lan-off]'))
  await dash.close()
  // ---- offline state + auto-reconnect
  await p.evaluate(() => { window.__mute = true })
  await p.waitForSelector('[data-testid=display-offline]', { timeout: 8000 })
  check('stalled data -> offline state shown', /CONNESSIONE PERSA/.test(await p.textContent('[data-testid=display-conn]')))
  await p.evaluate(() => { window.__mute = false })
  await p.waitForSelector('[data-testid=display-offline]', { state: 'detached', timeout: 8000 })
  check('data resumes -> offline state cleared', true)
  await p.evaluate(() => { window.__ws.forEach(w => w.close()) })                          // dropped connection (Wi-Fi blip)
  await p.waitForFunction(() => window.__ws.length > 1 && window.__ws[window.__ws.length - 1].readyState === 1, null, { timeout: 15000 })
  check('dropped socket -> automatic reconnection with a new WebSocket', true)
  await p.waitForFunction(() => !document.querySelector('[data-testid=display-offline]'), null, { timeout: 8000 })
  check('state is live again after reconnection', /^\d+$/.test((await p.textContent('[data-testid=display-speed]')).trim()))
  // ---- responsive: 13", 10", 7" (Raspberry), tablet portrait
  for (const [name, w, h] of [['13in-1280x800', 1280, 800], ['10in-1024x600', 1024, 600], ['7in-800x480', 800, 480], ['portrait-600x1000', 600, 1000]]) {
    await p.setViewportSize({ width: w, height: h }); await p.waitForTimeout(500)
    const m = await p.evaluate(() => {
      const r = s => { const e = document.querySelector(s); if (!e) return null; const q = e.getBoundingClientRect(); return { t: q.top, b: q.bottom, l: q.left, r: q.right, w: q.width, h: q.height } }
      return { sw: document.documentElement.scrollWidth, iw: innerWidth, ih: innerHeight, map: r('[data-testid=track-map-display]'), sug: r('[data-testid=display-suggestion]'), delta: r('[data-testid=display-delta]') }
    })
    check(`${name}: no horizontal scroll`, m.sw <= m.iw + 1, `${m.sw}/${m.iw}`)
    check(`${name}: map visible with useful size`, m.map && m.map.w > 250 && m.map.h > 120, JSON.stringify(m.map))
    check(`${name}: delta and suggestion fully inside the screen (not clipped or scrolled away)`, m.delta && m.sug && m.delta.t >= -1 && m.sug.t >= -1 && m.delta.b <= m.ih + 1 && m.sug.b <= m.ih + 1 && m.sug.r <= m.iw + 1, `delta.b=${m.delta && m.delta.b} sug.b=${m.sug && m.sug.b} ih=${m.ih}`)
    await p.screenshot({ path: `${shots}/display-${name}.png` })
  }
  check('no console/page errors', errs.length === 0, errs.slice(0, 3).join(' | '))
  await b.close()
  console.log(fail.length ? `\n${fail.length} FAILED: ${fail.join('; ')}` : '\nALL DISPLAY CHECKS PASSED')
  process.exit(fail.length ? 1 : 0)
})().catch(e => { console.error('E2E ERROR', e); process.exit(2) })
