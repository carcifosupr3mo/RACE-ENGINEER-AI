# TESTING
`cd backend && python -m pytest tests` — 52 test, ~9 s. UI: `node scripts/ui_smoke.js [url] [png]` (Playwright, richiede server avviato).

| Area | File | Natura dei dati |
|---|---|---|
| Layout (coerenza interna, NON verità LMU) | `test_layout.py` | — |
| Lettura sola lettura, estrazione giocatore (non slot 0), conversioni, letture strappate | `test_reader_decode.py` | costruiti a mano |
| Scenari | `test_synthetic_scenarios.py` | sintetici (giro costante/lento/frenata anticipata/tardiva/gas tardivo) |
| Acquisizione, stati, riconnessione, perdita connessione, campioni mancanti (conteggio esatto), sessioni incomplete, riavvio sessione, segregazione sintetico | `test_engine.py` | sintetici |
| DB: migrazioni, recupero, backup, round-trip, **SIGKILL**, coda piena non bloccante | `test_storage.py` | sintetici |
| Import DuckDB, originale intatto (hash), sola lettura, canali mancanti/troncati, scoperta Steam, report, drift header | `test_import_discovery_diag.py` | sintetici/fixture |
| API, guardia Host/Origin, token LAN, WS, restrizione percorsi | `test_api.py` | sintetici |

## Non ancora testato / non testabile qui
Acquisizione reale LMU; backend Windows `OpenFileMappingW`; file DuckDB reali; rilevamento processo su Windows;
packaging (Fase 9); test grafici/frontend React (Fase 3); AI (Fase 4); allineamento giri e analisi (Fase 3).
**I dati sintetici non dimostrano l'integrazione con LMU.**
