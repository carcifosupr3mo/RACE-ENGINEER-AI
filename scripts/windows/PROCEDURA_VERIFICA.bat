@echo off
rem Avvia la procedura guidata di verifica reale (PowerShell). Sola lettura, nulla viene caricato online, nessuna chiave richiesta.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0PROCEDURA_VERIFICA.ps1" %*
echo.
echo Codice di uscita: %ERRORLEVEL%  (0 = verificato, 3 = non verificato ma report prodotti, 2 = errore della procedura)
pause >nul
