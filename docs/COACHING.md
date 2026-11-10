# Ingegnere di pista: come nasce un consiglio (e quando NON ne nasce)

Stato: **implementato e testato SOLO con dati sintetici; mai verificato con LMU reale.** Le soglie sono euristiche non tarate su telemetria reale.

## 1. Canali usati (nessun canale non acquisito viene assunto)
Posizione lungo il giro (distanza, m), tempo, velocità (km/h), gas e freno (0..1), sterzo, marcia, giri motore; per la comparabilità: pioggia, temperatura pista, usura gomme, carburante. Se un canale manca, la regola che lo richiede **non scatta** (valore `None`), non viene stimato.

## 2. Rilievi (per curva: avvicinamento → frenata → rilascio → inserimento → percorrenza → apice → uscita → gas)
Ogni rilievo è giudicato sulla **curva intera**: serve una perdita di tempo di fase misurata (`seg_loss_s` 0,03 s ecc.) oltre alla differenza di comportamento. Frenare più tardi o avere velocità minima maggiore **non** è automaticamente migliore (`late_braking_gain` è un guadagno, non un errore).

| Rilievo | Canali | Condizione minima (euristica, non calibrata su LMU) |
|---|---|---|
| frenata anticipata / tardiva inefficiente / troppo lunga | freno, distanza, velocità | differenza ≥ 15 m (rilascio ≥ 8 m) **e** perdita di fase |
| rilascio brusco | freno | caduta 80 %→soglia in < 6 m e < 50 % del riferimento |
| trail braking insufficiente / eccessivo | freno, sterzo | riferimento ≥ 12 m, giro ≤ 40 % (o +15 m e ≥ 1,8×) **e** perdita di tempo in ingresso/centro |
| velocità minima, traiettoria (sterzo medio) | velocità, sterzo | ≥ 2 km/h, sterzo ≥ 1,10× **e** minima più bassa/perdita |
| accelerazione ritardata / gas aggressivo | gas, distanza | ≥ 15 m di ritardo; rampa 10→90 % ≤ 50 % del riferimento (≥ 12 m) **e** uscita più lenta |
| marcia | marcia | marcia all'apice diversa **e** curva più lenta (non provato che la marcia del riferimento sia ottimale) |

**Mai affermati** (non misurabili con i canali acquisiti): sotto/sovrasterzo, pattinamento, traffico, differenze di setup. Compaiono solo sotto «dati mancanti».

## 3. Filtri anti-falso-positivo (audit 0.6.1)
1. **Ripetizione**: un rilievo diventa consiglio solo se presente in ≥ 2 degli ultimi 3 giri analizzati (`MIN_REPEAT`, `REPEAT_WINDOW`). Un singolo giro cattivo è indistinguibile dalla normale variazione tra giri. Conseguenza: il primo consiglio arriva non prima del 3° giro analizzato.
2. **Confidenza** = affidabilità riferimento × (effetto/soglia, tempo perso). Bassa ⇒ nessun valore in metri nel testo.
3. **Confrontabilità** (`live/coach.py::comparable`): giro **non confrontabile** se la pioggia differisce ≥ 0,15 o la temperatura pista ≥ 10 °C (soglie euristiche, **non** calibrate; avvisi per carburante ≥ 20 L, usura ≥ 0,15, temperatura ≥ 5 °C). Se pioggia o temperatura pista non sono note su uno dei due giri (tipico: riferimento salvato da un'altra sessione) il confronto è **non verificabile**: i consigli possono comparire ma con confidenza limitata a «media», e il loro esito **non viene giudicato** (`non_verificabile`, dopo 3 giri il consiglio è chiuso come non verificabile). Setup e sessione non sono confrontabili automaticamente (non letti): dichiarato in «dati mancanti».
4. **Consigli opposti** sulla stessa curva non entro 2 giri (salvo confidenza alta); consigli ignorati due volte ⇒ `da_rivalutare` con priorità × 0,4.

## 4. Esito di un consiglio (il giro migliore NON basta)
Il sistema misura solo se il comportamento rilevato è cambiato; **non può sapere se il pilota ha "seguito" il consiglio**. Esiti: `non_seguito`, `parziale`, `seguito_non_efficace`, `peggiorato`, `miglioramento_osservato` (un giro senza il problema: potrebbe essere fortuna), `seguito_migliorato` (stato `applicato`, solo dopo **2 giri consecutivi** senza il problema), `non_confrontabile`, `non_verificabile`, `non_mostrato`. L'abitudine passa a «corretto» solo con `applicato`.

## 5. Display
In guida: una sola istruzione, titolo + «come» (max 3 righe); «perché/obiettivo/abitudine» e l'analisi completa solo a vettura quasi ferma (< 30 km/h); durante frenata/curva l'istruzione è congelata.
