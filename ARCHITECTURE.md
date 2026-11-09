# ARCHITECTURE

```
LMU ──(Shared Memory LMU_Data, sola lettura)──► lmu.reader ─► lmu.decode ─► model.Sample (+provenienza)
UserData/Telemetry/*.duckdb ──(read_only)──► importers.lmu_duckdb                │
                                                                                  ▼
                              acquisition.engine (thread, macchina a stati, dedup, perdite)
                                   │ latest sample                  │ add() non bloccante
                                   ▼                                ▼
                          api.app (FastAPI + WS)          storage.recorder (thread → DuckDB, checkpoint)
                                   │                                │ metadati
                          UI browser / (Qt WebEngine)       storage.catalog (SQLite, migrazioni, backup)
```
Un solo backend (Python) per web e desktop; la shell desktop PySide6 (Fase 8) caricherà la stessa UI via Qt WebEngine.

## Moduli (`backend/race_engineer`)
| Modulo | Ruolo |
|---|---|
| `lmu/layout.py` | struct ctypes `LMU_Data` (offset calcolati) — **[T3, non verificato su LMU]** |
| `lmu/reader.py` | backend di sola lettura (Windows named mapping, file/`/dev/shm`, buffer) + snapshot coerente del solo giocatore |
| `lmu/decode.py` | funzioni pure struct → `Sample` (conversioni di unità documentate) |
| `lmu/discovery.py` | Steam/librerie, `UserData`, `Telemetry`, build id, header SharedMemoryInterface, indizi plugin |
| `lmu/diagnostics.py` | stati di connessione + procedura guidata + drift nomi campi |
| `model/` | catalogo canali (unica fonte di verità), `Sample`, `Provenance` |
| `acquisition/engine.py` | polling ~250 Hz, dedup su `mElapsedTime`, stima perdite, riconnessione, sessioni, statistiche |
| `storage/` | SQLite (sessioni, migrazioni, backup, recupero), DuckDB per campioni (file per sessione) |
| `importers/lmu_duckdb.py` | ispezione/lettura in sola lettura dei DuckDB nativi |
| `synthetic/` | simulatore deterministico + "fake game" che scrive nel layout reale + fixture DuckDB |
| `api/` | FastAPI, WebSocket `/ws/live`, UI diagnostica statica |

## Decisioni e deviazioni dalla proposta (motivate)
1. **UI**: la pagina diagnostica statica (`/diag`) resta per la Fase 1; l'app React 18 + TS + Vite + `plotly.js-basic-dist-min` (`frontend/`) è compilata in `backend/race_engineer/api/webdist` e servita a `/app/` (così `serve` non richiede Node). Si usa Plotly direttamente senza wrapper React.
2. **Lettura Windows con `ctypes`** (`OpenFileMappingW`) invece di `mmap(tagname)`: non crea mappature vuote e garantisce sola lettura.
3. **Inserimenti DuckDB via NDJSON + `read_json`**: misurato ~40× più veloce di `executemany` (≈27k vs ≈650 righe/s);
   `executemany` non reggeva nemmeno 100 Hz con 73 colonne in raffiche.
4. **Un file DuckDB per sessione** (isolamento da crash, backup semplice); SQLite tiene solo i metadati.
5. **Nessun `psutil`**: rilevamento processo e memoria con chiamate di sistema minime.
6. **Dati sintetici in cartella e flag separati** (`synthetic/`, `is_synthetic=1`, provenienza `synthetic`, banner UI).

## Sicurezza
Bind su 127.0.0.1; controllo `Host` (anti DNS-rebinding) e `Origin` WS; `--lan` esplicito → token Bearer obbligatorio;
`/api/duckdb/inspect` accetta solo file `.duckdb` nella cartella Telemetry di LMU. Nessuna esposizione pubblica automatica.
