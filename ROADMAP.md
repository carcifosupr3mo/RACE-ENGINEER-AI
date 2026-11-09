# ROADMAP
Una fase è "completata" solo se i criteri di accettazione sono rispettati **con le evidenze indicate**.

| Fase | Stato | Note |
|---|---|---|
| 0 Ricerca/architettura | ✅ completata *per quanto verificabile senza LMU* | strutture da fonti pubbliche; **nessuna verifica su LMU installato** |
| 1 Acquisizione Shared Memory | 🟡 implementata, **non accettata** | criterio "acquisisce dati reali" NON soddisfatto: serve LMU su Windows |
| 2 Registrazione e sessioni | ✅ implementata e testata con dati sintetici | giri completi/incompleti/invalidi, import DuckDB LMU → sessione, profili circuito; **non verificata su LMU reale** |
| 3 Lap Analyzer + Visualizer | ✅ implementata e testata con dati sintetici (pytest, vitest, Playwright) | manca editor grafico curve, selezione di punto/curva avanzata; **non validata su dati LMU reali** |
| 4 Race Engineer AI | ⬜ | solo dopo Fase 3; vedi [AI-GROUNDING](docs/AI-GROUNDING.md) |
| 5 Setup Advisor | ⬜ | usare `metadata.CarSetup` dei DuckDB e file setup reali |
| 6 Tyre & Fuel | ⬜ | |
| 7 Driver Development | ⬜ | |
| 8 Desktop + Web definitivi | ⬜ | PySide6, tray, LAN opzionale |
| 9 Ottimizzazione/packaging | ⬜ | PyInstaller |

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
