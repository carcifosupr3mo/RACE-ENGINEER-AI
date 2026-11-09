# RACE ENGINEER AI

Ingegnere di pista virtuale per **Le Mans Ultimate (LMU)**: acquisisce la telemetria, la archivia, la analizza e
(nelle fasi successive) risponde con consigli verificabili. Qualità dei dati prima dell'estetica; ogni numero ha una provenienza.

**Stato: Fasi 0-7 implementate (5 parziale), 8-9 parziali; tutto verificato solo con dati SINTETICI. L'acquisizione da LMU reale e l'analisi su telemetria LMU reale NON sono ancora verificate.**
Vedi [ROADMAP.md](ROADMAP.md) e [docs/LMU-INTEGRATION.md](docs/LMU-INTEGRATION.md).

## Avvio rapido
```bash
cd backend && python -m venv ../.venv && ../.venv/bin/pip install -e ".[dev]"   # Windows: ..\.venv\Scripts\pip
python -m race_engineer diagnose                      # verifica LMU / Shared Memory (sola lettura)
python -m race_engineer serve                         # UI diagnostica su http://127.0.0.1:8765/ (con LMU aperto)
python -m race_engineer serve --synthetic early_brake # fake game SINTETICO (banner viola, mai dati reali)
python -m race_engineer record --seconds 30           # registra in terminale
python -m race_engineer inspect-duckdb "<file>.duckdb"
python -m pytest tests                                # 68 test
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
