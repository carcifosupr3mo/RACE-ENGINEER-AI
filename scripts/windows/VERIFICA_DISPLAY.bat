@echo off
rem Verifica live della catena LMU -> mappa -> analisi -> Driving Display (sola lettura, locale, nulla viene caricato).
rem Prerequisito: Race Engineer AI avviato con la porta fissa (AVVIA_CON_DISPLAY.bat), LMU in pista da almeno 3 giri.
rem Il report (Markdown + JSON) non contiene nome pilota, percorsi utente ne' chiavi. Sono dati REALI solo se il verdetto lo dice.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
%RE% live-check --port 8765
echo.
echo Codice di uscita: %ERRORLEVEL%  (0 = dati reali e tutti i passi automatici OK, 3 = incompleto o sintetico, 2 = app non raggiungibile)
pause >nul
