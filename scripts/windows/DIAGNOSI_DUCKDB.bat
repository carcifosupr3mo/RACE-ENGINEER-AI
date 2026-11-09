@echo off
rem Report locale dello schema di un file telemetria DuckDB di LMU. Trascina il file .duckdb su questo .bat.
rem Il file originale NON viene modificato (lavora su una copia). Nulla viene caricato online.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
if "%~1"=="" (
  echo Trascina un file .duckdb di UserData\Telemetry su questo file.
  pause >nul & exit /b 1
)
%RE% duckdb-report "%~1"
pause >nul
