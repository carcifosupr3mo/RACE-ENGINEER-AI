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

## Build / release
`python scripts/build.py` (frontend → test → PyInstaller → zip). Su **Windows** produce `dist/RaceEngineerAI/RaceEngineerAI.exe` (desktop, serve `pip install -e "backend[desktop]"`; in PySide6 6.12 Qt WebEngine è il wheel separato `PySide6-WebEngine`)
e `race-engineer-cli.exe`. Un .exe Windows non può essere prodotto da Linux. Installer (MSI/Inno Setup): non implementato.
Desktop da sorgente: `pip install -e "backend[desktop]"` poi `python scripts/run_desktop.py [--synthetic mixed]` (Linux headless: servono libEGL/libxkbcommon/libnss3… e `--smoke`).

## Windows (artefatti CI)
Scarica `RaceEngineerAI-windows` dalla CI: `RaceEngineerAI-Setup-<ver>.exe` (installa in %LOCALAPPDATA%\\Programs, non tocca LMU) oppure lo zip; verifica `SHA256SUMS.txt`. Poi segui docs/VALIDATION.md. I dati utente (%LOCALAPPDATA%\\RaceEngineerAI) non vengono rimossi dalla disinstallazione.
