# Prova dell'installer su Windows vero (CI), SENZA LMU: dati SINTETICI.
#   1. installazione silenziosa e smoke test della copia INSTALLATA
#   2. uscita pulita su richiesta (--quit) di una copia in esecuzione
#   3. aggiornamento (reinstallazione) con l'app APERTA: deve riuscire e l'app deve essere stata fermata
#   4. disinstallazione con l'app APERTA
# Uso: pwsh -File Test-Installer.ps1 -Setup dist\RaceEngineerAI-Setup-X.exe -Dir C:\percorso\di\prova
param([Parameter(Mandatory)][string]$Setup, [Parameter(Mandatory)][string]$Dir)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$exe = Join-Path $Dir "RaceEngineerAI.exe"
$silent = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$Dir")
$fail = New-Object System.Collections.ArrayList
function Check([string]$name, [bool]$ok, [string]$extra = "") {
    if ($ok) { Write-Host "PASS $name  $extra" } else { Write-Host "FAIL $name  $extra" -ForegroundColor Red; [void]$fail.Add($name) }
}
function Run-Wait([string]$file, [string[]]$arguments) {
    $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru
    $null = $p.Handle                       # senza questo ExitCode resta vuoto
    $p.WaitForExit()
    return $p.ExitCode
}
function Start-App {
    # copia in esecuzione come sul PC dell'utente (ridotta a icona), con dati sintetici e una cartella dati di prova
    $env:RACE_ENGINEER_DATA = Join-Path $env:TEMP ("reai_inst_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:QT_QPA_PLATFORM = "offscreen"                 # la macchina di CI non ha uno schermo vero
    $env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"
    $p = Start-Process -FilePath $exe -ArgumentList "--synthetic", "constant", "--start-minimized" -PassThru
    $null = $p.Handle
    $log = Join-Path $env:RACE_ENGINEER_DATA "logs\app.log"
    $ready = $false
    foreach ($i in 1..120) {
        if ($p.HasExited) { break }
        if ((Test-Path -LiteralPath $log) -and (Select-String -LiteralPath $log -Pattern "started: version" -Quiet)) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "l'app installata non e' partita (log: $(if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 20 | Out-String } else { 'assente' }))" }
    return $p
}
function Still-Running { return [bool](Get-Process -Name "RaceEngineerAI" -ErrorAction SilentlyContinue) }

# 1 ----------------------------------------------------------------------------------------------
Check "installazione silenziosa (codice 0)" ((Run-Wait $Setup $silent) -eq 0)
Check "exe installato presente" (Test-Path -LiteralPath $exe)
& python (Join-Path $repo "scripts\smoke_bundle.py") $Dir
Check "smoke test della copia installata" ($LASTEXITCODE -eq 0) "codice $LASTEXITCODE"
$ver = (Get-Item -LiteralPath $exe).VersionInfo
Check "l'exe dichiara prodotto e versione (Proprieta > Dettagli)" ($ver.ProductName -eq "Race Engineer AI" -and $ver.ProductVersion -match '^\d+\.\d+\.\d+') "$($ver.ProductName) $($ver.ProductVersion)"

# 2 ----------------------------------------------------------------------------------------------
$app = Start-App
$code = Run-Wait $exe @("--quit")
Check "--quit: richiesta accolta (codice 0)" ($code -eq 0) "codice $code"
Check "--quit: la copia in esecuzione e' uscita" ($app.WaitForExit(20000))
Check "--quit: uscita PULITA (codice 0, non terminata a forza)" ($app.HasExited -and $app.ExitCode -eq 0) "codice $($app.ExitCode)"
Check "--quit senza nessuna copia aperta: codice 0" ((Run-Wait $exe @("--quit")) -eq 0)

# 3 ----------------------------------------------------------------------------------------------
$app = Start-App
$code = Run-Wait $Setup $silent
Check "aggiornamento con l'app aperta: installer riuscito (codice 0)" ($code -eq 0) "codice $code"
Check "aggiornamento con l'app aperta: l'app e' stata fermata" ($app.WaitForExit(10000) -and -not (Still-Running))
& python (Join-Path $repo "scripts\smoke_bundle.py") $Dir
Check "smoke test dopo l'aggiornamento" ($LASTEXITCODE -eq 0) "codice $LASTEXITCODE"

# 4 ----------------------------------------------------------------------------------------------
$app = Start-App
$code = Run-Wait (Join-Path $Dir "unins000.exe") @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
foreach ($i in 1..60) { if (-not (Test-Path -LiteralPath $exe)) { break }; Start-Sleep -Milliseconds 500 }    # il disinstallatore lavora da una copia temporanea
Check "disinstallazione con l'app aperta: l'app e' stata fermata" ($app.WaitForExit(10000) -and -not (Still-Running))
Check "disinstallazione con l'app aperta: exe rimosso" (-not (Test-Path -LiteralPath $exe))

Write-Host ""
if ($fail.Count) { Write-Host ("FALLITI: " + ($fail -join "; ")) -ForegroundColor Red; exit 1 }
Write-Host "Tutti i controlli dell'installer superati."
exit 0
