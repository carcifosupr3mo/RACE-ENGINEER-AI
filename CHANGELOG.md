# CHANGELOG
## 0.1.0 — Fase 0/1 (non rilasciata)
- Ricerca strutture `LMU_Data` e DuckDB da fonti pubbliche; documentazione con stato di verifica.
- Layout ctypes, reader sola lettura (Windows/file/buffer), decoder con provenienza, catalogo canali (73).
- Motore di acquisizione: macchina a stati, dedup, stima perdite, riconnessione, sessioni, statistiche.
- Storage: SQLite (migrazioni, backup, recupero sessioni interrotte), recorder DuckDB con checkpoint.
- Importer DuckDB LMU in sola lettura con diagnostica canali.
- Simulatore sintetico deterministico (8 scenari) che scrive nel layout reale; fixture DuckDB sintetico.
- API FastAPI + WebSocket + UI diagnostica; CLI `diagnose|serve|record|inspect-duckdb|layout`.
- 52 test pytest.
