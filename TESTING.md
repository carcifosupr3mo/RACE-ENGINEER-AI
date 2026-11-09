# TESTING
`cd backend && python -m pytest tests` — 99 test, ~2 min. Frontend: `cd frontend && npm test` (vitest, 4) e, con backend avviato su dati sintetici
(`RACE_ENGINEER_DATA=<dir> python scripts/seed_synthetic.py mixed`, poi `python -m race_engineer serve --synthetic constant --laps 30`),
`NODE_PATH=$(npm root -g) node frontend/e2e/e2e.cjs http://127.0.0.1:8765 out.png` (Playwright, 11 controlli: banner sintetico, 7 grafici, mappa, cursore sincronizzato, osservazioni attese, nessun errore console).

| Area | File | Natura dei dati |
|---|---|---|
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
