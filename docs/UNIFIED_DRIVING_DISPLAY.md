# UNIFIED DRIVING DISPLAY — un solo ingegnere di pista, due modalità di presentazione

Stato: implementato e verificato **solo con dati sintetici** (test automatici, smoke, CI Windows senza LMU).
**Nessuna verifica con Le Mans Ultimate reale**: lettura shared memory, offset, posizione/orientamento dei canali `pos_x_m/pos_z_m`,
nomi circuito/vettura e frequenza reale sono ancora da provare con il gioco (vedi «Verifiche reali ancora necessarie»).

## 1. Piano tecnico (fatto PRIMA di scrivere codice)

Analisi del repository esistente: l'app aveva già **un solo** acquisitore (`acquisition/engine.py` → shared memory in sola lettura →
`Sample`), **un solo** registratore/Session Manager (`storage/*`, catalogo SQLite + DuckDB per sessione), **un solo** motore di analisi
(`analysis/laps|align|corners|compare`), **un solo** livello AI (`ai/facts → engineer/chat → provider`, catena di provider gratuiti con coda,
quota e validatore di grounding), **un solo** backend (`api/app.py`, REST + WebSocket `/ws/live`) e **una** UI React servita da `/app/`.
Mancavano: (a) analisi di guida per fasi della curva, (b) un riferimento personale progressivo, (c) lo stato live condiviso (la UI live
mostrava solo i campioni grezzi), (d) l'adattamento al tipo di sessione, (e) una presentazione adatta alla guida.

| Capacità richiesta | Componente esistente | Cosa è stato fatto |
|---|---|---|
| Acquisizione shared memory | `AcquisitionEngine` | **Riutilizzato**, invariato (un solo lettore; il live engineer si aggancia con `on_sample`, come già fa la pipeline endurance) |
| Session Manager / giri | `storage/*`, `analysis.laps.segment_laps` | **Riutilizzato**: la validità dei giri live usa la STESSA `segment_laps` |
| Allineamento/delta | `analysis.align` | **Riutilizzato** (`align_lap`, griglia 1 m, stessa origine temporale) |
| Analisi curve/frenata | `analysis.corners`, `compare.corner_metrics` | **Esteso**: `analysis/driving.py` chiama `corner_metrics` e aggiunge fasi e giudizio sull'intera curva |
| Motore strategia/risorse | `endurance.detector` (carburante, gomme, stint, eventi) | **Riutilizzato**: allarmi e risorse leggono lo STESSO `EventDetector` e le sue soglie |
| Motore AI | `ai/facts`, `engineer`, `providers/*` | **Esteso**: nuovi fatti `driving_finding/driving_gain/mode`, nuovi consigli; interpretazione periodica via la STESSA coda AI |
| Memoria/storico | `driver`, `race_memory`, catalogo | **Esteso**: riferimento personale persistente (`analysis/reference.py`) |
| Backend / WebSocket | `api/app.py`, `/ws/live` | **Esteso**: nuovo campo `engineer` + `events` nello stesso WebSocket, endpoint `/api/engineer/*`, pagina `/driving-display` |
| UI | React `/app/` | **Esteso**: stesso bundle, seconda rotta `/driving-display`; la dashboard mostra lo stesso stato |

Non esiste un secondo motore, un secondo flusso di telemetria o un secondo agente AI.

## 2. Architettura finale

```
LMU shared memory (sola lettura)
        │  AcquisitionEngine (unico lettore, macchina a stati, registrazione)
        ├──► SessionRecorder / Catalog          (Session Manager, DuckDB per sessione)
        ├──► EnduranceService → EventDetector   (carburante, gomme, stint, eventi; coda AI)
        └──► LiveEngineer  ◄── UNICO stato condiviso
               buffer giro → segment_laps → align_lap → driving.analyse(vs PersonalReference)
               → PersonalReference.add → Arbiter (1 suggerimento) + alert → [AI: coda esistente, solo aggregati]
                         │
          snapshot() ────┼──► /ws/live  (campo "engineer", "events")   ──► Driving Display  (/driving-display)
                         ├──► /api/engineer/state|map|events|reference ──► Dashboard (Live Telemetry, Driving Display info)
                         └──► ai/facts.build_facts (stessa driving.analyse) ──► Race Engineer AI (chat)
Post-sessione: /api/sessions/{id}/driving  → la STESSA driving.analyse sulla sessione registrata (Lap Analyzer)
```

Garanzie di coerenza (testate in `backend/tests/test_live_engineer.py`):
* **Stesso stato**: il campo `engineer` del WebSocket è identico (a meno di `connection`/`server_time`) a `GET /api/engineer/state`; dashboard e display leggono lo stesso `snapshot()`.
* **Stessa analisi live/offline**: per gli stessi giri, le osservazioni calcolate dal live engineer e da `/api/sessions/{id}/driving` coincidono (corsia, tipo, fase, evidenze, impatto temporale).
* **Un nuovo giro o un nuovo riferimento è visibile ovunque**: eventi `lap_completed`, `reference_changed`, `analysis_ready`, `suggestion_changed` in `events`; `reference.version` e `map_version` cambiano per entrambe le interfacce.

## 3. Nuove funzioni centrali

### 3.1 Analisi di guida (`analysis/driving.py`)
Per ogni curva, quando i dati lo permettono: punto di frenata, picco e progressione della pressione (`brake_ramp_m`), lunghezza della frenata,
punto e brusquezza del rilascio (`release_span_m`), velocità di ingresso, velocità minima e punto d'apice, primo/pieno gas, velocità di uscita,
tempo di **ingresso / centro / uscita** (dall'asse temporale allineato per distanza) e delta rispetto al riferimento.

Osservazioni (`DrivingFinding`): `early_braking`, `inefficient_late_braking`, `braking_too_long`, `abrupt_release`, `delayed_acceleration`,
`insufficient_min_speed`, `inefficient_line`, `entry_loss`/`mid_loss`/`exit_loss`. Ognuna riporta le misure (evidenze), l'impatto sul tempo
della fase, la **confidenza** (livello + punteggio + motivi) e la provenienza `computed`.

**Una frenata più tardi NON è automaticamente migliore**: viene giudicata sull'intera curva. Se frena più tardi *e* il tempo complessivo
della curva migliora, il risultato è un **guadagno** (`late_braking_gain`), non un errore; è segnalata `inefficient_late_braking` solo se, oltre a frenare più tardi,
si perde velocità minima/uscita/tempo. Lo scenario sintetico `late_brake` (frenata più tardi e più forte, stesso tempo) non genera errori (test).

Soglie e limiti: `DrivingThresholds` (frenata ±15 m, minima 2 km/h, uscita 3 km/h, gas 15 m, fase 0,03 s…). Sono valori generici, **non tarati su LMU reale**.
La confidenza = affidabilità del riferimento × (entità dell'effetto, tempo perso); con pochi giri di riferimento resta «bassa».

### 3.2 Riferimento personale progressivo (`analysis/reference.py`)
Per (circuito, vettura): i migliori giri validi (max 8, entro il 107 % del migliore) con canali allineati e posizione. Il più veloce è l'*ancora*
(asse del delta, geometria della mappa). L'affidabilità cresce con il numero di giri (apprendimento → bassa → media → alta, penalizzata dalla dispersione e dalle curve provvisorie).
Per ogni curva si conserva anche il **miglior passaggio** (tempo di zona minimo) come obiettivo. Persistenza: `data/references/*.npz`;
i riferimenti **sintetici sono in file separati** (`synthetic_*`) e non possono diventare il riferimento di una sessione reale. Un file corrotto non blocca nulla (si riparte da zero, il file resta).

### 3.3 Adattamento automatico alla sessione (`analysis/session_mode.py`)
Stesso motore, pesi diversi per l'arbitro dei suggerimenti: prove libere/test (tutte le perdite), qualifica (giro veloce, perdite per curva), gara (costanza, gomme, carburante),
endurance (stint, degrado, consumi; euristica: gara ≥ 60 min trascorsi o ≥ 3 stint), tipo non riconosciuto → modalità **generica**. Nessuna modalità separata, nessun altro motore.

### 3.4 Intelligenza condivisa
* Tempo reale **deterministico** (nessuna chiamata LLM per campione): analisi a fine giro su thread dedicato, tick a 10 Hz O(1).
* L'AI interpreta: `driving_analysis` è una richiesta periodica (un giro) alla coda AI **esistente** (aggregati, mai campioni grezzi, mai per sessioni sintetiche, quota e fallback invariati); il testo è accettato solo se supera il controllo dei numeri (`ungrounded_numbers`).
* Chat/ingegnere (`ai/facts`, `ai/engineer`): nuovi fatti `driving_finding`, `driving_gain`, `mode` ricavati dalla stessa `driving.analyse`.

### 3.5 Arbitro dei suggerimenti (`live/suggestions.py`)
* **Un solo** suggerimento principale, breve (es. «P2: frena ~41 m più tardi»), legato a una curva, con livello di affidabilità, impatto temporale e numero di giri in cui si ripete.
* Priorità = peso della modalità × confidenza × impatto × ripetizione; isteresi di 6 s; con la curva successiva entro 700 m si preferisce il suo suggerimento.
* **Non disturba durante manovre impegnative**: in curva, in frenata o con sterzo > 0,30 il suggerimento è congelato (`frozen`); solo gli allarmi `critical` (carburante critico, motore in surriscaldamento) interrompono.
* Dati insufficienti (meno di 2 giri validi nel riferimento) → stato **apprendimento** con messaggio esplicito, nessun suggerimento inventato.
* Allarmi importanti (carburante, gomme, motore, pioggia, danni) dalle stesse soglie dell'`EventDetector`.

## 4. Driving Display

Seconda **modalità di presentazione della stessa app** (stesso bundle, rotta `/driving-display`), ottimizzata per un monitor esterno da 10–13″, leggibile anche a 7″ (800×480). Contiene solo l'essenziale:
mappa interattiva (posizione auto, traiettoria del giro in corso, zone di frenata/rilascio/accelerazione, curva attuale e prossima, tap su una curva per i dettagli, zoom/pan/«segui»),
delta, velocità, marcia, giri motore (barra), gas/freno, curva attuale/prossima, **un** suggerimento con affidabilità, allarmi importanti, stato di apprendimento, ultimo giro e migliore, modalità sessione, banner «DATI SINTETICI».

* **La mappa è costruita dai campioni reali di posizione** (`pos_x_m/pos_z_m`) del giro di riferimento: nessuna geometria o punto di frenata è inventato. Senza posizione disponibile mostra «Sto costruendo la mappa…» e non disegna nulla. Orientamento: assi di gioco (x a destra, z in alto); **non verificato** rispetto al nord/alla pista reale.
* Il display **non calcola nulla**: mostra lo stato calcolato dal PC. Un Raspberry/tablet riceve solo risultati.
* Resilienza: riconnessione automatica con back-off (0,8 s → 5 s), stato offline esplicito se non arrivano dati per 2,5 s (valori attenuati, nessun dato finto), nessuno stato perso al ritorno della rete (il WebSocket riparte dallo stato corrente).
* Leggero: nessun grafico Plotly nella pagina (il display carica un chunk di ~13 kB; la dashboard lo scarica solo in `/app/`).

## 5. API e WebSocket (un'unica infrastruttura)

| Endpoint | Descrizione |
|---|---|
| `WS /ws/live` | esteso: `{sample, status, context, engineer, events}`; `engineer` = stato condiviso (senza mappa), `events` = eventi dall'ultimo messaggio |
| `GET /api/engineer/state[?full=1]` | stato condiviso (`full` aggiunge mappa, scia del giro, ultima analisi, riferimento) |
| `GET /api/engineer/map` | mappa dai dati reali: punti `[x,z,distanza]`, curve, zone, obiettivi; oppure `available:false` + motivo |
| `GET /api/engineer/events?since=N` | eventi con numero progressivo |
| `GET /api/engineer/reference` · `/status` | riferimento personale, stato interno (contatori, errori) |
| `GET /api/sessions/{id}/driving?lap=&ref=` | analisi di guida post-sessione (stessa funzione del live) |
| `GET /api/display/info` | URL del display (monitor locale e LAN, con token se `--lan`) |
| `GET /driving-display` | pagina del display (stesso bundle di `/app/`) |

Schema dello stato (`schema: 1`): `session{mode…}`, `lap`, `inputs`, `position`, `delta`, `corner{current,next,dist_to_next_m,phase,demanding}`, `reference{version,laps,reliability,anchor}`,
`suggestion{state: learning|ready|frozen|quiet, main, frozen, learning}`, `alerts[]`, `last_lap`, `resources`, `ai_note`, `map_version`, `connection`, `synthetic`, `seq`.

## 6. Come aprire il Driving Display

**A — Secondo monitor collegato al PC (cavo)**
1. Avvia Race Engineer AI (installer o `RaceEngineerAI.exe`). Windows deve riconoscere il secondo monitor (Impostazioni → Schermo → «Estendi»).
2. Dall'icona nella barra di sistema: **«Apri Driving Display (secondo monitor)»** (o `Ctrl+D` nella finestra principale): si apre a tutto schermo sul monitor non principale (F11 per uscire dal tutto schermo). Oppure `RaceEngineerAI.exe --display`.
3. In alternativa, da qualunque browser del PC: `http://127.0.0.1:PORTA/driving-display` (la porta è mostrata in Dashboard → Driving Display; con la CLI: `race-engineer-cli serve` → 8765).

**B — Raspberry Pi / tablet in LAN (browser)**
1. Sul PC avvia con l'opzione esplicita `--lan`: `race-engineer-cli serve --lan --port 8765` (oppure `RaceEngineerAI.exe --lan`). Di default l'app è raggiungibile **solo dal PC**.
2. All'avvio vengono stampati il token e l'indirizzo completo: `http://IP-DEL-PC:8765/driving-display?token=…` (la tray: «Driving Display in rete…», lo copia negli appunti).
3. Sul Raspberry apri quell'indirizzo con Chromium (modalità kiosk: `chromium-browser --kiosk "http://IP-DEL-PC:8765/driving-display?token=…"`).
4. Se Windows Defender Firewall chiede l'autorizzazione per la rete privata, consentila (nessuna modifica a router o rete è necessaria). Il token protegge tutte le chiamate `/api` e `/ws`; non esporre la porta su Internet.

## 7. Cosa è stato verificato (e cosa no)

Vedi `docs/VALIDATION.md` (sezione «Sistema unificato») per l'esito dei test, della CI e dei checksum. In sintesi: test pytest sintetici (analisi, riferimento, modalità, stato condiviso, coerenza live/offline, WebSocket,
riconnessione, sicurezza LAN), vitest (formattazione, back-off), Playwright sul display (aggiornamento live, mappa, interazione, coerenza con la dashboard, offline/riconnessione, 4 viewport), smoke dell'exe congelato e della copia installata.

### Limiti e verifiche reali ancora necessarie
* **Nessuna prova con LMU reale**: mapping, offset, `gameVersion`, frequenza, `pos_x_m/pos_z_m` (assi, unità, orientamento), `mLapDist`, nomi pista/vettura e `mSession` (tipo sessione) vanno verificati con `verify-lmu` e il confronto con l'HUD.
* Le soglie dell'analisi di guida sono generiche (non specifiche per auto/pista); la confidenza è una stima basata su numero di giri e dimensione dell'effetto, non una probabilità.
* La numerazione delle curve è **provvisoria** (P1, P2…) finché non si salva un profilo pista; il cambio dell'ancora può rinumerare le curve rilevate automaticamente.
* Modalità endurance: euristica (≥ 60 min o ≥ 3 stint); la durata reale della gara non è letta dal gioco.
* Il giro di riferimento è il più veloce **valido** del driver, non un giro «ideale» composto.
* CI verde sul commit `e9675dc` (run 12, 5 job su 5; vedi `docs/VALIDATION.md`). Secondo monitor (posizionamento a tutto schermo su Windows con più schermi), tray, Raspberry reale, Wi-Fi reale e firewall **non sono stati provati** su hardware: coperti solo dalla CI Windows (senza monitor secondario) e da Chromium headless su Linux.
* L'interpretazione AI (`driving_analysis`) è provata solo con provider finti; nessuna richiesta reale NVIDIA/Groq.
* Installer/exe non firmati (SmartScreen può avvisare).

---

## 8. Audit di unicità (verificato sul codice, non solo dichiarato)

| Requisito | Dove vive (unico) | Come si è verificato |
|---|---|---|
| Un solo sistema di acquisizione | `acquisition/engine.py::AcquisitionEngine`, una sola istanza per processo (`desktop/main.py`, `__main__.py`); `lmu/verify.py` ne crea una **separata solo** per la registrazione di prova a riga di comando, mai insieme all'app | `grep AcquisitionEngine(` sul pacchetto |
| Un solo Session Manager | `AcquisitionEngine` + `storage/catalog.py` (catalogo/sessioni); `LiveEngineer` non ne ha uno proprio: segue `engine.session_id` / `ctx` | lettura del codice, `test_live_engineer.py` |
| Un solo Lap Analyzer | `analysis/laps.segment_laps` → `analysis/align.align_lap` → `analysis/driving.analyse`; usati dal live (`live/engineer.py`), dall'API offline (`/api/sessions/{id}/driving`) e dai fatti AI (`ai/facts.py`) | `test_live_analysis_equals_offline_driving_analysis_of_the_recorded_session` |
| Un solo motore AI | `ai/engineer.py` + `ai/providers.AIRequestQueue` (una coda per processo, creata in `endurance/service.py`); il live vi accoda solo `driving_analysis` | grep `AIRequestQueue(` |
| Un solo stato condiviso | `LiveEngineer.snapshot()` → campo WS `engineer`, `/api/engineer/state`, dashboard, display, fatti AI | test WS == REST; Playwright dashboard == display == REST |
| Nessun calcolo nel frontend | `frontend/src/display/*` formatta soltanto; nessuna analisi o delta ricalcolato | lettura del codice |

Nota onesta: `analysis/driver.py` e `ai/facts.py` costruiscono il riferimento **della sessione registrata** (analisi a posteriori), mentre il live usa il riferimento personale persistente. Usano la stessa funzione di analisi ma possono scegliere un giro di riferimento diverso (il migliore della sessione vs il migliore storico): non è un secondo motore, ed è dichiarato nel campo `ref_lap` di ogni risultato.

## 9. Procedura per il primo test REALE con LMU (Windows)

Prima dell'uscita in pista l'unica cosa che i test sintetici NON possono dire è se LMU e il lettore concordano. Tutto è in sola lettura; nessun file di LMU viene toccato; nulla viene caricato.

1. **Installa** da `RaceEngineerAI-Setup-<ver>.exe` (artefatto CI); controlla lo SHA256 con `SHA256SUMS.txt` (`Get-FileHash`). L'installer non è firmato: SmartScreen può avvisare.
2. **LMU**: *Settings → Gameplay → Enable Plugins = ON*, chiudi e riavvia LMU del tutto. Carica una sessione (anche prove libere) ed entra in pista. (L'app non cambia mai le impostazioni di LMU.)
3. **Verifica base della Shared Memory** (60 s di guida): doppio clic su `VERIFICA_LMU.bat` e confronta velocità/giri/marcia a schermo con la tabella finale. Se il verdetto non è «REALE» **fermati e inviami il report**: il resto non ha senso.
4. **Avvia con il display**: `AVVIA_CON_DISPLAY.bat` (porta fissa 8765). Si apre la dashboard; il Driving Display va sul secondo monitor (`Ctrl+D`, `F` o il pulsante «tutto schermo»). Per un browser sul PC: `http://127.0.0.1:8765/driving-display`.
5. **Guida almeno 4 giri validi** (i primi 2 servono a imparare il circuito: il display mostra «APPRENDIMENTO»). Controlla a vista:
   * banner «DATI SINTETICI» **assente** (se c'è, i dati non vengono da LMU);
   * circuito, vettura e modalità sessione corretti in alto;
   * la mappa compare dopo il primo giro completo e somiglia al circuito (l'orientamento è quello degli assi di gioco: può essere ruotato/specchiato, **è un limite noto non verificato**);
   * zone rosse (frenata) all'inizio delle curve, verdi (accelerazione) all'uscita;
   * il delta cambia durante il giro e coincide, con qualche decimo di tolleranza, col delta del HUD di LMU se ne hai uno attivo;
   * dashboard (pagina «Live») e display mostrano **la stessa modalità, lo stesso delta e lo stesso suggerimento**.
6. **Report diagnostico completo**: `VERIFICA_DISPLAY.bat` (con l'app ancora aperta). Produce `%LOCALAPPDATA%\RaceEngineerAI\reports\live-check-<data>.md/.json` con 11 passi (processo LMU, Shared Memory, sessione, circuito, campioni, mappa, frenate, accelerazioni, analisi curve, delta, doppio schermo), ognuno `OK / MANCA / NON VERIFICABILE` con l'evidenza e la dicitura **dati REALI o SINTETICI**. Nessun nome pilota, percorso utente o chiave. Codice di uscita `0` solo con dati reali e tutti i passi automatici OK; `3` incompleto o sintetico; `2` app non raggiungibile.
   Da riga di comando: `race-engineer-cli.exe live-check --port 8765`. Dal browser: `http://127.0.0.1:8765/api/engineer/checklist?format=md`.
7. **Allega** il report `live-check` (e quello di `VERIFICA_LMU`) quando segnali un problema.

**Cosa NON prova questa procedura**: che gli offset della Shared Memory siano corretti in ogni versione di LMU (lo dice `verify-lmu`/confronto HUD), la qualità dei suggerimenti nel giudizio di un pilota, il comportamento su più giorni/endurance reali. Il verdetto automatico non sostituisce il confronto con il HUD.

## 10. Rete locale e firewall (nessuna modifica al router)

* Default: l'app ascolta **solo** su `127.0.0.1`; da altri dispositivi non è raggiungibile.
* Per un Raspberry/tablet: avvia con `--lan` (`RaceEngineerAI.exe --port 8765 --lan` oppure `race-engineer-cli.exe serve --lan --port 8765`). L'app stampa/mostra gli URL `http://IP-DEL-PC:8765/driving-display?token=…` per ogni IP privato trovato. Il token è obbligatorio per `/api` e `/ws` (senza token: 403).
* **Firewall di Windows**: alla prima apertura in LAN Windows chiede il permesso: scegli **solo «Reti private»**. In alternativa, regola esplicita da PowerShell *amministratore* (sul **PC**, non sul router; adatta il percorso):
  ```powershell
  New-NetFirewallRule -DisplayName "Race Engineer AI Display" -Direction Inbound -Protocol TCP -LocalPort 8765 -Profile Private -Action Allow -Program "$env:LOCALAPPDATA\Programs\RaceEngineerAI\RaceEngineerAI.exe"
  ```
  Per rimuoverla: `Remove-NetFirewallRule -DisplayName "Race Engineer AI Display"`. Non aprire la porta sul profilo *Pubblico*, non fare port-forwarding sul router, non esporre su Internet.
* Il PC e il dispositivo devono stare nella stessa rete (stesso Wi-Fi/switch); alcune reti «ospiti» isolano i client tra loro.
* Il dispositivo client richiede **solo un browser moderno** (Chromium/Firefox/Safari): nessuna installazione. Tasto `F` o pulsante «tutto schermo» per il fullscreen; su un Raspberry anche `chromium-browser --kiosk "<URL>"`.
* Se la connessione cade, il display mostra «CONNESSIONE PERSA» e si riconnette da solo con back-off; richiede il PC acceso e l'app in esecuzione.

## 11. Ingegnere di pista: come funziona e procedura di test reale con LMU

### 11.1 Cosa fa
- **In guida**: una sola istruzione alla volta (cosa/dove/come/perché/obiettivo), legata a una curva (numerazione provvisoria P1, P2…), con affidabilità e dati mancanti dichiarati. Durante frenata/curva l'istruzione è congelata e il Display mostra solo il titolo. Se non c'è nulla di affidabile non dice nulla.
- **Tra i giri**: «Analisi giro N» (vs miglior giro e giro precedente, curve migliorate/peggiorate, consigli applicati o no, errore ricorrente, prossimo obiettivo). Un giro con pioggia o temperatura pista molto diverse dal riferimento è dichiarato non confrontabile e non giudica i consigli.
- **Memoria** (SQLite locale, stesso catalogo): consigli e loro esito, abitudini, giri analizzati, preferenze (`GET/PUT /api/coach/prefs`: confidenza minima, verbosità, durata analisi, consigli per curva). Un consiglio ignorato due volte viene ri-valutato (priorità ridotta), non ripetuto all'infinito.
- Solo testo, nessuna voce. Nessun upload di telemetria; l'AI è opzionale e non necessaria.
- Non misurabile con i canali acquisiti (quindi mai affermato): traffico, sotto/sovrasterzo, pattinamento, differenze di setup.

### 11.2 Procedura di test REALE con LMU (Windows) — NON ancora eseguita
Regole: non modificare file di LMU; salva ogni risultato (PASS/FAIL + dato). In caso di FAIL raccogli: `python -m race_engineer live-check` (report in `reports/`), `GET /api/engineer/state?full=1`, `GET /diag`, `GET /api/coach/summary`, la cartella `logs/`, una foto/screenshot del Display e dell'HUD di LMU. I report sono anonimizzati (nessun nome pilota/percorso/chiave): non inviare altro.

| # | Azione | Atteso | Registra | PASS se | Se FAIL raccogli |
|---|---|---|---|---|---|
| 1 | `AVVIA_CON_DISPLAY.bat` | app e Display si aprono, nessun errore | versione, orario | UI raggiungibile su `/app/` e `/driving-display` | log di avvio |
| 2 | Avvia LMU, entra in pista (sessione di prove, meteo asciutto) | – | circuito, vettura, meteo, temperatura pista dall'HUD | – | – |
| 3 | Stato connessione | «LIVE», `state=acquiring` | `/diag`: mapping size, effective_hz | shared memory acquisita, ≥ 5 Hz effettivi (atteso ~50–100) | `/diag`, `verify-lmu` |
| 4 | Confronta con HUD: velocità, giri motore, marcia, gas, freno | valori coincidenti (±2 km/h) | 3 confronti a velocità diverse | tutti coincidono | foto HUD+Display |
| 5 | Sessione/circuito/vettura riconosciuti | corrispondono a LMU | valori mostrati | uguali a LMU | `/api/engineer/state` |
| 6 | Guida 8 giri puliti in condizioni costanti (stesse gomme, nessuna pioggia), con 2–3 curve in cui freni volutamente 15–20 m prima ad ogni giro | giri 1..8 riconosciuti, tempi = HUD (±0,1 s) | tempo/giro app vs HUD | ogni giro riconosciuto una volta, tempo coerente | `lap_completed` negli eventi |
| 7 | Mappa e curve | tracciato dalle posizioni reali, curve P1.. sulle curve vere | n° curve vs pista | forma/curve plausibili | screenshot mappa |
| 8 | Display in guida | una sola istruzione, solo titolo + «come», nessun testo lungo; nulla di nuovo in frenata/curva | cosa compare e quando | coerente con ciò che hai fatto | video/screenshot |
| 9 | Istruzione: il consiglio appare solo dopo l'errore ripetuto (≥ 2 giri) e riguarda la curva dove freni presto | consiglio sulla curva giusta | curva, testo, affidabilità | corrisponde; nessun consiglio su curve guidate bene | `/api/coach/tips` |
| 10 | Segui il consiglio per 2–3 giri | `miglioramento_osservato` poi `applicato` | stato nei `/api/coach/tips` | transizione corretta, mai `applicato` dopo un solo giro | `/api/coach/tips` |
| 11 | Ferma la vettura (< 30 km/h) | spiegazione completa e analisi del giro | testo | analisi del giro con tempi coerenti | `/api/coach/review` |
| 12 | `/api/engineer/checklist` e `live-check` | passi automatici OK, verdetto REAL | report | `REAL_ALL_AUTOMATIC_STEPS_OK` (non sostituisce i confronti 4–5) | report |
| 13 | **Scenario B (condizioni diverse)**: ferma, cambia meteo/pioggia o temperatura pista in modo netto (o gomme diverse), guida 3 giri | i giri sono dichiarati NON confrontabili/non verificabili, nessun giudizio sui consigli, nessun nuovo consiglio basato su quei giri | testo review | review dice «non confrontabile» e i consigli restano non giudicati | `/api/coach/review` |
| 14 | Chiudi l'app e riavviala (stesso circuito/vettura) | consigli, abitudini, giri analizzati ancora presenti | `/api/coach/summary` prima/dopo | stessi conteggi | dump prima/dopo |
| 15 | Log | nessun errore in `logs/`, nessun nome pilota/chiave | – | zero errori | log |
| 16 | Ricollegamento: scollega il cavo di rete del secondo monitor / ricarica la pagina | stato offline poi ripresa | – | torna LIVE da solo | – |

Il test NON è completato finché i passi 3–14 non sono eseguiti con LMU attivo: fino ad allora lo stato resta «non verificato con LMU reale». Limite noto: un riferimento salvato da un'altra sessione non ha condizioni registrate ⇒ i consigli appariranno con confidenza «media» e il loro esito sarà `non_verificabile` finché non c'è un nuovo giro di riferimento nella stessa sessione.
