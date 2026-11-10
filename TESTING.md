# TESTING
`cd backend && python -m pytest tests` — ~150 test, ~3 min (include `test_validation_tools`, `test_ai_providers` con trasporto HTTP finto, `test_endurance` con simulazione 4 h). Frontend: `cd frontend && npm test` (vitest, 8; 184 pytest in totale) e, con backend avviato su dati sintetici
(`RACE_ENGINEER_DATA=<dir> python scripts/seed_synthetic.py constant mixed`, poi `python -m race_engineer serve --synthetic constant --laps 30`),
`NODE_PATH=$(npm root -g) node frontend/e2e/e2e.cjs http://127.0.0.1:8765 out.png` (Playwright, 19 controlli incl. pannello AI senza chiavi: banner sintetico, 7 grafici, mappa, cursore sincronizzato, osservazioni attese, nessun errore console).

| Area | File | Natura dei dati |
|---|---|---|
| Analisi di guida (fasi curva, riferimento personale, adattamento sessione) | `test_driving_analysis.py` | sintetici con differenze note |
| Ingegnere live unificato (stato condiviso, suggerimento unico, WS, mappa, reset sessione) | `test_live_engineer.py` | sintetici |
| Driving Display (Playwright, 4 viewport, offline/riconnessione, coerenza dashboard) | `frontend/e2e/display.cjs` (job CI `display-e2e`) | sintetici |
| Live-check (verdetto sintetico mai reale, nessun dato personale, passo reale incompleto) | `test_live_engineer.py` | sintetici |
| Layout (coerenza interna, NON verità LMU) | `test_layout.py` | — |
| Lettura sola lettura, estrazione giocatore (non slot 0), conversioni, letture strappate | `test_reader_decode.py` | costruiti a mano |
| Scenari | `test_synthetic_scenarios.py` | sintetici (giro costante/lento/frenata anticipata/tardiva/gas tardivo) |
| Acquisizione, stati, riconnessione, perdita connessione, campioni mancanti (conteggio esatto), sessioni incomplete, riavvio sessione, segregazione sintetico | `test_engine.py` | sintetici |
| DB: migrazioni, recupero, backup, round-trip, **SIGKILL**, coda piena non bloccante | `test_storage.py` | sintetici |
| Import DuckDB, originale intatto (hash), sola lettura, canali mancanti/troncati, scoperta Steam, report, drift header | `test_import_discovery_diag.py` | sintetici/fixture |
| Analisi: giri, allineamento, curve, confronto, API, import | `test_analysis.py` | sintetici |
| API, guardia Host/Origin, token LAN, WS, restrizione percorsi | `test_api.py` | sintetici |

## Desktop e packaging (verificati su Linux headless, NON su Windows)
- `python -m race_engineer.desktop.main --smoke --synthetic constant` (offscreen): avvia backend in-process, carica `/app/` in Qt WebEngine, legge il titolo dalla UI React,
  verifica acquisizione sintetica, chiude in modo controllato → `SMOKE loaded=True nav_title='Race Engineer AI' state=acquiring samples=783`, exit 0.
- `pyinstaller packaging/race_engineer.spec`: bundle Linux (CLI + desktop, 835 MB) → CLI: `layout`, `diagnose`, `serve`, `/app/`, compare (scipy), chat; desktop congelato: stesso `--smoke` OK.
- Tray, notifiche e minimizzazione sono implementati ma **non osservabili in headless**: non verificati.

## Non ancora testato / non testabile qui
Acquisizione reale LMU; backend Windows `OpenFileMappingW`; file DuckDB reali; rilevamento processo su Windows;
bundle/exe Windows, installer; AI con LLM reale; tray/notifiche; analisi e frontend su dati reali (solo sintetici).
**I dati sintetici non dimostrano l'integrazione con LMU.**

## Smoke del bundle / sorgente
`python scripts/smoke_bundle.py --source` oppure `python scripts/smoke_bundle.py dist/RaceEngineerAI` (CLI, verify-lmu senza LMU = NON verificato, serve sintetico, /app/, /diag, chat a regole, spegnimento, persistenza dopo riapertura, shell desktop). Nessun test qui dice nulla su LMU reale: vedi docs/VALIDATION.md.

## Coaching (0.6.0, SINTETICO)
- `backend/tests/test_coach.py`: istruzioni per ogni tipo (nessuna distanza inventata a confidenza bassa), comparabilità, ciclo di vita su sessione «mixed», persistenza al riavvio, abitudine/occasionale/corretto, separazione reale/sintetico, preferenze, consigli opposti, ri-valutazione, giri non confrontabili, chiusura consigli mai mostrati, API.
- `frontend/e2e/display.cjs`: istruzione (come/perché/obiettivo), analisi di fine giro, coerenza dashboard/display/REST, memoria coach.
- Nessuno di questi test sostituisce la verifica con LMU reale (vedi `docs/UNIFIED_DRIVING_DISPLAY.md` §11).
