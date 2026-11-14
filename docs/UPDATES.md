# Aggiornamenti dell'app (0.7.0)

## Cosa fa
A ogni avvio dell'app desktop, in background, viene interrogato l'elenco ufficiale delle release del repository GitHub
`carcifosupr3mo/RACE-ENGINEER-AI`. Se esiste una versione **stabile** più recente di quella installata:

| Interruttore «Aggiornamenti automatici» (Impostazioni → Aggiornamenti) | Comportamento |
|---|---|
| **Spento** (predefinito) | popup centrale «Nuovo aggiornamento disponibile» con versione installata, nuova versione e novità. **AGGIORNA** avvia l'installazione; **SALTA PER ORA** chiude il popup e l'app parte normalmente (il popup non ricompare finché l'app resta aperta) |
| **Acceso** | scarica, verifica e installa da solo, poi l'app si riavvia; al riavvio mostra «Aggiornamento completato» |

Senza Internet (o con GitHub che non risponde) il controllo viene saltato in silenzio e l'app parte normalmente.

## Quali release vengono usate
Solo release **non bozza**, **non pre-release** e con tag nella forma `vMAJOR.MINOR.PATCH` (es. `v0.7.1`). Un tag come `v0.7.0-rc1`,
un `nightly` o un branch non vengono mai offerti. Non si scarica mai codice sorgente.
**Conseguenza pratica:** le release pubblicate finora (`v0.6.x-rc1`) sono pre-release, quindi non vengono offerte come aggiornamento.
Per pubblicare una versione offerta agli utenti, usare il workflow `release` con `stable = true` e un tag `vX.Y.Z`.

Una release dichiara la propria compatibilità nelle note con una riga `min-update-from: X.Y.Z`: un'installazione più vecchia di quella
versione non viene aggiornata dall'app (l'utente è indirizzato alla pagina di download). Non si installano mai versioni più vecchie
o uguali a quella in uso.

## Schermata e passi (tutti reali, nessuna percentuale simulata)
1. Controllo aggiornamenti · 2. Download (byte scaricati / dimensione dichiarata da GitHub, con ripresa HTTP Range dopo un'interruzione, 3 tentativi)
· 3. Verifica (SHA-256 del file letto dal disco) · 4. Installazione (estrazione file per file) · 5. Riavvio.

## Sicurezza
* **Provenienza**: solo `https`, solo host GitHub (`api.github.com`, `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`),
  controllati anche a ogni redirect; il pacchetto deve stare sotto `/<repo>/releases/download/` di una release restituita dall'API ufficiale.
* **Integrità**: il pacchetto `RaceEngineerAI-win32.zip` deve comparire in `SHA256SUMS.txt` **della stessa release** e l'hash deve coincidere,
  altrimenti nulla viene installato. Limite onesto: questo protegge da file corrotti/troncati, non da chi può pubblicare release sul repository;
  per quello serve la firma del codice ([CODE-SIGNING.md](CODE-SIGNING.md)), non ancora attiva.
* **Struttura del pacchetto**: deve contenere `RaceEngineerAI.exe` e `RaceEngineerUpdater.exe`; percorsi che escono dalla cartella di estrazione
  (zip-slip) fanno rifiutare il pacchetto.
* **Spazio su disco**: si controlla prima del download (≈3,5× la dimensione del pacchetto); messaggio chiaro se manca.
* **Download temporaneo**: in `<cartella dati>/update/<versione>/`; l'app installata non viene toccata finché tutto è verificato.

## Installazione sicura: updater separato
Su Windows un programma in esecuzione non può sovrascrivere i propri file. Il pacchetto contiene perciò `RaceEngineerUpdater.exe`
(piccolo, solo libreria standard Python, `backend/race_engineer/updater/apply.py`). L'app ne **copia** una versione in una cartella temporanea,
la avvia e si chiude (la registrazione in corso viene salvata). L'updater:
1. attende l'uscita dell'app (elenco processi, nessun handle di processo);
2. **backup**: rinomina la cartella installata in `RaceEngineerAI.old-<versione>` (istantaneo, atomico, nulla viene copiato o perso);
3. sposta la nuova cartella al suo posto e **copia** nella nuova ciò che solo la vecchia conteneva (file aggiunti dall'utente);
4. avvia la nuova versione e la osserva 20 s: se si chiude subito con errore → **rollback** automatico e riavvio della vecchia;
5. se va tutto bene cancella il backup. Qualsiasi errore prima del punto 4 ripristina la cartella precedente.
L'esito (`update_result.json`, `update.log`) viene mostrato all'avvio successivo («Aggiornamento completato» oppure spiegazione dell'errore).
Se l'app non si chiude entro 90 s, l'updater non tocca nulla.

## Cosa non viene mai sovrascritto
I dati dell'utente stanno fuori dalla cartella del programma (`%LOCALAPPDATA%\RaceEngineerAI`: catalogo SQLite con simulatore scelto,
impostazioni e preferenze aggiornamenti, sessioni DuckDB, profili, memoria del coach). L'aggiornamento sostituisce solo la cartella del
programma. Inoltre, quando una versione cambia lo schema del catalogo, prima della migrazione viene creata la copia
`catalog.sqlite.before-vN.bak` (mai sovrascritta).

## Dove NON funziona l'installazione automatica
Esecuzione dai sorgenti, sistemi diversi da Windows, installazioni senza `RaceEngineerUpdater.exe`: l'app segnala la nuova versione e
rimanda alla pagina di download (nessun tentativo di installare).

## Verifiche eseguite
`backend/tests/test_updater.py` (31 test con un finto GitHub su HTTP reale), `backend/tests/test_sims_and_updates_api.py`,
`scripts/e2e_home_update.py` (browser reale, 38 controlli), `scripts/test_updater_bundle.py` (processo updater reale: attesa, sostituzione, rollback;
eseguito in CI su Windows con l'exe congelato). Vedi CHANGELOG 0.7.0 per cosa è stato davvero eseguito e cosa no.

## Firma dei checksum (opzionale, da attivare)
Vedi `docs/RELEASE.md`. Con `PUBLIC_KEY_HEX` vuoto (stato attuale) l'app verifica solo SHA-256: protegge da file corrotti, **non** da chi può modificare la release. Con la chiave inserita, `SHA256SUMS.txt.sig` (Ed25519) è obbligatoria e una release senza firma valida viene rifiutata (`bad_signature`).
