# ANALYSIS-METHODS  (Fasi 2-3: implementato, validato SOLO su dati sintetici)

Codice: `backend/race_engineer/analysis/{laps,align,corners,compare}.py`.

## Giri (`laps.py`)
Segmentazione per cambio di `lap_number`. Stato: **complete** (parte alla linea, copertura distanza ≥ 98 %, nessun buco di distanza > 50 m,
nessun buco temporale > 5× mediana, giro chiuso dal gioco), **incomplete** (una delle condizioni sopra manca; motivi elencati),
**invalid** (`lap_invalidated` dal gioco). `valid_for_analysis` = complete e senza pit. Il tempo giro è quello del gioco
(`last_lap_time`, provenienza *direct*) se disponibile, altrimenti calcolato dal tempo sessione (*computed*): l'origine è sempre riportata.
Medie e deviazione standard usano solo giri validi (dichiarato nella risposta). I dati non vengono mai cancellati.

## Allineamento (`align.py`)
Ogni giro è riportato su una griglia di distanza (1 m) con `np.interp` sulla distanza giro; i campioni con distanza decrescente sono
scartati (conteggio in `quality.dropped_backwards`); marcia a gradino (nessuna interpolazione tra marce). Qualità: `coverage`, `max_gap_m`,
`ok` (copertura ≥ 97 % e buco ≤ 50 m). L'API rifiuta il confronto (422) se la qualità è insufficiente. Delta = t_giro(s) − t_rif(s).

## Curve (`corners.py`)
Minimi locali di velocità del giro di riferimento (`scipy.signal.find_peaks`, prominenza ≥ 15 km/h, distanza ≥ 120 m). Ingresso = inizio del
blocco di frenata che precede l'apice (o massimo locale se non si frena); uscita = velocità recuperata a metà tra apice e massimo nei 400 m
successivi. **Numerazione provvisoria `P1…`**: nessun numero reale viene inventato. Un profilo salvato (`PUT /api/tracks/profile`, tabella
`track_profiles`) sostituisce la rilevazione e rimuove il flag *provvisorio*. L'editor grafico è **non implementato** (solo API).

## Confronto e osservazioni (`compare.py`)
Metriche per curva: inizio/rilascio frenata, picco freno, velocità minima, ripresa gas (≥ 90 %), velocità d'uscita, tempo senza pedali,
variazione del delta nella zona. Osservazioni con soglie esplicite (frenata ±15 m, minima ≥ 2 km/h, uscita ≥ 3 km/h, gas ≥ 15 m, picco freno
+0,15, rilascio −15 m): early/late braking, early brake release, brake peak higher, low min speed, late throttle, slow exit. Ogni osservazione
contiene i valori misurati e la variazione di tempo di zona; la nota esplicita che l'attribuzione è per posizione e non prova la causa.
Costanza: deviazione standard tra giri validi (≥ 3) di velocità minima, punto di frenata, ripresa gas.
Non implementate: sterzata eccessiva (richiede dati non verificati), accelerazione non progressiva, transizioni freno-gas, analisi per GPS.

## Validazione
Scenari sintetici con differenze note: +40 m di frenata → rilevati −41 m (P2) e +1,8 s; +35 m di gas → +34 m (P3); ritmo −3 % → solo le curve oltre
soglia; giri costanti → nessuna osservazione; dati mancanti/telemetria assente → metriche `None`, mai inventate.
**Non validato su telemetria LMU reale** (soglie e rilevazione curve potrebbero richiedere taratura).
