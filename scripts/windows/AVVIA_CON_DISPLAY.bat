@echo off
rem Avvia Race Engineer AI con porta fissa 8765 (dashboard) e apre il Driving Display sul secondo monitor.
rem Per usare il display da un altro dispositivo in rete aggiungi --lan alla riga di avvio (il token viene mostrato dal programma).
setlocal
cd /d "%~dp0"
if not exist "RaceEngineerAI.exe" (echo RaceEngineerAI.exe non trovato in questa cartella & pause & exit /b 2)
start "" "RaceEngineerAI.exe" --port 8765 --display
echo Dashboard:        http://127.0.0.1:8765/app/
echo Driving Display:  http://127.0.0.1:8765/driving-display
