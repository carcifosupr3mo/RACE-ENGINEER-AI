# CHANGELOG
## 0.5.0 (non rilasciata) — Sistema unificato con doppio display
- **Un solo ingegnere di pista**: nuovo `LiveEngineer` (stato condiviso) agganciato all'unico `AcquisitionEngine`; nessun secondo motore/flusso/agente AI. Dettagli in `docs/UNIFIED_DRIVING_DISPLAY.md`.
- Analisi di guida per fasi (frenata, rilascio, apice, gas, uscita, tempi ingresso/centro/uscita) con giudizio sull'intera curva (la frenata più tardi non è automaticamente migliore) e confidenza (`analysis/driving.py`).
- Riferimento personale progressivo e persistente per circuito/vettura, sintetico separato (`analysis/reference.py`); adattamento automatico al tipo di sessione (`analysis/session_mode.py`).
- Arbitro dei suggerimenti: uno solo, legato alla curva, con affidabilità; congelato in guida impegnativa; stato «apprendimento» se i dati non bastano; allarmi dalle soglie dell'EventDetector (`live/suggestions.py`).
- AI: nuovi fatti di guida, interpretazione periodica via la coda AI esistente (aggregati, grounding); la pipeline endurance ignora le risposte di altri tipi.
- API: `/api/engineer/{state,map,events,reference,status}`, `/api/sessions/{id}/driving`, `/api/display/info`, `/driving-display`; il WebSocket `/ws/live` porta `engineer` + `events`.
- **Driving Display** (`/driving-display`, stesso bundle, chunk separato ~13 kB senza Plotly): mappa interattiva dai dati di posizione reali, delta, velocità, marcia, giri, pedali, curva attuale/prossima, un suggerimento, allarmi, riconnessione automatica e stato offline; dashboard: blocco «Ingegnere di pista» nella Live, sezione «Driving Display», tabella di analisi di guida nel Lap Analyzer.
- Shell desktop: voce di menu «Apri Driving Display (secondo monitor)», `Ctrl+D`, `--display`, `--lan` (opt-in, token) e «Driving Display in rete». CLI: `serve --lan` stampa l'URL del display; `--synthetic-speed` per test/demo.
- Test: +25 pytest (184 totali), +4 vitest, e2e Playwright del display, smoke 29 controlli (7 nuovi). Nessuna verifica con LMU reale.
## 0.4.1 (non rilasciata)
- Procedura Windows guidata `PROCEDURA_VERIFICA.ps1`: preflight, registrazione >= 60 s con marcature HUD, report DuckDB/setup, riepilogo, controllo integrita' originali e report salvati. Test PowerShell in CI.
- Nuovi comandi `preflight`, `hud-compare`, `verification-summary`; commit registrato in `build_info.json`.
- Fix: `verify-lmu` non puo' piu' risultare reale con `--shm-path`; mapping non raggiungibile => codice 3; report mai sovrascritti.

## 0.3.0 — Fasi 4-9 (parziali, vedi ROADMAP)
- AI: base fatti, ingegnere a regole, provider-agnostic (OpenAI-compatibile/Anthropic), budget/timeout/fallback, validatore anti-allucinazione, chat persistente.
- Tyre & Fuel, Driver Development (storico, obiettivi, allenamenti), Setup Advisor conservativo, migrazione SQLite 3.
- UI: Race Engineer AI, Tyre & Fuel, Driver Development, Track Analysis (editor curve), Setup Advisor.
- Shell desktop PySide6 (tray, notifiche, chiusura controllata), spec PyInstaller e `scripts/build.py`.
## 0.2.0 — Fasi 2/3
- Giri completi/incompleti/invalidi, tempi con origine, riepilogo solo su giri validi.
- Allineamento per distanza con controlli di qualità; rilevazione curve provvisorie; profili circuito (SQLite migrazione 2).
- Confronto giro/riferimento con osservazioni numeriche; costanza tra giri.
- Import dei DuckDB nativi LMU come sessioni (provenienza `duckdb_import`, originale intatto).
- API analisi (`/api/sessions/{id}/laps|corners|trace|compare|consistency`, `/api/tracks/profile`, `/api/import/duckdb`).
- Frontend React 18 + TypeScript + Vite + Plotly: navigazione a 10 sezioni, Live, Sessions, Lap Analyzer (7 grafici sincronizzati, mappa, curve, osservazioni).
- Scenario sintetico `mixed`; test pytest (68), vitest (4), e2e Playwright (11 controlli).
## 0.1.0 — Fase 0/1 (non rilasciata)
- Ricerca strutture `LMU_Data` e DuckDB da fonti pubbliche; documentazione con stato di verifica.
- Layout ctypes, reader sola lettura (Windows/file/buffer), decoder con provenienza, catalogo canali (73).
- Motore di acquisizione: macchina a stati, dedup, stima perdite, riconnessione, sessioni, statistiche.
- Storage: SQLite (migrazioni, backup, recupero sessioni interrotte), recorder DuckDB con checkpoint.
- Importer DuckDB LMU in sola lettura con diagnostica canali.
- Simulatore sintetico deterministico (8 scenari) che scrive nel layout reale; fixture DuckDB sintetico.
- API FastAPI + WebSocket + UI diagnostica; CLI `diagnose|serve|record|inspect-duckdb|layout`.
- 52 test pytest.
