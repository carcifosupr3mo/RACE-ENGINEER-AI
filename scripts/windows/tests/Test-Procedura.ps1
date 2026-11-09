# Test automatici di PROCEDURA_VERIFICA.ps1 SENZA LMU: file/dati SINTETICI, nessuna rete, nessuna chiave.
# Richiede python con il pacchetto race_engineer installato (pip install -e backend). Uso: powershell -File Test-Procedura.ps1
# Esito: codice 0 se tutti i controlli passano.
param([string]$CliPath)   # se indicato, la procedura usa questo exe (es. quello congelato); altrimenti "python -m race_engineer"
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$proc = Join-Path (Split-Path -Parent $here) "PROCEDURA_VERIFICA.ps1"
$hostExe = (Get-Process -Id $PID).Path
$script:ModeArgs = @("-PythonModule")
if ($CliPath) { $script:ModeArgs = @("-CliPath", (Resolve-Path -LiteralPath $CliPath).Path) }
$fail = New-Object System.Collections.ArrayList
function Check([string]$name, [bool]$ok, [string]$extra = "") {
    if ($ok) { Write-Host ("PASS " + $name + $(if ($extra) { "  " + $extra } else { "" })) } else { Write-Host ("FAIL " + $name + "  " + $extra) -ForegroundColor Red; [void]$fail.Add($name) }
}
function Run-Proc([string[]]$ProcArgs) {
    $mode = $script:ModeArgs
    $out = & $hostExe -NoProfile -ExecutionPolicy Bypass -File $proc @mode @ProcArgs 2>&1
    $script:Code = $LASTEXITCODE
    $script:Out = ($out | ForEach-Object { "$_" }) -join "`n"
}
function Tree-Fingerprint([string]$dir) {
    @(Get-ChildItem -LiteralPath $dir -Recurse -File | Sort-Object FullName | ForEach-Object { "{0}|{1}|{2}|{3}" -f $_.FullName, $_.Length, $_.LastWriteTimeUtc.Ticks, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join "`n"
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("reai_ps_test_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Write-Host ("PowerShell " + $PSVersionTable.PSVersion + " - cartella di test " + $tmp)
$env:NVIDIA_API_KEY = $null; $env:GROQ_API_KEY = $null          # la verifica LMU non deve richiedere chiavi AI

# --- 0. nessuna dipendenza da chiavi AI nello script
$src = Get-Content -LiteralPath $proc -Raw
Check "lo script non usa chiavi AI ne' comandi di rete" (($src -notmatch "ai-test") -and ($src -notmatch "Invoke-WebRequest|Invoke-RestMethod|curl|NVIDIA_API_KEY|GROQ_API_KEY"))
Check "lo script e' solo ASCII (compatibile con PowerShell 5.1)" (($src.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -eq 0)

# --- fixture sintetiche
& python (Join-Path $here "make_fixtures.py") $tmp | Out-Host
$game = Join-Path $tmp "Le Mans Ultimate"
$shm = Join-Path $tmp "fake_lmu_data.bin"
$data = Join-Path $tmp "data"
$env:LMU_GAME_DIR = $game
$fpBefore = Tree-Fingerprint $game

# --- 1. esecuzione completa su dati sintetici (file override): non e' LMU reale -> codice 3, ma report completi
Run-Proc @("-NonInteractive", "-Seconds", "3", "-ShmPath", $shm, "-DataDir", $data, "-SkipHud")
Check "dati da file/bridge => la verifica NON risulta reale (codice 3)" ($script:Code -eq 3) ("codice " + $script:Code)
$rep = Join-Path $data "reports"
$names = @(Get-ChildItem -LiteralPath $rep -File | ForEach-Object { $_.Name })
foreach ($pat in @("preflight_*.json", "lmu_verification_*.json", "lmu_verification_*.md", "duckdb_report_*.json", "duckdb_report_*.md", "setup_report_*.json", "originals_integrity_*.json", "verification_summary_*.json", "verification_summary_*.md")) {
    $f = Get-ChildItem -LiteralPath $rep -Filter $pat -File | Select-Object -First 1
    Check ("report creato e non vuoto: " + $pat) ($f -and $f.Length -gt 0)
}
$sumFile = Get-ChildItem -LiteralPath $rep -Filter "verification_summary_*.json" -File | Select-Object -First 1
$sum = Get-Content -LiteralPath $sumFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
Check "il riepilogo NON dichiara la Fase 1 completata" (($sum.phase1.declared_complete -eq $false) -and ($sum.phase1.status -match "NOT COMPLETE"))
Check "il riepilogo marca i dati come NON reali" ($sum.data_origin -match "NOT REAL")
Check "DuckDB e setup trovati automaticamente (nessun percorso richiesto)" (($sum.duckdb.run -eq $true) -and ($sum.setup.run -eq $true))
Check "HUD non eseguito e dichiarato tale" ($sum.hud.run -eq $false)
$integ = Get-ChildItem -LiteralPath $rep -Filter "originals_integrity_*.json" -File | Select-Object -First 1 | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
Check "integrita' originali: invariati" ($integ.all_unchanged -eq $true)
Check "la cartella LMU simulata e' identica prima e dopo (hash, dimensioni, date, nessun file creato)" ((Tree-Fingerprint $game) -eq $fpBefore)
$leak = @(Get-ChildItem -LiteralPath $rep -File | Where-Object { $_.Name -notlike "hud_annotations_*" } | Select-String -Pattern ([regex]::Escape($env:USERNAME)) | ForEach-Object { $_.Filename + ": " + $_.Line.Trim() })
Check "nessun nome utente nei report (md e json)" ($leak.Count -eq 0) (($leak | Select-Object -First 3) -join " || ")

# --- 2. seconda esecuzione: nulla viene sovrascritto
$hashes1 = @{}; Get-ChildItem -LiteralPath $rep -File | ForEach-Object { $hashes1[$_.Name] = (Get-FileHash -LiteralPath $_.FullName).Hash }
Start-Sleep -Seconds 2
Run-Proc @("-NonInteractive", "-Seconds", "3", "-ShmPath", $shm, "-DataDir", $data, "-SkipHud")
$same = $true; foreach ($k in $hashes1.Keys) { if (-not (Test-Path (Join-Path $rep $k)) -or (Get-FileHash -LiteralPath (Join-Path $rep $k)).Hash -ne $hashes1[$k]) { $same = $false } }
Check "seconda esecuzione: i report precedenti sono intatti" $same
Check "seconda esecuzione: nuovi report aggiunti" ((@(Get-ChildItem -LiteralPath $rep -Filter "verification_summary_*.json").Count) -eq 2)

# --- 3. HUD da file (annotazioni fuori registrazione => errore segnalato, non crash)
$ann = Join-Path $tmp "ann.json"
Set-Content -LiteralPath $ann -Value '[{"epoch": 1.0, "speed_kmh": 100}]' -Encoding UTF8
Run-Proc @("-NonInteractive", "-Seconds", "3", "-ShmPath", $shm, "-DataDir", $data, "-HudFile", $ann)
$hudJson = Get-ChildItem -LiteralPath $rep -Filter "hud_comparison_*.json" -File | Select-Object -First 1
Check "HUD: annotazioni fuori finestra => confronto NON superato e report creato" ($hudJson -and ((Get-Content -LiteralPath $hudJson.FullName -Raw) -match "NOT PASSED"))

# --- 4. errori e dati mancanti: nessun LMU, nessun mapping, nessun file => segnalato, report prodotti, codice 3
$empty = Join-Path $tmp "no_lmu"; New-Item -ItemType Directory -Force -Path $empty | Out-Null
$env:LMU_GAME_DIR = Join-Path $tmp "does_not_exist"
$data2 = Join-Path $tmp "data2"
Run-Proc @("-NonInteractive", "-Seconds", "3", "-ShmPath", (Join-Path $tmp "missing.bin"), "-DataDir", $data2, "-SkipHud")
Check "senza LMU/mapping: codice 3 (non verificato), non un crash" ($script:Code -eq 3) ("codice " + $script:Code)
$s2 = Get-ChildItem -LiteralPath (Join-Path $data2 "reports") -Filter "verification_summary_*.json" -File | Select-Object -First 1
$sum2 = Get-Content -LiteralPath $s2.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
Check "senza LMU: riepilogo con 'NOT COMPLETE' e elenco di cio' che manca" (($sum2.phase1.status -match "NOT COMPLETE") -and (@($sum2.preflight_missing).Count -ge 2))
Check "senza LMU: nessuna registrazione dichiarata" ($sum2.data_origin -eq "NO RECORDING")

# --- 5. percorso indicato inesistente => segnalato come errore (codice 2), nessuna modifica
$env:LMU_GAME_DIR = $game
Run-Proc @("-NonInteractive", "-Seconds", "3", "-ShmPath", $shm, "-DataDir", (Join-Path $tmp "data3"), "-SkipHud", "-DuckdbFile", (Join-Path $tmp "nope.duckdb"))
Check "percorso DuckDB inesistente: errore segnalato (codice 2)" (($script:Code -eq 2) -and ($script:Out -match "non esiste"))
Check "la cartella LMU simulata e' ancora identica" ((Tree-Fingerprint $game) -eq $fpBefore)

Write-Host ""
if ($fail.Count -eq 0) { Write-Host "TUTTI I CONTROLLI PASSATI" -ForegroundColor Green; exit 0 }
Write-Host ("FALLITI: " + ($fail -join "; ")) -ForegroundColor Red
Write-Host "--- ultimo output della procedura ---"; Write-Host $script:Out
exit 1
