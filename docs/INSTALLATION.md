# INSTALLATION
Requisiti: Python ≥ 3.11 (sviluppato con 3.13). Dipendenze locali al progetto (nessuna installazione globale):
`fastapi uvicorn pydantic duckdb numpy scipy` (+ `pytest httpx` per i test).

```bash
cd backend
python -m venv ../.venv
../.venv/bin/pip install -e ".[dev]"        # Windows: ..\.venv\Scripts\pip install -e ".[dev]"
```
Dati dell'app: `%LOCALAPPDATA%\RaceEngineerAI` (Windows) o `~/.local/share/race-engineer-ai`; override `RACE_ENGINEER_DATA`.
Mai dentro la cartella di LMU. Override ricerca gioco: `LMU_GAME_DIR`.

LMU: Settings → Gameplay → **Enable Plugins** = ON, poi riavvio completo (il software non modifica mai questa impostazione).
Accesso LAN: `serve --lan` stampa un token; senza il flag il server ascolta solo su 127.0.0.1.
Packaging EXE e installer: Fase 9 (non implementato).
