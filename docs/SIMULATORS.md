# Simulatori: cosa è supportato e cosa no (0.7.0)

Regola: un simulatore è «Supportato» (selezionabile) **solo se l'app contiene il codice che ne legge davvero i dati**. Il registro è
`backend/race_engineer/sims.py`. Le colonne «canale dati» sono ciò che la documentazione pubblica / gli SDK della community descrivono; **non è stato
verificato nulla di tutto ciò dentro questa app né con i giochi installati** (l'ambiente di sviluppo è Linux, senza giochi).

| Simulatore | Stato nell'app | Canale dati (da documentazione pubblica, non verificato qui) | Configurazione nel gioco |
|---|---|---|---|
| Le Mans Ultimate | **Supportato** (lettura implementata; ancora **non verificata con il gioco reale**, vedi LMU-INTEGRATION.md) | Shared Memory `LMU_Data`, ~250 Hz; file DuckDB nativi | «Enable Plugins» attivo |
| Assetto Corsa Competizione | In arrivo | Shared Memory physics/graphics/static + Broadcasting API (UDP) | nessuna (broadcasting: `broadcasting.json`) |
| Assetto Corsa | In arrivo | Shared Memory `acpmf_*` + UDP Remote Telemetry | nessuna |
| Assetto Corsa EVO | Da verificare | interfaccia dati non documentata in modo affidabile (accesso anticipato) | sconosciuta |
| iRacing | In arrivo | irsdk (memory-mapped file, 60 Hz) + file .ibt | nessuna |
| rFactor 2 | In arrivo | plugin community «Shared Memory Map» | installare e attivare il plugin |
| Automobilista 2 | In arrivo | Shared Memory formato Project CARS 2 + UDP | attivare «Shared Memory» |
| RaceRoom Racing Experience | In arrivo | Shared Memory `$R3E` | nessuna |
| F1 (serie recente) | In arrivo | UDP Telemetry (porta 20777), formato diverso ogni anno | attivare «UDP Telemetry» |
| Project CARS 2 | In arrivo | Shared Memory + UDP | attivare «Shared Memory» |

Per promuovere un simulatore a «Supportato»: lettore dedicato (come `lmu/reader.py` + `decode.py`), motore di acquisizione per quel gioco, test con
dati sintetici **e** con il gioco reale, poi `status=SUPPORTED` in `sims.py`. Finché non è fatto, l'API rifiuta la selezione (HTTP 409) e l'interfaccia
la mostra disattivata.

## Separazione dei dati tra simulatori
* `sessions.sim` e `goals.sim` (migrazione 6; tutto il già registrato è `lmu`): elenco sessioni, storico pilota e obiettivi filtrano per simulatore scelto.
* Le impostazioni per gioco usano il prefisso `sim.<id>.` (`Catalog.get_sim_setting/put_sim_setting`).
* **Limite attuale**: la memoria del coach (`coach_tips`, `coach_habits`, `coach_laps`) è indicizzata per circuito/vettura senza simulatore. Con un solo simulatore
  selezionabile non può mescolare nulla; va estesa con una colonna `sim` quando verrà aggiunto un secondo gioco.
* La scelta è salvata nel catalogo (`app.selected_sim`), non nel browser: sopravvive a chiusura, riavvio del PC e aggiornamenti.
