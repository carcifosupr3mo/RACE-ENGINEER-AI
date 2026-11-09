# Procedura Windows: verifica reale (copia e incolla)

Tutto è **sola lettura** e **locale**: nessun file o telemetria viene caricato online; i report non contengono chiavi né nome utente.
Cartella programma (installer): `%LOCALAPPDATA%\Programs\RaceEngineerAI`. Dati e **risultati**: `%LOCALAPPDATA%\RaceEngineerAI` (report in `reports\`, registrazione di prova in `verify_runs\`, copie fedeli dei setup in `setups_raw\`, log in `logs\app.log`).

## 0. Installazione e integrità
```powershell
# dopo aver scaricato dagli artefatti CI: RaceEngineerAI-Setup-<ver>.exe e SHA256SUMS.txt
Get-FileHash .\RaceEngineerAI-Setup-*.exe -Algorithm SHA256   # deve coincidere con la riga in SHA256SUMS.txt
.\RaceEngineerAI-Setup-*.exe
```

## 1. Procedura guidata (consigliata)
```powershell
cd "$env:LOCALAPPDATA\Programs\RaceEngineerAI"
powershell -ExecutionPolicy Bypass -File .\PROCEDURA_VERIFICA.ps1
```
Ti guida in: aprire LMU → **Settings › Gameplay › Enable Plugins = ON e riavvio completo di LMU (manuale, il programma non cambia impostazioni)** → caricare una sessione e guidare → diagnostica → registrazione 60 s → report DuckDB → analisi setup.

## 2. Comandi singoli
```powershell
cd "$env:LOCALAPPDATA\Programs\RaceEngineerAI"
.\race-engineer-cli.exe diagnose                      # installazione, processo, mapping LMU_Data (JSON)
.\race-engineer-cli.exe verify-lmu --seconds 60       # guida in pista; confronta con il HUD
notepad (Get-ChildItem "$env:LOCALAPPDATA\RaceEngineerAI\reports\lmu_verification_*.md" | Sort LastWriteTime | Select -Last 1).FullName
.\race-engineer-cli.exe duckdb-report                 # elenca i .duckdb nativi trovati
.\race-engineer-cli.exe duckdb-report "C:\...\UserData\Telemetry\<file>.duckdb"
.\race-engineer-cli.exe setup-inspect                 # elenca i .svm trovati
.\race-engineer-cli.exe setup-inspect "C:\...\<setup>.svm"
.\race-engineer-cli.exe ai-test                       # prova reale gratuita dei provider (richiede chiavi)
```
Cosa leggere nel report `lmu_verification_*.md`: verdetto in cima; `mapping.size` (atteso ≥ 324820), `gameVersion`, riga `header_offsets` (offset del nostro layout = offset calcolati dagli header LMU installati), `effective_hz`, campioni persi, canali costanti/nulli, e la tabella **HUD** da compilare a mano. Il verdetto "REAL LMU VERIFIED" significa solo che i controlli automatici sono passati: il confronto col HUD resta manuale. In `duckdb_report_*.md` leggere `g_force_analysis.verdict`.
Se `mapping` fallisce: Enable Plugins non attivo o LMU non riavviato; il programma non installa plugin e non modifica LMU.

## 3. Chiavi AI (gratuite) e prova reale
```powershell
# Opzione A - variabili d'ambiente (utente corrente; riapri PowerShell dopo)
[Environment]::SetEnvironmentVariable("NVIDIA_API_KEY", (Read-Host "NVIDIA key"), "User")
[Environment]::SetEnvironmentVariable("GROQ_API_KEY",   (Read-Host "Groq key"),   "User")
# Opzione B - Gestione credenziali di Windows: app > Settings > AI gratuita > incolla e Salva
.\race-engineer-cli.exe ai-test          # 1 richiesta minima (~20 token) per route; le chiavi non vengono stampate
```
Chiavi gratuite: build.nvidia.com (modello `nvidia/nemotron-3.5-lightning-30b-a3b`: verifica nella pagina del modello che sia un endpoint gratuito per il tuo account) e console.groq.com (piano free). Il programma chiama solo i modelli nella lista consentita e rispetta limiti locali; non usa endpoint a pagamento.
