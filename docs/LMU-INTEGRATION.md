# LMU-INTEGRATION

## Stato di verifica (leggere per primo)
| Elemento | Stato |
|---|---|
| Esistenza dell'interfaccia nativa `LMU_Data` e requisito "Enable Plugins" | Documentato da terzi (TinyPedal README: *"no plugin required… make sure `Enable Plugins` is ON in Settings → Gameplay"*) |
| Layout binario (324 820 B) | Trascritto da mappatura di terzi, **non verificato su LMU** |
| Backend di lettura Windows (`OpenFileMappingW`) | Implementato, **mai eseguito** (sviluppo su Linux) |
| Backend di lettura file/`/dev/shm` | Implementato, testato con dati **sintetici** |
| Acquisizione reale da LMU | **NON VERIFICATA** |
| Posizione su disco dell'opzione "Enable Plugins" | **Sconosciuta**: la scansione `UserData/player/*.json` è solo un indizio |
| Plugin legacy rFactor 2 | Non usato, non installato. Va valutato solo come fallback dopo verifica di compatibilità |

## Ambiente di sviluppo della Fase 0/1
Linux (container cloud), nessuna installazione LMU, nessun Steam, nessuna cartella `UserData`. Perciò non è stato
possibile ispezionare versione del gioco, mapping reale, né file DuckDB reali. Le informazioni sulle strutture
provengono da repository pubblici (elencati in TELEMETRY-FORMAT.md).

## Principi di sicurezza dell'acquisizione
- Solo lettura: Windows `OpenFileMappingW(FILE_MAP_READ)` + `MapViewOfFile(FILE_MAP_READ)`; non crea mai il mapping
  (a differenza di `mmap(-1, size, tagname)` che ne crea uno vuoto se il gioco è chiuso), non apre handle al processo,
  nessuna iniezione, nessuna modifica di eseguibile/config/EAC.
- Il rilevamento del processo usa solo l'elenco processi (`tasklist` / `/proc`).
- Mai modificare `config.json` o le impostazioni di LMU; mai installare plugin.
- DuckDB originali aperti `read_only=True`, opzionalmente su copia scratch.

## Macchina a stati
`Simulatore non rilevato → Simulatore avviato → Attesa della sessione → Connessione Shared Memory attiva →
Acquisizione attiva → Sessione terminata`, più `Errore di acquisizione`.
- *non rilevato*: nessun processo e nessun mapping; *avviato*: processo presente ma mapping assente (tipico di
  Enable Plugins disattivo o gioco in caricamento); *attesa sessione*: mapping valido ma `playerHasVehicle=false`;
  *connessa*: mapping valido, nessun nuovo campione da >2 s (menu/pausa); *acquisizione*: `mElapsedTime` avanza;
  *terminata*: `mGamePhase==8` o veicolo del giocatore sparito dopo acquisizione; *errore*: mapping troppo piccolo/eccezione.
- Riconnessione automatica ogni secondo; la perdita del mapping chiude la sessione come `incomplete` (dati conservati).

## Procedura guidata (fallback 3.4)
`GET /api/diagnostics/report` (e pannello UI) esegue: piattaforma → installazione → UserData → Telemetry → processo →
mapping → dimensione mapping vs layout → drift nomi campi vs header installati → indizi impostazione plugin. Per ogni
controllo fallito indica la correzione (es. attivare *Enable Plugins* e riavviare completamente LMU).

## Come completare la verifica con LMU aperto (Windows)
1. LMU: Settings → Gameplay → **Enable Plugins = ON**, riavviare LMU. Entrare in pista (anche Practice/Test Day).
2. `python -m race_engineer diagnose` → atteso: `mapping` OK, `mapping_size` OK, `header_drift` senza campi mancanti.
3. `python -m race_engineer record --seconds 30` → osservare `hz`, `lost`, valori plausibili (velocità, giri, marcia,
   pedali, sterzo). Confrontare con il cruscotto di LMU.
4. Segnalare: valore di `mapping.size`, `effective_hz`, `gameVersion`, eventuali campi mancanti. Solo allora
   aggiornare questa tabella a "verificato" con data/versione del gioco.
