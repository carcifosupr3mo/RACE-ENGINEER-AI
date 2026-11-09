@echo off
rem Diagnostica base (installazione LMU, processo, mapping LMU_Data) in JSON. Nessun dato personale.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
%RE% diagnose
pause >nul
