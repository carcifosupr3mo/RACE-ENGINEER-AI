# ROADMAP
Una fase è "completata" solo se i criteri di accettazione sono rispettati **con le evidenze indicate**.

| Fase | Stato | Note |
|---|---|---|
| 0 Ricerca/architettura | ✅ completata *per quanto verificabile senza LMU* | strutture da fonti pubbliche; **nessuna verifica su LMU installato** |
| 1 Acquisizione Shared Memory | 🟡 implementata, **non accettata** | criterio "acquisisce dati reali" NON soddisfatto: serve LMU su Windows |
| 2 Registrazione e sessioni | ✅ implementata e testata con dati sintetici | giri completi/incompleti/invalidi, import DuckDB LMU → sessione, profili circuito; **non verificata su LMU reale** |
| 3 Lap Analyzer + Visualizer | ✅ implementata e testata con dati sintetici (pytest, vitest, Playwright) | manca editor grafico curve, selezione di punto/curva avanzata; **non validata su dati LMU reali** |
| 4 Race Engineer AI | ✅ implementata, testata con dati sintetici e provider finti | ingegnere a regole + LLM opzionale validato; **mai provato con un LLM reale** |
| 5 Setup Advisor | 🟡 parziale | import verbatim, parser generico, proposte solo con limiti min/max verificati nel setup; **formato setup LMU reale non verificato**; mancano dati di comportamento (sotto/sovrasterzo) per correlazioni più forti |
| 6 Tyre & Fuel | ✅ implementata, testata con dati sintetici | consumo su giri puliti, piano carburante con margine manuale, evoluzione gomme; non verificata su LMU |
| 7 Driver Development | ✅ implementata, testata con dati sintetici | storico giorno/settimana/mese, obiettivi, allenamenti dai punti deboli misurati |
| 8 Desktop + Web definitivi | 🟡 vedi report | shell PySide6 (tray, notifiche, chiusura controllata) con smoke test headless su Linux (sorgente e bundle congelato); **tray/notifiche non osservate, mai eseguita su Windows**; LAN opzionale via `--lan` |
| 9 Ottimizzazione/packaging | 🟡 parziale | spec PyInstaller + `scripts/build.py`; bundle Linux verificato (CLI e desktop congelati); **.exe Windows e installer NON prodotti** (serve Windows) |

| 10 Validazione reale Windows / AI gratuita / endurance | 🟡 strumenti pronti, **nessuna verifica reale eseguita** | `verify-lmu`, `duckdb-report`, `setup-inspect`, `ai-test`, AI multi-provider NVIDIA→Groq→locale, pipeline endurance, simulazione 24 h sintetica, installer e smoke in CI; vedi [docs/VALIDATION.md](docs/VALIDATION.md) |

## Fase 1 — criteri di accettazione
| Criterio | Stato |
|---|---|
| App diagnostica si avvia, mostra stato connessione | ✅ (sintetico + assenza LMU verificata) |
| Rileva LMU / verifica Shared Memory | 🟡 codice pronto; rilevamento reale non provato |
| Mostra velocità, RPM, marcia, gas, freno, sterzo, stato sessione | ✅ con dati sintetici · ❌ non provato con LMU |
| **Acquisisce dati reali da LMU** | ❌ **non verificato** |
| Registra un campione di telemetria | ✅ sintetico · ❌ reale |
| Test con dati sintetici separati dal reale | ✅ |

**Prossimo passo bloccante:** eseguire la procedura in [docs/LMU-INTEGRATION.md](docs/LMU-INTEGRATION.md) su Windows con LMU
aperto e riportare l'esito; correggere `layout.py` se la dimensione o i campi differiscono.
Poi Fase 2 (giri validi, riconoscimento circuito/vettura, import DuckDB in sessione), poi Fase 3.
| 11 Sistema unificato con doppio display | ✅ implementato e testato con dati sintetici, 🟡 non verificato su LMU/hardware reali | un solo ingegnere (stato condiviso), analisi di guida per fasi, riferimento personale progressivo, adattamento alla sessione, Driving Display su `/driving-display` (secondo monitor o LAN); vedi [docs/UNIFIED_DRIVING_DISPLAY.md](docs/UNIFIED_DRIVING_DISPLAY.md) |
