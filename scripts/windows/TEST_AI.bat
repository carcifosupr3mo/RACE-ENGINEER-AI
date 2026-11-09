@echo off
rem Prova reale (poche decine di token GRATUITI) di NVIDIA e Groq. Le chiavi si leggono da NVIDIA_API_KEY / GROQ_API_KEY
rem oppure da Gestione credenziali di Windows (salvate dall'app). Le chiavi non vengono mai stampate.
setlocal
cd /d "%~dp0"
if exist "race-engineer-cli.exe" (set "RE=race-engineer-cli.exe") else (set "RE=python -m race_engineer")
%RE% ai-test
pause >nul
