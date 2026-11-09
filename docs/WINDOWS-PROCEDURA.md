# Procedura Windows: verifica reale (copia e incolla)

Tutto è **sola lettura** e **locale**: nessun file o telemetria viene caricato online; i report non contengono chiavi né nome utente.
Cartella programma (installer): `%LOCALAPPDATA%\Programs\RaceEngineerAI`. Dati e **risultati**: `%LOCALAPPDATA%\RaceEngineerAI` (report in `reports\`, registrazione di prova in `verify_runs\`, copie fedeli dei setup in `setups_raw\`, log in `logs\app.log`).

## 0. Installazione e integrità
```powershell
# dopo aver scaricato dagli artefatti CI: RaceEngineerAI-Setup-<ver>.exe e SHA256SUMS.txt
Get-FileHash .\RaceEngineerAI-Setup-*.exe -Algorithm SHA256   # deve coincidere con la riga in SHA256SUMS.txt
.\RaceEngineerAI-Setup-*.exe
```

## 1. Procedura guidata (consigliata): `PROCEDURA_VERIFICA.ps1`
```powershell
cd "$env:LOCALAPPDATA\Programs\RaceEngineerAI"
powershell -ExecutionPolicy Bypass -File .\PROCEDURA_VERIFICA.ps1        # oppure doppio clic su PROCEDURA_VERIFICA.bat
```
Non serve nessuna chiave AI. Cosa fa, in ordine (e cosa ti chiede):

| Passo | Automatico | Ti chiede solo se manca |
|---|---|---|
| Programma | trova `race-engineer-cli.exe` (cartella dello script, `%LOCALAPPDATA%\Programs\RaceEngineerAI`, PATH) e verifica che parta | `-CliPath` se non lo trova |
| Permessi | prova a scrivere in `%LOCALAPPDATA%\RaceEngineerAI\reports` | niente (si ferma con errore chiaro) |
| LMU | installazione (Steam), processo in esecuzione, mapping `LMU_Data` (dimensione, `gameVersion`), numero di file DuckDB e setup trovati | i passi manuali sotto, solo se il mapping manca |
| Registrazione | `diagnose` + `verify-lmu` per almeno 60 s (`-Seconds`), con marcature HUD (INVIO) | niente |
| DuckDB / setup | prende da solo il `.duckdb` e il `.svm` piu' recenti | il percorso, **solo** se non ne trova (`-DuckdbFile`, `-SetupFile`) |
| Integrita' | hash SHA256, dimensione e data dei file originali prima/dopo + numero di file nelle cartelle `UserData\Telemetry` e `UserData\player\Settings` | niente |
| Confronto HUD | confronta le tue annotazioni con la registrazione (sezione 3) | i valori letti, per ogni marcatura |
| Riepilogo | `verification_summary_*.md/.json` | niente |
| Controllo finale | ogni report esiste, non e' vuoto, il JSON e' valido, nessun report precedente e' stato sovrascritto | niente |

**Passi manuali in LMU** (la procedura non li esegue e non cambia impostazioni di LMU): avvia LMU da Steam; *Settings > Gameplay > Enable Plugins = ON*; chiudi e **riavvia completamente** LMU; carica una sessione ed entra in pista. Se il mapping manca, la procedura te lo ricorda e ricontrolla fino a 3 volte, poi prosegue documentando il problema.

**Codici di uscita**: `0` verifica automatica REALE superata e report validi; `3` LMU non raggiungibile o verifica non superata (report comunque prodotti); `2` errore della procedura (programma non trovato, cartella non scrivibile, report mancanti/invalidi, file originale cambiato).

**Dove sono i risultati**: `%LOCALAPPDATA%\RaceEngineerAI\reports`
- `verification_summary_<data>.md` (**leggi questo per primo**) e `.json`
- `lmu_verification_<data>.md/.json` (shared memory, offset, frequenza, campioni, qualita'), `preflight_<data>.json`
- `duckdb_report_<data>.md/.json`, `setup_report_<data>.md/.json`, `hud_comparison_<data>.md/.json`, `originals_integrity_<data>.json`, `hud_annotations_<data>.json`
- registrazione di prova: `%LOCALAPPDATA%\RaceEngineerAI\verify_runs\<data>`; copie fedeli dei setup: `setups_raw\`; log della console: `reports\verify_console_<data>.log`

Il riepilogo contiene: versione app e commit (dal file `build_info.json` della build; "sconosciuto" per build precedenti), versione LMU (Steam build id e `gameVersion` letta dal mapping), mapping trovato e dimensione, offset verificati (struct del nostro layout = struct calcolate dagli header installati di LMU; se gli header non si trovano lo stato e' *sconosciuto*, non "ok"), frequenza effettiva, campioni ricevuti/persi, campi disponibili / costanti (non verificati) / mancanti, errori, stato DuckDB, stato setup, qualita' dati, esito HUD. **Origine dati**: "REAL" solo se ogni campione proviene dalla memoria condivisa del sistema; con `-ShmPath` (file/bridge) o dati sintetici il riepilogo scrive "NOT REAL" e la verifica non puo' risultare reale. Il riepilogo non dichiara **mai** la Fase 1 completata: al massimo scrive "ACCEPTANCE CRITERIA MET - final acceptance is the user's decision".

## 2. Comandi singoli (equivalenti alla procedura)
```powershell
cd "$env:LOCALAPPDATA\Programs\RaceEngineerAI"
.\race-engineer-cli.exe preflight                                  # JSON: app/commit, LMU, processo, mapping, DuckDB e setup trovati
.\race-engineer-cli.exe diagnose                                   # installazione, processo, mapping LMU_Data (JSON; codice 2 = mapping assente)
.\race-engineer-cli.exe verify-lmu --seconds 60                    # [--out <cartella>] [--shm-path <file>, solo test]; codice 3 = non verificato
.\race-engineer-cli.exe duckdb-report                              # senza argomenti elenca i .duckdb nativi trovati
.\race-engineer-cli.exe duckdb-report "C:\...\UserData\Telemetry\<file>.duckdb"
.\race-engineer-cli.exe setup-inspect                              # senza argomenti elenca i .svm trovati
.\race-engineer-cli.exe setup-inspect "C:\...\<setup>.svm"
.\race-engineer-cli.exe hud-compare --annotations <annotazioni.json> --verify-report <lmu_verification_*.json>
.\race-engineer-cli.exe verification-summary --verify <...json> [--preflight --duckdb --setup --hud --originals]
```
Se `mapping` fallisce: Enable Plugins non attivo o LMU non riavviato; il programma non installa plugin e non modifica LMU.

## 3. Confronto con l'HUD (come annotare)
L'HUD e il campionamento non sono mai simultanei (latenza di visualizzazione, tempo per leggere e scrivere): per questo il confronto usa una **finestra di +-1,5 s** attorno a ogni annotazione e **tolleranze** (velocita' max(3 km/h, 3%), RPM max(150, 3%), acceleratore/freno +-10 punti %; marcia e giro devono comparire tra i valori registrati nella finestra). Nessuna precisione al millisecondo e' richiesta.

Modo consigliato: durante la registrazione di 60 s **premi INVIO** quando guardi l'HUD (marcatura con orario esatto; 4-6 volte, in punti diversi: rettilineo, frenata, curva, cambio marcia). Scatta anche uno screenshot (Win+Alt+PrtScn con Xbox Game Bar) o annota a mano: finita la registrazione la procedura chiede, per ogni marcatura, velocita' (km/h), RPM, marcia (0=N, -1=R), giro, acceleratore % e freno % (Invio = non letto). Servono almeno 3 annotazioni, almeno una in movimento (> 30 km/h), e almeno l'80% di accordo per ogni campo letto. Una differenza costante di +-1 sul giro/marcia viene segnalata come *probabile convenzione di numerazione*, non nascosta ne' corretta.

Alternativa con file (orari presi da un video/orologio): `-HudFile mie_annotazioni.json`; formato in `hud_annotazioni_ESEMPIO.json` (`utc` oppure `epoch` + campi `speed_kmh, rpm, gear, lap, throttle_pct, brake_pct`, tutti facoltativi). Il file non viene modificato.

Un confronto superato e' una prova sulla **mappatura dei canali**; non sostituisce la decisione finale di accettazione, che spetta a te.

## 4. Chiavi AI (gratuite) e prova reale (separata: NON serve alla verifica LMU)
```powershell
# Opzione A - variabili d'ambiente (utente corrente; riapri PowerShell dopo)
[Environment]::SetEnvironmentVariable("NVIDIA_API_KEY", (Read-Host "NVIDIA key"), "User")
[Environment]::SetEnvironmentVariable("GROQ_API_KEY",   (Read-Host "Groq key"),   "User")
# Opzione B - Gestione credenziali di Windows: app > Settings > AI gratuita > incolla e Salva
.\race-engineer-cli.exe ai-test          # 1 richiesta minima (~20 token) per route; le chiavi non vengono stampate
```
Chiavi gratuite: build.nvidia.com (modello `nvidia/nemotron-3.5-lightning-30b-a3b`: verifica nella pagina del modello che sia un endpoint gratuito per il tuo account) e console.groq.com (piano free). Il programma chiama solo i modelli nella lista consentita e rispetta limiti locali; non usa endpoint a pagamento.
