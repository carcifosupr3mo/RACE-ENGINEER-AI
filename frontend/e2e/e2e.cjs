// Playwright end-to-end against a running backend (SYNTHETIC data).
// Usage: node e2e/e2e.cjs http://127.0.0.1:8765 [screenshot.png]
const { chromium } = require('playwright')
const base = process.argv[2] || 'http://127.0.0.1:8765'
const fail = []
const check = (name, ok, extra = '') => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (extra ? '  ' + extra : '')); if (!ok) fail.push(name) }
;(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 1000 } })
  const errs = []; p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
  await p.goto(base + '/'); await p.waitForSelector('[data-testid=nav-live]')
  check('redirect to app + nav', p.url().includes('/app/'))
  await p.click('[data-testid=nav-live]'); await p.waitForTimeout(1500)
  check('synthetic banner on live', await p.isVisible('[data-testid=synth-banner]'))
  const st = await p.textContent('[data-testid=state]')
  check('live state label', /Acquisizione|Sessione|Attesa|Connessione/.test(st), st)
  await p.click('[data-testid=nav-sessions]'); await p.waitForSelector('[data-testid=sessions] tbody tr')
  const btns = await p.$$('[data-testid=open-laps]:not([disabled])')
  check('a finished session exists', btns.length > 0)
  await btns[0].click(); await p.waitForSelector('[data-testid=lap-table]')
  check('lap table has rows', (await p.$$('[data-testid=lap-table] tbody tr')).length >= 3)
  await p.waitForSelector('[data-testid=chart-delta] .main-svg', { timeout: 15000 })
  await p.waitForTimeout(800)
  const n = await p.$$eval('[data-testid=charts] .main-svg', e => e.length)
  check('7 charts rendered', n >= 7, 'svg count ' + n)
  check('track map rendered', await p.isVisible('[data-testid=track-map] .main-svg'))
  const td = (await p.textContent('[data-testid=total-delta]')).trim()
  check('total delta shown', /s$/.test(td), td)
  const box = await (await p.$('[data-testid=chart-speed_kmh] .nsewdrag')).boundingBox()
  await p.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2); await p.waitForTimeout(500)
  const hov = await p.$$eval('[data-testid=chart-brake] .hoverlayer .hovertext', e => e.length)
  check('cursor synchronized across charts', hov > 0, 'hovertext in brake chart: ' + hov)
  const ft = (await p.$('[data-testid=findings]')) ? await p.textContent('[data-testid=findings]') : ''
  check('mixed session: early braking found in P2 (expected from scenario)', /P2/.test(ft) && /Frenata anticipata/.test(ft), ft.slice(0, 120))
  await p.selectOption('[data-testid=lap-select]', '3'); await p.waitForTimeout(1500)
  const ft3 = (await p.$('[data-testid=findings]')) ? await p.textContent('[data-testid=findings]') : ''
  check('lap 3: late throttle found in P3', /P3/.test(ft3) && /Accelerazione tardiva/.test(ft3), ft3.slice(0, 120))
  await p.screenshot({ path: process.argv[3] || 'e2e.png', fullPage: true })
  check('no console/page errors', errs.length === 0, JSON.stringify(errs).slice(0, 300))
  await b.close(); process.exit(fail.length ? 1 : 0)
})()
