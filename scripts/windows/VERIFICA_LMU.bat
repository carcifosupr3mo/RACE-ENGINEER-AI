@echo off
rem Verifica reale di Le Mans Ultimate (sola lettura). Avvia LMU, carica una sessione, entra in pista e lancia questo file.
rem Genera un report (Markdown + JSON) senza credenziali e senza nome utente; nulla viene caricato online.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
echo === Race Engineer AI - verifica LMU reale (60 s) ===
echo Guida in pista e confronta i valori a schermo con quelli del HUD di LMU.
%RE% verify-lmu --seconds 60
echo.
echo Il percorso del report e' indicato sopra ("Report:"). Premi un tasto per chiudere.
pause >nul
