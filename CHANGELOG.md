# CHANGELOG
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
