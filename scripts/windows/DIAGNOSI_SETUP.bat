@echo off
rem Ispeziona un file setup di LMU (.svm). Senza argomenti elenca i .svm trovati in UserData\player\Settings.
rem Trascina un file .svm su questo .bat. Il file originale NON viene modificato; viene conservata una copia fedele.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
%RE% setup-inspect %1
pause >nul
