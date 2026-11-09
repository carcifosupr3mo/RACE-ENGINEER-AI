# DATA-MODEL
**SQLite** (`catalog.sqlite`, migrazioni versionate in `storage/catalog.py`): `schema_migrations`, `sessions`
(id, started/ended, source `lmu_shm|duckdb_import|synthetic`, `is_synthetic`, status `recording|complete|incomplete`, track, vehicle,
class, session_type, session_code, game_version, track_length_m, samples, samples_lost, `data_path`, `original_path`).
Una sessione trovata in `recording` all'avvio è marcata `incomplete`; **nessun dato viene mai cancellato**.
Backup: `Catalog.backup()` (API SQLite online); integrità: `integrity_ok()`.

**DuckDB derivato** (`<data>/sessions/*.duckdb`, sintetici in `<data>/synthetic/`): tabella `samples(session_id, wall_time,
provenance, <73 canali>)` (vedi TELEMETRY-FORMAT §3). I DuckDB originali di LMU non vengono mai modificati: sono solo sorgente.

Non ancora implementati: giri/settori (Fase 2), profili circuito, setup importati, conversazioni, report, profilo pilota.
Provenienza: enum `lmu_shm, duckdb_import, computed, manual, unavailable, synthetic` (estensione della lista richiesta: `synthetic`).

Migrazioni: 1 `sessions`; 2 `track_profiles` (profili curve confermati); 3 `goals`, `messages` (chat), `settings` (AI, senza segreti), `setups` (copia verbatim, originali mai modificati).
