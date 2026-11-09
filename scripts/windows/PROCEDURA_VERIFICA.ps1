# Race Engineer AI - procedura guidata di verifica REALE su Windows (PowerShell 5.1+).
# Sola lettura: non modifica LMU, non cambia impostazioni, non carica nulla online.
# Uso: apri PowerShell nella cartella di installazione (o dove hai estratto lo zip) ed esegui:
#   powershell -ExecutionPolicy Bypass -File .\PROCEDURA_VERIFICA.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cli = Join-Path $here "race-engineer-cli.exe"
if (-not (Test-Path $cli)) { $cli = Join-Path "$env:LOCALAPPDATA\Programs\RaceEngineerAI" "race-engineer-cli.exe" }
if (-not (Test-Path $cli)) { throw "race-engineer-cli.exe non trovato: esegui lo script dalla cartella del programma." }
$reports = Join-Path $env:LOCALAPPDATA "RaceEngineerAI\reports"

Write-Host "`n=== 1. Apri Le Mans Ultimate ===" -ForegroundColor Cyan
Write-Host "Avvia LMU da Steam. Lo script NON lo avvia e NON cambia le sue impostazioni."
Read-Host "Premi Invio quando LMU e' aperto"

Write-Host "`n=== 2. Abilita i plugin (manuale) ===" -ForegroundColor Cyan
Write-Host "In LMU: Settings > Gameplay > Enable Plugins = ON, poi CHIUDI e RIAVVIA completamente LMU."
Read-Host "Premi Invio quando LMU e' stato riavviato con Enable Plugins attivo"

Write-Host "`n=== 3. Avvia una sessione ===" -ForegroundColor Cyan
Write-Host "Carica una sessione (es. Prove libere), esci dai box ed entra in pista. Guida con continuita' durante il test."
Read-Host "Premi Invio quando sei in pista e stai guidando"

Write-Host "`n=== 4. Diagnostica base ===" -ForegroundColor Cyan
& $cli diagnose

Write-Host "`n=== 5. Verifica Shared Memory + registrazione 60 s ===" -ForegroundColor Cyan
Write-Host "Confronta velocita', RPM, marcia e giro stampati ogni secondo con il HUD di LMU."
& $cli verify-lmu --seconds 60
$md = Get-ChildItem $reports -Filter "lmu_verification_*.md" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
if ($md) { Write-Host "REPORT: $($md.FullName)" -ForegroundColor Green; Start-Process notepad $md.FullName }

Write-Host "`n=== 6. Report telemetria DuckDB nativa ===" -ForegroundColor Cyan
Write-Host "(LMU scrive il file .duckdb alla fine del giro/sessione: se non c'e' ancora, esci ai box e rilancia solo questo punto.)"
& $cli duckdb-report
$f = Read-Host "Incolla il percorso completo di un file .duckdb dall'elenco (Invio per saltare)"
if ($f) { & $cli duckdb-report "$f"; Write-Host "Report in: $reports (duckdb_report_*.md)" -ForegroundColor Green }

Write-Host "`n=== 7. Analisi setup ===" -ForegroundColor Cyan
& $cli setup-inspect
$s = Read-Host "Incolla il percorso completo di un file .svm (Invio per saltare)"
if ($s) { & $cli setup-inspect "$s"; Write-Host "Report in: $reports (setup_report_*.md); copia fedele in $env:LOCALAPPDATA\RaceEngineerAI\setups_raw" -ForegroundColor Green }

Write-Host "`nFatto. Tutti i risultati sono in: $reports" -ForegroundColor Green
Write-Host "I report non contengono chiavi ne' nome utente. Nulla e' stato caricato online."
Invoke-Item $reports
