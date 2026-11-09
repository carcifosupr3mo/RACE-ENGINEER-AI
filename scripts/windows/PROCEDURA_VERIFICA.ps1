# Race Engineer AI - procedura guidata di verifica REALE su Windows (PowerShell 5.1 o 7+). Solo caratteri ASCII.
#
# Cosa fa: controlli preliminari -> (passi manuali in LMU) -> diagnostica -> registrazione >= 60 s con marcature HUD ->
#          report DuckDB nativo -> analisi setup -> confronto HUD -> riepilogo -> verifica che i report siano salvati.
# Cosa NON fa: non modifica file/impostazioni di LMU, non avvia/ferma LMU, non installa plugin, non carica nulla online,
#              non richiede chiavi AI. I file originali (.duckdb, .svm) sono solo letti (hash prima/dopo nel riepilogo).
#
# Uso (PowerShell nella cartella del programma):
#   powershell -ExecutionPolicy Bypass -File .\PROCEDURA_VERIFICA.ps1
# Parametri opzionali (servono solo se i percorsi NON vengono trovati da soli):
#   -DuckdbFile <path.duckdb>  -SetupFile <path.svm>  -HudFile <annotazioni.json>  -Seconds 60
# Parametri per i test automatici (senza LMU):
#   -NonInteractive  -PythonModule  -ShmPath <file>  -DataDir <cartella>  -SkipHud  -CliPath <exe>
#
# Codici di uscita: 0 = verifica automatica REALE superata e report validi; 3 = LMU non raggiungibile / verifica NON superata
#                   (report comunque prodotti); 2 = errore della procedura (CLI non trovato, cartella non scrivibile, report mancanti).
param(
    [string]$CliPath,
    [switch]$PythonModule,
    [int]$Seconds = 60,
    [string]$DuckdbFile,
    [string]$SetupFile,
    [string]$HudFile,
    [string]$ShmPath,
    [string]$DataDir,
    [switch]$NonInteractive,
    [switch]$SkipHud
)
$ErrorActionPreference = "Continue"
$script:Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:Problems = New-Object System.Collections.ArrayList

function Write-Step([string]$t) { Write-Host ""; Write-Host ("=== " + $t + " ===") -ForegroundColor Cyan }
function Write-Ok([string]$t)   { Write-Host ("  [OK]   " + $t) -ForegroundColor Green }
function Write-Warn2([string]$t){ Write-Host ("  [ATT.] " + $t) -ForegroundColor Yellow }
function Write-Bad([string]$t)  { Write-Host ("  [KO]   " + $t) -ForegroundColor Red; [void]$script:Problems.Add($t) }
function Stop-Procedure([string]$t) { Write-Bad $t; Write-Host "Procedura interrotta." -ForegroundColor Red; exit 2 }
function Pause-Manual([string]$t) { if ($NonInteractive) { Write-Host ("  (non interattivo) " + $t) } else { [void](Read-Host $t) } }
function Save-Text([string]$path, [string]$text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}
function Quote-Arg([string]$a) { if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' } else { return $a } }

# ---------------------------------------------------------------- 0. programma
if ($DataDir) { $env:RACE_ENGINEER_DATA = $DataDir }
Write-Step "0. Programma installato"
$script:Exe = $null
$script:UseModule = [bool]$PythonModule
if ($script:UseModule) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { Stop-Procedure "python non trovato (modalita' -PythonModule)." }
    $script:Exe = $py.Source
} else {
    $cands = @()
    if ($CliPath) { $cands += $CliPath }
    $cands += (Join-Path $script:Here "race-engineer-cli.exe")
    $cands += (Join-Path $env:LOCALAPPDATA "Programs\RaceEngineerAI\race-engineer-cli.exe")
    $gc = Get-Command race-engineer-cli -ErrorAction SilentlyContinue
    if ($gc) { $cands += $gc.Source }
    foreach ($c in $cands) { if ($c -and (Test-Path -LiteralPath $c)) { $script:Exe = (Resolve-Path -LiteralPath $c).Path; break } }
    if (-not $script:Exe) { Stop-Procedure "race-engineer-cli.exe non trovato. Cartelle cercate: la cartella dello script e %LOCALAPPDATA%\Programs\RaceEngineerAI. Usa -CliPath <percorso>." }
}
function Invoke-Cli([string[]]$CliArgs, [switch]$KeepStderr) {
    $all = @()
    if ($script:UseModule) { $all += @("-m", "race_engineer") }
    $all += $CliArgs
    if ($KeepStderr) { $out = & $script:Exe @all 2>&1 } else { $out = & $script:Exe @all 2>$null }
    $script:LastExit = $LASTEXITCODE
    return @($out | ForEach-Object { "$_" })
}
Write-Ok ("programma: " + $script:Exe)
$null = Invoke-Cli @("layout")
if ($script:LastExit -ne 0) { Stop-Procedure "il programma non si avvia correttamente (comando 'layout' codice $($script:LastExit))." }
Write-Ok "il programma si avvia"

# ---------------------------------------------------------------- 1. preliminari
function Get-Preflight {
    $a = @("preflight")
    if ($ShmPath) { $a += @("--shm-path", $ShmPath) }
    $txt = (Invoke-Cli $a) -join "`n"
    $script:PfRaw = $txt
    try { return ($txt | ConvertFrom-Json) } catch { return $null }
}
function Show-Preflight($pf) {
    Write-Host ("  app versione {0}, commit {1}" -f $pf.app.version, $(if ($pf.app.commit) { $pf.app.commit } else { "sconosciuto" }))
    if ($pf.data_dir.writable -and $pf.reports_dir.writable) { Write-Ok ("cartella dati scrivibile: " + $pf.data_dir.path) } else { Write-Bad "cartella dati/report NON scrivibile (permessi)." }
    if ($pf.lmu_install.found) { Write-Ok "installazione LMU trovata (sola lettura)" } else { Write-Warn2 "installazione LMU non trovata (imposta LMU_GAME_DIR se e' in una cartella non standard)" }
    if ($pf.lmu_process_running -eq $true) { Write-Ok "processo LMU in esecuzione" } elseif ($pf.lmu_process_running -eq $false) { Write-Warn2 "processo LMU non in esecuzione" } else { Write-Warn2 "stato processo LMU non determinabile" }
    if ($pf.mapping.present) { Write-Ok ("mapping LMU_Data presente, dimensione {0}, gameVersion {1}" -f $pf.mapping.size, $pf.mapping.game_version) } else { Write-Warn2 ("mapping LMU_Data NON presente: " + $pf.mapping.error) }
    Write-Host ("  file DuckDB nativi trovati: {0}; file setup (.svm) trovati: {1}" -f @($pf.duckdb_files).Count, @($pf.setup_files).Count)
    foreach ($w in @($pf.warnings)) { if ($w) { Write-Warn2 $w } }
}
Write-Step "1. Controlli preliminari"
$pf = Get-Preflight
if (-not $pf) { Stop-Procedure "preflight non leggibile (output non JSON)." }
if (-not ($pf.data_dir.writable -and $pf.reports_dir.writable)) { Show-Preflight $pf; Stop-Procedure "non posso scrivere in $($pf.reports_dir.path): controlla i permessi o usa -DataDir." }
$ReportsDir = $pf.reports_dir.path
New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$existing = @{}
Get-ChildItem -LiteralPath $ReportsDir -File -ErrorAction SilentlyContinue | ForEach-Object { $existing[$_.Name] = "$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
Show-Preflight $pf

if (-not $pf.mapping.present -and -not $NonInteractive) {
    Write-Step "2. Passi manuali in LMU (il programma NON li esegue)"
    Write-Host "  a) Avvia Le Mans Ultimate da Steam."
    Write-Host "  b) Settings > Gameplay > Enable Plugins = ON, poi CHIUDI e RIAVVIA completamente LMU."
    Write-Host "  c) Carica una sessione (es. Prove libere), esci dai box ed entra in pista."
    for ($i = 1; $i -le 3 -and -not $pf.mapping.present; $i++) {
        [void](Read-Host "Premi Invio quando sei in pista (tentativo $i/3)")
        $pf = Get-Preflight
        if ($pf) { Show-Preflight $pf } else { break }
    }
    if (-not $pf) { Stop-Procedure "preflight non leggibile." }
    if (-not $pf.mapping.present) { Write-Warn2 "mapping ancora assente: eseguo comunque la verifica, che documentera' il problema." }
} elseif ($pf.mapping.present -and -not $NonInteractive) {
    Write-Host "  Entra in pista e guida con continuita' durante la registrazione."
}
$PreflightFile = Join-Path $ReportsDir ("preflight_" + $ts + ".json")
Save-Text $PreflightFile $script:PfRaw

# ---------------------------------------------------------------- 3. registrazione
Write-Step ("3. Diagnostica e registrazione di " + $Seconds + " s (dati REALI da memoria condivisa)")
if ($Seconds -lt 60) { Write-Warn2 "meno di 60 s: la verifica definitiva richiede almeno 60 s." }
$null = Invoke-Cli @("diagnose")
Write-Host ("  diagnose: codice " + $script:LastExit + " (0 = mapping raggiungibile, 2 = non raggiungibile)")

$vlog = Join-Path $ReportsDir ("verify_console_" + $ts + ".log")
$verr = Join-Path $ReportsDir ("verify_console_" + $ts + ".err.log")
$vargs = @(); if ($script:UseModule) { $vargs += @("-m", "race_engineer") }
$vargs += @("verify-lmu", "--seconds", "$Seconds", "--out", $ReportsDir)
if ($ShmPath) { $vargs += @("--shm-path", $ShmPath) }
$argString = ($vargs | ForEach-Object { Quote-Arg $_ }) -join " "
if (-not $NonInteractive) { Write-Host "  Durante la registrazione premi INVIO ogni volta che leggi i valori sull'HUD (max ~6 volte) e annotali." -ForegroundColor Yellow }
$proc = Start-Process -FilePath $script:Exe -ArgumentList $argString -RedirectStandardOutput $vlog -RedirectStandardError $verr -NoNewWindow -PassThru
$marks = New-Object System.Collections.ArrayList
$printed = 0
$canKey = (-not $NonInteractive)
while (-not $proc.HasExited) {
    if ($canKey) {
        try {
            while ([Console]::KeyAvailable) {
                $k = [Console]::ReadKey($true)
                if ($k.Key -eq [ConsoleKey]::Enter) {
                    $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
                    [void]$marks.Add($epoch)
                    Write-Host ("  >>> marcatura #{0} registrata alle {1} - annota velocita', RPM, marcia, giro, acceleratore, freno dell'HUD" -f $marks.Count, (Get-Date -Format "HH:mm:ss")) -ForegroundColor Magenta
                }
            }
        } catch { $canKey = $false }
    }
    $lines = @(Get-Content -LiteralPath $vlog -ErrorAction SilentlyContinue)
    for ($i = $printed; $i -lt $lines.Count; $i++) { Write-Host ("  " + $lines[$i]) }
    $printed = $lines.Count
    Start-Sleep -Milliseconds 250
}
$proc.WaitForExit()
$verifyExit = $proc.ExitCode
$lines = @(Get-Content -LiteralPath $vlog -ErrorAction SilentlyContinue)
for ($i = $printed; $i -lt $lines.Count; $i++) { Write-Host ("  " + $lines[$i]) }
Write-Host ("  verify-lmu: codice di uscita " + $verifyExit)

$VerifyMd = $null
foreach ($l in $lines) { if ($l -match '^Report:\s+(.+?\.md)') { $VerifyMd = $Matches[1].Trim() } }
$VerifyJson = $null
if ($VerifyMd) { $VerifyJson = [System.IO.Path]::ChangeExtension($VerifyMd, ".json") }
if (-not ($VerifyJson -and (Test-Path -LiteralPath $VerifyJson))) {
    $VerifyJson = $null
    $cand = Get-ChildItem -LiteralPath $ReportsDir -Filter "lmu_verification_*.json" -File -ErrorAction SilentlyContinue | Where-Object { -not $existing.ContainsKey($_.Name) } | Sort-Object LastWriteTime | Select-Object -Last 1
    if ($cand) { $VerifyJson = $cand.FullName; $VerifyMd = [System.IO.Path]::ChangeExtension($cand.FullName, ".md") }
}
if (-not $VerifyJson) { Write-Bad "report di verifica non trovato dopo verify-lmu." }

# ---------------------------------------------------------------- 4. DuckDB e setup
Write-Step "4. Telemetria DuckDB nativa e setup (percorsi cercati automaticamente)"
$pf2 = Get-Preflight
if (-not $pf2) { $pf2 = $pf }
$duck = $DuckdbFile
if (-not $duck -and @($pf2.duckdb_files).Count -gt 0) {
    $duck = @($pf2.duckdb_files)[0].path
    Write-Ok ("DuckDB piu' recente trovato: " + (Split-Path -Leaf $duck))
}
if (-not $duck -and -not $NonInteractive) {
    $duck = Read-Host "Nessun .duckdb trovato. Incolla il percorso completo (Invio per saltare)"
}
$svm = $SetupFile
if (-not $svm -and @($pf2.setup_files).Count -gt 0) {
    $svm = @($pf2.setup_files)[0]
    Write-Ok ("setup piu' recente trovato: " + (Split-Path -Leaf $svm))
}
if (-not $svm -and -not $NonInteractive) {
    $svm = Read-Host "Nessun .svm trovato. Incolla il percorso completo (Invio per saltare)"
}
if ($duck -and -not (Test-Path -LiteralPath $duck)) { Write-Bad ("file DuckDB indicato non esiste: " + $duck); $duck = $null }
if ($svm -and -not (Test-Path -LiteralPath $svm)) { Write-Bad ("file setup indicato non esiste: " + $svm); $svm = $null }

function Get-Snapshot($files, $dirs) {
    $r = @{ files = @(); dir_counts = @{} }
    foreach ($f in $files) {
        if ($f) {
            $item = Get-Item -LiteralPath $f
            $r.files += @{ name = $item.Name; length = $item.Length; mtime_ticks = $item.LastWriteTimeUtc.Ticks; sha256 = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash }
        }
    }
    foreach ($d in $dirs) { if ($d -and (Test-Path -LiteralPath $d)) { $r.dir_counts[(Split-Path -Leaf $d)] = @(Get-ChildItem -LiteralPath $d -Recurse -File -ErrorAction SilentlyContinue).Count } }
    return $r
}
$protectedDirs = @()
if ($pf2.lmu_install.telemetry_dir) { $protectedDirs += $pf2.lmu_install.telemetry_dir }
if ($pf2.lmu_install.user_data) { $protectedDirs += (Join-Path $pf2.lmu_install.user_data "player\Settings") }
$snapBefore = Get-Snapshot @($duck, $svm) $protectedDirs

$DuckdbJson = $null; $SetupJson = $null
if ($duck) {
    $o = Invoke-Cli @("duckdb-report", $duck, "--out", $ReportsDir)
    Write-Host ("  duckdb-report: codice " + $script:LastExit)
    foreach ($l in $o) { if ($l -match '^Report:\s+(.+?\.md)') { $DuckdbJson = [System.IO.Path]::ChangeExtension($Matches[1].Trim(), ".json") } }
    if (-not $DuckdbJson) { Write-Bad "duckdb-report non ha prodotto un report." }
} else { Write-Warn2 "DuckDB: nessun file analizzato (LMU lo scrive a fine sessione/giro: esci ai box e rilancia con -DuckdbFile)." }
if ($svm) {
    $o = Invoke-Cli @("setup-inspect", $svm, "--out", $ReportsDir)
    Write-Host ("  setup-inspect: codice " + $script:LastExit)
    foreach ($l in $o) { if ($l -match '^Report:\s+(.+?\.md)') { $SetupJson = [System.IO.Path]::ChangeExtension($Matches[1].Trim(), ".json") } }
    if (-not $SetupJson) { Write-Bad "setup-inspect non ha prodotto un report." }
} else { Write-Warn2 "Setup: nessun file analizzato (percorso LMU dei .svm non verificato: usa -SetupFile)." }

$snapAfter = Get-Snapshot @($duck, $svm) $protectedDirs
$unchanged = $true; $detail = @()
for ($i = 0; $i -lt $snapBefore.files.Count; $i++) {
    $b = $snapBefore.files[$i]; $a = $snapAfter.files[$i]
    $same = ($b.sha256 -eq $a.sha256) -and ($b.length -eq $a.length) -and ($b.mtime_ticks -eq $a.mtime_ticks)
    if (-not $same) { $unchanged = $false }
    $detail += @{ name = $b.name; sha256_before = $b.sha256; sha256_after = $a.sha256; unchanged = $same }
}
foreach ($k in $snapBefore.dir_counts.Keys) { if ($snapBefore.dir_counts[$k] -ne $snapAfter.dir_counts[$k]) { $unchanged = $false } }
$integ = @{ checked = $true; all_unchanged = $unchanged; files = $detail; dir_file_counts_before = $snapBefore.dir_counts; dir_file_counts_after = $snapAfter.dir_counts }
$IntegFile = Join-Path $ReportsDir ("originals_integrity_" + $ts + ".json")
Save-Text $IntegFile ($integ | ConvertTo-Json -Depth 6)
if ($unchanged) { Write-Ok "file originali analizzati e cartelle LMU: invariati (hash/dimensione/data identici prima e dopo)" } else { Write-Bad "ATTENZIONE: un file originale o il numero di file nelle cartelle LMU e' cambiato durante l'analisi (potrebbe essere LMU stesso: verifica)." }

# ---------------------------------------------------------------- 5. HUD
Write-Step "5. Confronto con l'HUD"
$HudJson = $null
$annFile = $null
if ($SkipHud) { Write-Warn2 "confronto HUD saltato (-SkipHud)." }
elseif ($HudFile) {
    if (Test-Path -LiteralPath $HudFile) { $annFile = $HudFile } else { Write-Bad ("file annotazioni HUD non trovato: " + $HudFile) }
}
elseif ($marks.Count -gt 0 -and -not $NonInteractive) {
    Write-Host "  Inserisci i valori letti sull'HUD per ogni marcatura (Invio = non letto). Tolleranza: finestra +-1.5 s, nessuna precisione al millisecondo."
    $ann = @()
    $n = 0
    foreach ($m in $marks) {
        $n++
        $when = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]($m * 1000)).ToLocalTime().ToString("HH:mm:ss")
        Write-Host ("  Marcatura #{0} ({1})" -f $n, $when) -ForegroundColor Magenta
        $e = @{ epoch = $m }
        foreach ($f in @(@("speed_kmh", "velocita' km/h"), @("rpm", "RPM"), @("gear", "marcia (0=N, -1=R)"), @("lap", "giro"), @("throttle_pct", "acceleratore %"), @("brake_pct", "freno %"))) {
            $v = Read-Host ("    " + $f[1])
            if ($v) {
                $d = 0.0
                if ([double]::TryParse(($v -replace ',', '.'), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$d)) { $e[$f[0]] = $d } else { Write-Warn2 "valore non numerico ignorato" }
            }
        }
        $ann += $e
    }
    $annFile = Join-Path $ReportsDir ("hud_annotations_" + $ts + ".json")
    Save-Text $annFile (ConvertTo-Json -InputObject @($ann) -Depth 4)
    Write-Ok ("annotazioni salvate: " + $annFile)
}
else { Write-Warn2 "nessuna marcatura HUD: durante la registrazione premi INVIO per marcare i momenti, oppure passa -HudFile (vedi docs\WINDOWS-PROCEDURA.md, sezione HUD)." }
if ($annFile -and $VerifyJson) {
    $o = Invoke-Cli @("hud-compare", "--annotations", $annFile, "--verify-report", $VerifyJson, "--out", $ReportsDir) -KeepStderr
    $o | ForEach-Object { Write-Host ("  " + $_) }
    foreach ($l in $o) { if ($l -match '^Report:\s+(.+?\.md)') { $HudJson = [System.IO.Path]::ChangeExtension($Matches[1].Trim(), ".json") } }
}

# ---------------------------------------------------------------- 6. riepilogo
Write-Step "6. Riepilogo automatico"
$sargs = @("verification-summary", "--out", $ReportsDir, "--preflight", $PreflightFile, "--originals", $IntegFile)
if ($VerifyJson) { $sargs += @("--verify", $VerifyJson) }
if ($DuckdbJson) { $sargs += @("--duckdb", $DuckdbJson) }
if ($SetupJson) { $sargs += @("--setup", $SetupJson) }
if ($HudJson) { $sargs += @("--hud", $HudJson) }
$o = Invoke-Cli $sargs
$SummaryMd = $null
foreach ($l in $o) { if ($l -match '^Report:\s+(.+?\.md)') { $SummaryMd = $Matches[1].Trim() } }
$SummaryJson = $null
if ($SummaryMd) { $SummaryJson = [System.IO.Path]::ChangeExtension($SummaryMd, ".json") }

# ---------------------------------------------------------------- 7. verifica dei report salvati
Write-Step "7. Verifica che i report siano stati salvati correttamente"
$expected = @()
foreach ($j in @($PreflightFile, $VerifyJson, $DuckdbJson, $SetupJson, $HudJson, $IntegFile, $SummaryJson)) { if ($j) { $expected += $j } }
foreach ($j in @($VerifyJson, $DuckdbJson, $HudJson, $SummaryJson)) { if ($j) { $expected += [System.IO.Path]::ChangeExtension($j, ".md") } }
$okAll = $true
foreach ($f in $expected) {
    $leaf = Split-Path -Leaf $f
    if (-not (Test-Path -LiteralPath $f)) { Write-Bad ("MANCANTE: " + $leaf); $okAll = $false; continue }
    $len = (Get-Item -LiteralPath $f).Length
    if ($len -le 0) { Write-Bad ("VUOTO: " + $leaf); $okAll = $false; continue }
    if ($existing.ContainsKey($leaf)) { Write-Bad ("esisteva gia' prima: " + $leaf); $okAll = $false; continue }
    if ($f -like "*.json") {
        try { $null = (Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { Write-Bad ("JSON non valido: " + $leaf); $okAll = $false; continue }
    }
    Write-Ok ("{0}  ({1} byte)" -f $leaf, $len)
}
$overwritten = @()
foreach ($name in $existing.Keys) {
    $p = Join-Path $ReportsDir $name
    if (-not (Test-Path -LiteralPath $p)) { $overwritten += $name; continue }
    $it = Get-Item -LiteralPath $p
    if ("$($it.Length)|$($it.LastWriteTimeUtc.Ticks)" -ne $existing[$name]) { $overwritten += $name }
}
if ($overwritten.Count -gt 0) { Write-Bad ("report precedenti modificati/rimossi: " + ($overwritten -join ", ")); $okAll = $false } else { Write-Ok "nessun report precedente sovrascritto o rimosso" }

# ---------------------------------------------------------------- esito
Write-Step "Esito"
$status = "(riepilogo non disponibile)"
if ($SummaryJson -and (Test-Path -LiteralPath $SummaryJson)) {
    try { $sm = Get-Content -LiteralPath $SummaryJson -Raw -Encoding UTF8 | ConvertFrom-Json; $status = $sm.phase1.status; Write-Host ("  Origine dati: " + $sm.data_origin) } catch { }
}
Write-Host ("  " + $status) -ForegroundColor Yellow
Write-Host ("  Cartella dei risultati: " + $ReportsDir) -ForegroundColor Green
if ($SummaryMd) { Write-Host ("  Riepilogo: " + $SummaryMd) -ForegroundColor Green }
if ($VerifyMd) { Write-Host ("  Verifica LMU: " + $VerifyMd) -ForegroundColor Green }
Write-Host "  Nulla e' stato caricato online. I report non contengono chiavi ne' nome utente (percorsi abbreviati)."
if (-not $NonInteractive -and $SummaryMd -and (Test-Path -LiteralPath $SummaryMd)) { Start-Process notepad $SummaryMd }
if (-not $okAll) { exit 2 }
if ($script:Problems.Count -gt 0) { exit 2 }
if (-not $VerifyJson) { exit 2 }
if ($verifyExit -ne 0) { exit 3 }
exit 0
