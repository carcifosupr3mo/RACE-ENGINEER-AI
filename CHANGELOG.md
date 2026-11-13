# CHANGELOG
## 0.6.6 (non rilasciata) — Analisi circuito con mappa a colori, testi più chiari, display da telefono
- **Analisi circuito:** la pista è disegnata con ogni zona colorata in base al tempo che perdi (verde = costante, rosso = lì perdi di più), le zone dove perdi più tempo e le tue curve migliori in frasi semplici, e una tabella zona per zona. La mappa dei nomi delle curve è ora facoltativa e ripiegata.
- **Tutto più leggibile:** menu e titoli in italiano («Analisi giri», «Gomme e benzina»…), una riga che spiega cosa fa ogni pagina, testo più grande.
- **Display da telefono/altro PC:** se l'indirizzo non contiene il codice di accesso (`?token=…`) la pagina si apriva ma restava su «Connessione al PC in corso…» senza spiegare perché. Ora dice chiaramente che manca (o è sbagliato) il codice e dove trovare l'indirizzo completo; il browser ricorda il codice una volta usato. Verificato lato server: dall'indirizzo di rete il flusso dati parte con il codice e viene rifiutato senza.
- Corretto: la prima zona del giro (dal traguardo) non compariva nel riepilogo.
## 0.6.5 (non rilasciata) — Correzioni dai test su Le Mans Ultimate reale, analisi giri, display in rete
Corretto dopo la prova su un PC con LMU reale (Monza):
- **Lap Analyzer: «alignment quality too low» / errore 500.** Nei dati reali il contatore del giro e la distanza di giro non cambiano sullo stesso campione al traguardo: i primi campioni del giro sembravano a ~fine pista e il giro veniva scartato (copertura 0 %). Ora la distanza viene riallineata (`unwrap_lap_distance`), anche per live/coach. Tempo del giro: il valore del gioco arriva in ritardo (primi campioni «vecchi»); si usa la mediana e, se diverge dall'orologio di oltre 0,5 s, l'orologio (con nota). Piccoli buchi (≤ 0,5 s) non invalidano più il giro: finiscono nelle note. Errori ora in italiano e comprensibili (422, non 500). Test su difetti riprodotti (falliscono senza la correzione).
- **Track Analysis:** un profilo circuito vuoto non risulta più «confermato dall'utente» e non si può salvare vuoto; messaggio chiaro quando non si trovano curve.
- **Live Telemetry:** «persi 50500» era tempo passato in garage/menu (il tempo del gioco salta mentre la telemetria non si aggiorna), non campioni persi. Salti > 2 s sono ora «pause» (`pause_events`, `paused_s`), solo i buchi brevi sono «persi». Schermata Live rifatta: stato (In pista / Ai box / Fermo in garage o menu), giri e tempi, comandi con frizione, carburante e temperature, quattro gomme, danni, condizioni meteo.
- **AI:** NVIDIA «empty completion»: i modelli che ragionano finivano i token pensando e non rispondevano; ora un nuovo tentativo con più token, test del collegamento con 256 token. Errori in italiano con il link per creare la chiave (NVIDIA / Groq).
- **Display in rete (LAN) con interruttore ON/OFF nell'app** (Impostazioni e menu dell'icona): niente più `--lan` da riga di comando. Apre un secondo ascolto sulla rete, spento di default; i PC remoti hanno sempre bisogno del token (che resta stabile tra i riavvii), solo questo PC può accenderlo/spegnerlo. Windows può chiedere il permesso di rete la prima volta.
- **La X chiude davvero l'app** (prima restava nascosta nella barra di sistema): registrazione chiusa e salvata, nessun processo rimasto. Più leggera: un solo processo di rendering web con memoria JavaScript limitata, servizi di rete in background spenti, e quando il gioco non è collegato il lettore dorme (CPU a riposo ~0) invece di interrogare 250 volte al secondo.
- **Analisi giri molto migliore:** nuovo riepilogo di sessione (`/api/sessions/{id}/report`): giro ideale dai migliori tempi di ogni zona (curve e rettilinei), margine teorico, mappa a colori del tempo perso giro per giro, costanza e andamento, consigli in ordine di guadagno. Le note dei giri compaiono nella tabella.
### Già nella 0.6.4 (mai rilasciata) — Firma digitale pronta, aggiornamento con l'app aperta
- **Firma digitale (Authenticode): pipeline pronta, manca solo il certificato.** `scripts/sign_windows.py` firma exe, installer e disinstallatore con marca temporale e controlla ogni firma; la build fallisce se una firma richiesta non risulta. Senza certificato la build resta **non firmata e lo dichiara** (log, `SIGNING.txt`, `build_info.json`, note della release). Il certificato arriva dai segreti di GitHub Actions e viene tolto dall'ambiente prima di npm/pip/test. Istruzioni e opzioni: `docs/CODE-SIGNING.md`.
- CI: prova della pipeline di firma su Windows con un certificato usa e getta, solo su copie (`scripts/test_signing_windows.py`).
- **Aggiornamento e disinstallazione con l'app aperta.** Chiudere la finestra la nasconde solo nella barra di sistema, quindi l'installer trovava i file in uso. Ora installer e disinstallatore chiedono alla copia in esecuzione di chiudersi in modo pulito (`RaceEngineerAI.exe --quit`: registrazione chiusa, dati salvati) e solo come riserva la terminano.
- **Difetto di CI corretto:** lo smoke test della copia *installata* non poteva far fallire la build (il suo codice di uscita veniva sovrascritto dal comando successivo). Nuovo `scripts/windows/tests/Test-Installer.ps1`: installazione, smoke, uscita pulita, aggiornamento e disinstallazione con l'app aperta, ognuno con esito verificato.
- Gli exe dichiarano prodotto e versione (Proprietà → Dettagli); l'installer dichiara autore, versione e indirizzi di supporto.
- Log dell'app: riga «started» con versione e porta.
## 0.6.3 (non rilasciata) — Finestra cmd all'avvio, sicurezza
- **Finestra nera (cmd) all'avvio dell'exe: corretta.** Causa: per sapere se LMU è aperto l'app lancia `tasklist`; da un exe senza console Windows apriva una finestra cmd a ogni controllo (all'avvio e poi ogni 2 s finché LMU non è collegato). Ora il processo è avviato con `CREATE_NO_WINDOW`. Test di regressione (fallisce senza la correzione).
- **Sicurezza:** `tasklist` è chiamato con percorso assoluto in `System32` (prima era cercato anche nella cartella dell'app / corrente, dove un exe estraneo con lo stesso nome sarebbe stato eseguito).
- **Sicurezza:** in modalità locale (senza token) l'API rifiuta le richieste provenienti da un altro sito (`Origin` estraneo o `Sec-Fetch-Site: cross-site`): una pagina web aperta nel browser non può più pilotare l'app. Test di regressione.
- **Installer:** la versione era rimasta `0.1.0`, quindi un installer nuovo vedeva «stessa versione già installata» e riavviava la copia vecchia senza aggiornarla. Versione portata a 0.6.3 (unica fonte: `race_engineer.__version__`, usata anche da `build_info.json`).
- **Nuovo — secondo avvio:** se l'app è già aperta (di solito nascosta nella barra di sistema), un secondo doppio clic ne riporta la finestra in primo piano invece di mostrare solo un avviso.
- **Nuovo — menu dell'icona nella barra di sistema:** versione installata, «Apri cartella dati», «Apri cartella log», «Scarica aggiornamenti» (apre la pagina delle release nel browser; l'app non contatta la rete da sola) e «Avvia con Windows (ridotto a icona)» (facoltativo, solo utente corrente, nessun diritto di amministratore).
- **Nuovo:** la finestra principale ricorda dimensione e posizione.
- **Tolto — seconda finestra indesiderata:** i collegamenti normali usano `--display-auto`: il Driving Display si apre da solo all'avvio solo se c'è un secondo monitor. Con un solo monitor non compare più una seconda finestra sopra la principale (resta disponibile con `Ctrl+D`, dal menu e dal collegamento «Avvia con Driving Display»).
- Collegamento del menu Start «Avvia con Driving Display»: ora avvia direttamente l'exe (porta 8765) invece del `.bat`, quindi senza finestra cmd.
## 0.6.2 (non rilasciata) — Verifica pre-test reale
- **Run 17 (`193f0ce`, solo documentazione) fallita** nel job `display-e2e` con codice identico alla run 16 verde: l'e2e cercava un consiglio la cui finestra (errore su 3 giri) dipendeva dalla velocità della macchina. Il test era non deterministico; nuovo scenario sintetico `persistent` (errore su tutti i giri) usato da CI/e2e. Nessun cambiamento al comportamento del coach per questo.
- **Difetto reale corretto (audit unità/valori mancanti):** un buco di telemetria ≤ 50 m (NaN) sul gas dopo l'apice veniva letto come «gas chiuso» → falso `delayed_acceleration` con confidenza «alta». Ora metrica non misurabile se mancano campioni (gas prima della ripresa, freno nella finestra di frenata). Test di regressione (fallisce senza la correzione).
- e2e: controllo che il testo «come» sia ≤ 3 righe e che il riquadro resti nello schermo (anche 800×480), con osservazione effettiva.
- `docs/COACHING.md` §6: tabella delle unità per ogni segnale.
## 0.6.1 (non rilasciata) — Audit del coaching
- **Run 15 (commit solo documentale) fallita** nel job `display-e2e`: a 800×480 il riquadro dell'istruzione usciva dallo schermo (la spiegazione lunga rendeva il riquadro troppo alto). Causa reale: il Display mostrava testo lungo anche in guida. Corretto: in guida solo titolo + «come» (max 3 righe); perché/obiettivo/abitudine e analisi completa solo sotto 30 km/h.
- Un rilievo diventa consiglio solo se ripetuto in ≥ 2 degli ultimi 3 giri analizzati (un giro cattivo isolato è rumore); il primo consiglio non arriva prima del 3° giro analizzato.
- Confrontabilità non verificabile (pioggia/temperatura pista ignote su un giro, p.es. riferimento di un'altra sessione): confidenza limitata a «media» e esito del consiglio NON giudicato (`non_verificabile`).
- «Applicato» solo dopo 2 giri consecutivi senza il problema (`miglioramento_osservato` al primo): nessun «applicato» per un singolo giro fortunato.
- Nuovo scenario sintetico `repeated` (stesso errore su 3 giri); CI e2e lo usa al posto di `mixed` (errori isolati ⇒ nessun consiglio, voluto).
- Docs: `docs/COACHING.md` (canali, soglie con avvertenza «euristiche», limiti), procedura reale in 16 passi con PASS/FAIL e scenario B (condizioni diverse), `ROADMAP.md`.
## 0.6.0 (non rilasciata) — Ingegnere di pista AI (coaching)
- **Coaching dentro l'unico motore**: `live/coach.py` è un componente del `LiveEngineer` (nessun secondo motore/acquisitore/analizzatore). Riusa `analysis.driving.analyse`.
- Nuovi rilievi sull'intera curva: trail braking insufficiente/eccessivo, gas aggressivo, scelta marcia (con guardie anti-contraddizione).
- **Istruzioni strutturate** in italiano, solo testo (`live/instructions.py`): cosa / dove / come / perché / obiettivo, evidenza misurata vs calcolata vs interpretata, dati mancanti dichiarati; metri solo con confidenza non bassa; numerazione curve provvisoria dichiarata.
- **Memoria persistente** nel catalogo esistente (migrazione 5: `coach_tips`, `coach_habits`, `coach_laps`; nessun secondo DB). Ciclo di vita nuovo → mostrato → applicato | da_rivalutare | non_verificabile, esito misurato sui giri successivi (seguito/parziale/non seguito/peggiorato/non confrontabile), distinzione abitudine / occasionale / corretto, ri-valutazione dell'ipotesi (priorità ridotta, mai ripetuto all'infinito), niente consigli opposti ravvicinati, preferenze configurabili. Dati reali e sintetici separati.
- **Analisi di fine giro** (`Coach.review`): vs miglior giro, giro precedente, curve migliorate/peggiorate, tempo guadagnato/perso, errori ricorrenti, consigli valutati, prossimo obiettivo; giri in condizioni non confrontabili (pioggia, temperatura pista) non giudicano né creano consigli.
- API: `/api/coach/{review,summary,tips,progress,prefs}`. Checklist live con 3 nuovi passi (istruzione, analisi di fine giro, memoria).
- **Driving Display** riprogettato come schermo del coach: istruzione grande, come/perché/obiettivo, nota abitudine/ri-valutazione, pannello analisi di fine giro, mappa secondaria; silenzioso (solo istruzione) nelle manovre impegnative.
- Test: nuovi `tests/test_coach.py` (13) e +4 in `test_driving_analysis.py`; e2e display esteso; smoke con controlli coach. Nessuna verifica con LMU reale.
## 0.5.0 (non rilasciata) — Sistema unificato con doppio display
- **Un solo ingegnere di pista**: nuovo `LiveEngineer` (stato condiviso) agganciato all'unico `AcquisitionEngine`; nessun secondo motore/flusso/agente AI. Dettagli in `docs/UNIFIED_DRIVING_DISPLAY.md`.
- Analisi di guida per fasi (frenata, rilascio, apice, gas, uscita, tempi ingresso/centro/uscita) con giudizio sull'intera curva (la frenata più tardi non è automaticamente migliore) e confidenza (`analysis/driving.py`).
- Riferimento personale progressivo e persistente per circuito/vettura, sintetico separato (`analysis/reference.py`); adattamento automatico al tipo di sessione (`analysis/session_mode.py`).
- Arbitro dei suggerimenti: uno solo, legato alla curva, con affidabilità; congelato in guida impegnativa; stato «apprendimento» se i dati non bastano; allarmi dalle soglie dell'EventDetector (`live/suggestions.py`).
- AI: nuovi fatti di guida, interpretazione periodica via la coda AI esistente (aggregati, grounding); la pipeline endurance ignora le risposte di altri tipi.
- API: `/api/engineer/{state,map,events,reference,status}`, `/api/sessions/{id}/driving`, `/api/display/info`, `/driving-display`; il WebSocket `/ws/live` porta `engineer` + `events`.
- **Driving Display** (`/driving-display`, stesso bundle, chunk separato ~13 kB senza Plotly): mappa interattiva dai dati di posizione reali, delta, velocità, marcia, giri, pedali, curva attuale/prossima, un suggerimento, allarmi, riconnessione automatica e stato offline; dashboard: blocco «Ingegnere di pista» nella Live, sezione «Driving Display», tabella di analisi di guida nel Lap Analyzer.
- Shell desktop: voce di menu «Apri Driving Display (secondo monitor)», `Ctrl+D`, `--display`, `--lan` (opt-in, token) e «Driving Display in rete». CLI: `serve --lan` stampa l'URL del display; `--synthetic-speed` per test/demo.
- Test: +25 pytest (184 totali), +4 vitest, e2e Playwright del display, smoke 29 controlli (7 nuovi). Nessuna verifica con LMU reale.
## 0.4.1 (non rilasciata)
- Procedura Windows guidata `PROCEDURA_VERIFICA.ps1`: preflight, registrazione >= 60 s con marcature HUD, report DuckDB/setup, riepilogo, controllo integrita' originali e report salvati. Test PowerShell in CI.
- Nuovi comandi `preflight`, `hud-compare`, `verification-summary`; commit registrato in `build_info.json`.
- Fix: `verify-lmu` non puo' piu' risultare reale con `--shm-path`; mapping non raggiungibile => codice 3; report mai sovrascritti.

## 0.3.0 — Fasi 4-9 (parziali, vedi ROADMAP)
- AI: base fatti, ingegnere a regole, provider-agnostic (OpenAI-compatibile/Anthropic), budget/timeout/fallback, validatore anti-allucinazione, chat persistente.
- Tyre & Fuel, Driver Development (storico, obiettivi, allenamenti), Setup Advisor conservativo, migrazione SQLite 3.
- UI: Race Engineer AI, Tyre & Fuel, Driver Development, Track Analysis (editor curve), Setup Advisor.
- Shell desktop PySide6 (tray, notifiche, chiusura controllata), spec PyInstaller e `scripts/build.py`.
## 0.2.0 — Fasi 2/3
- Giri completi/incompleti/invalidi, tempi con origine, riepilogo solo su giri validi.
- Allineamento per distanza con controlli di qualità; rilevazione curve provvisorie; profili circuito (SQLite migrazione 2).
- Confronto giro/riferimento con osservazioni numeriche; costanza tra giri.
- Import dei DuckDB nativi LMU come sessioni (provenienza `duckdb_import`, originale intatto).
- API analisi (`/api/sessions/{id}/laps|corners|trace|compare|consistency`, `/api/tracks/profile`, `/api/import/duckdb`).
- Frontend React 18 + TypeScript + Vite + Plotly: navigazione a 10 sezioni, Live, Sessions, Lap Analyzer (7 grafici sincronizzati, mappa, curve, osservazioni).
- Scenario sintetico `mixed`; test pytest (68), vitest (4), e2e Playwright (11 controlli).
## 0.1.0 — Fase 0/1 (non rilasciata)
- Ricerca strutture `LMU_Data` e DuckDB da fonti pubbliche; documentazione con stato di verifica.
- Layout ctypes, reader sola lettura (Windows/file/buffer), decoder con provenienza, catalogo canali (73).
- Motore di acquisizione: macchina a stati, dedup, stima perdite, riconnessione, sessioni, statistiche.
- Storage: SQLite (migrazioni, backup, recupero sessioni interrotte), recorder DuckDB con checkpoint.
- Importer DuckDB LMU in sola lettura con diagnostica canali.
- Simulatore sintetico deterministico (8 scenari) che scrive nel layout reale; fixture DuckDB sintetico.
- API FastAPI + WebSocket + UI diagnostica; CLI `diagnose|serve|record|inspect-duckdb|layout`.
- 52 test pytest.
