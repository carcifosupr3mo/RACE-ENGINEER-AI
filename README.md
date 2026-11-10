# RACE ENGINEER AI

Ingegnere di pista virtuale per **Le Mans Ultimate (LMU)**: acquisisce la telemetria, la archivia, la analizza e
(nelle fasi successive) risponde con consigli verificabili. Qualità dei dati prima dell'estetica; ogni numero ha una provenienza.

**Stato: Fasi 0-7 implementate (5 parziale), 8-9 parziali; tutto verificato solo con dati SINTETICI. L'acquisizione da LMU reale e l'analisi su telemetria LMU reale NON sono ancora verificate.**
Vedi [ROADMAP.md](ROADMAP.md) e [docs/LMU-INTEGRATION.md](docs/LMU-INTEGRATION.md).

## Avvio rapido su Windows (versione portatile dalla CI — consigliato per il test con LMU)
1. Scarica l'artefatto `RaceEngineerAI-windows` dalla pagina della run CI (sezione *Artifacts*) ed estrailo: contiene `RaceEngineerAI-Setup-<ver>.exe` e `RaceEngineerAI-win32.zip`.
2. Verifica gli hash **prima** di aprire i file (devono coincidere con `SHA256SUMS.txt` e con [docs/VALIDATION.md](docs/VALIDATION.md)):
```powershell
Get-FileHash .\RaceEngineerAI-win32.zip -Algorithm SHA256
Get-FileHash .\RaceEngineerAI-Setup-0.1.0.exe -Algorithm SHA256
```
3. Estrai `RaceEngineerAI-win32.zip` in una cartella (es. `C:\RaceEngineerAI`) e fai doppio clic su **`AVVIA_CON_DISPLAY.bat`**: dashboard su `http://127.0.0.1:8765/app/`, Driving Display su `http://127.0.0.1:8765/driving-display` (tasto **F** = tutto schermo sul secondo monitor).
4. Avvia LMU, fai almeno 3 giri, poi **`VERIFICA_DISPLAY.bat`** (report anonimizzato; codice 0 = dati reali e passi automatici OK, 3 = incompleto/sintetico, 2 = app non raggiungibile).
5. Procedura completa di validazione: [docs/UNIFIED_DRIVING_DISPLAY.md](docs/UNIFIED_DRIVING_DISPLAY.md) §11.2. Altri script nella cartella: `VERIFICA_LMU.bat`, `PROCEDURA_VERIFICA.bat`, `DIAGNOSI_COMPLETA.bat`, `TEST_AI.bat`.

Da riga di comando (stessa cartella): `RaceEngineerAI.exe --port 8765 --display` (aggiungi `--lan` solo per usare il Display da un altro dispositivo in rete).
Il programma non è firmato digitalmente: se Windows mostra un avviso non disattivare le protezioni, verifica prima l'hash.

## Avvio rapido da sorgente (sviluppo)
```bash
cd backend && python -m venv ../.venv && ../.venv/bin/pip install -e ".[dev]"   # Windows: ..\.venv\Scripts\pip
python -m race_engineer diagnose                      # verifica LMU / Shared Memory (sola lettura)
python -m race_engineer serve                         # UI diagnostica su http://127.0.0.1:8765/ (con LMU aperto)
python -m race_engineer serve --synthetic early_brake # fake game SINTETICO (banner viola, mai dati reali)
python -m race_engineer record --seconds 30           # registra in terminale
python -m race_engineer inspect-duckdb "<file>.duckdb"
python -m pytest tests                                # suite completa (~200 test, ~3-6 min)
(cd ../frontend && npm ci && npm run build && npm test) # UI React (build già inclusa in webdist)
```
Dettagli: [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Documentazione
[ARCHITECTURE](ARCHITECTURE.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [TESTING](TESTING.md) ·
[LMU-INTEGRATION](docs/LMU-INTEGRATION.md) · [TELEMETRY-FORMAT](docs/TELEMETRY-FORMAT.md) · [DATA-MODEL](docs/DATA-MODEL.md) ·
[ANALYSIS-METHODS](docs/ANALYSIS-METHODS.md) · [AI-GROUNDING](docs/AI-GROUNDING.md) · [INSTALLATION](docs/INSTALLATION.md)

## Regole non negoziabili
Sola lettura su LMU (nessuna iniezione, nessuna modifica a gioco/config/EAC, nessun plugin installato);
dati sintetici sempre separati e marcati; nessun dato inventato; accesso LAN disattivato di default.
