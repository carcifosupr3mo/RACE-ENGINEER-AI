# Test reale Le Mans Ultimate — procedura ripetibile sul tuo PC

## Stato onesto (aggiornato 2026-11-14)
**La lettura dei dati di Le Mans Ultimate NON è mai stata verificata con il gioco reale.** In questo ambiente (Linux/CI) LMU non esiste: tutto ciò che è stato provato usa dati **simulati** (lettore + layout provati su una memoria finta con la stessa struttura). Il layout `LMU_Data` è stato trascritto da fonti pubbliche. Fino a che non fai il test qui sotto, ogni voce della tabella resta **NON VERIFICATA**.

| Cosa controllare | Come lo controlla l'app | Stato |
|---|---|---|
| Connessione (mapping `LMU_Data`) | `diagnose`, `preflight`, `verify-lmu` | non verificato con LMU reale |
| Rilevamento sessione | stato motore `acquiring` + `session_id` creato | non verificato |
| Velocità, marcia, giri motore, acceleratore, freno | confronto con l'HUD (±1,5 s, tolleranze) | non verificato |
| Sterzo | controllo di intervallo −1…1 in `verify-lmu`; **nessun confronto con l'HUD** (l'HUD non lo mostra) | solo plausibilità |
| Tempi sul giro | numero giro confrontato con l'HUD; **i tempi giro non sono confrontati automaticamente** → leggili a mano (passo 6) | non verificato |
| Dati continui in guida | frequenza effettiva, campioni persi, tempo mai all'indietro | non verificato |

## Passi esatti
1. Installa l'app (installer dagli artefatti CI o dalla release) e controlla l'hash: `Get-FileHash .\RaceEngineerAI-Setup-*.exe -Algorithm SHA256` deve coincidere con `SHA256SUMS.txt`.
2. Avvia LMU da Steam → *Impostazioni → Gameplay → Enable Plugins = ON* → chiudi e **riavvia** LMU.
3. Entra in pista (anche prova libera, auto in movimento). Tieni visibile l'HUD con velocità, marcia, RPM.
4. Apri PowerShell:
   ```powershell
   cd "$env:LOCALAPPDATA\Programs\RaceEngineerAI"
   powershell -ExecutionPolicy Bypass -File .\PROCEDURA_VERIFICA.ps1
   ```
5. Durante i 60 s di registrazione guida (rettilineo, frenata, curva, cambio marcia) e premi **INVIO** 4–6 volte guardando l'HUD; a fine registrazione inserisci i valori letti (velocità, RPM, marcia, giro, acceleratore %, freno %).
6. **Tempi sul giro e sterzo (a mano):** completa almeno 2 giri; annota l'ultimo tempo mostrato dal gioco. Poi nell'app → *Le tue sessioni* → apri la sessione e confronta tempo giro e numero giri. Volta lo sterzo tutto a sinistra/destra da fermo e controlla in *Dati in diretta* che il valore cambi segno.
7. Apri `%LOCALAPPDATA%\RaceEngineerAI\reports\verification_summary_<data>.md`.

## Come leggere il risultato (reale vs simulato)
- Il riepilogo scrive **Origine dati: REAL** solo se ogni campione arriva dalla memoria condivisa del sistema. Con file/bridge o dati sintetici scrive **NOT REAL** e la verifica non può risultare reale.
- Codice di uscita `0` = verifica automatica reale superata; `3` = LMU non raggiungibile o verifica non superata (report comunque creati); `2` = errore della procedura.
- Nell'app, i dati sintetici sono sempre etichettati; se vedi «sintetico» **non** hai fatto il test reale.
- Se un campo risulta costante o mancante, il riepilogo lo elenca come «non verificato»: non va considerato funzionante.

## Cosa mandarmi per chiudere la verifica
Il file `verification_summary_<data>.md` (nessuna chiave, nessun nome utente) più i tuoi appunti del passo 6. Solo dopo un riepilogo REAL con accordo HUD ≥ 80% potrò aggiornare lo stato in `docs/VALIDATION.md`; la decisione finale di accettazione resta tua.

Sola lettura: l'app non scrive nella memoria di LMU, non inietta nulla, non modifica impostazioni del gioco.
