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
* Secondo monitor (posizionamento a tutto schermo su Windows con più schermi), tray, Raspberry reale, Wi-Fi reale e firewall **non sono stati provati** su hardware: coperti solo dalla CI Windows (senza monitor secondario) e da Chromium headless su Linux.
* L'interpretazione AI (`driving_analysis`) è provata solo con provider finti; nessuna richiesta reale NVIDIA/Groq.
* Installer/exe non firmati (SmartScreen può avvisare).
