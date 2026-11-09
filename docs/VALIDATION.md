# VALIDAZIONE — cosa è verificato e cosa no (aggiornato 2026-11-09)

## Legenda
- **LMU reale**: provato con Le Mans Ultimate in esecuzione su Windows. **Nessuna voce è in questo stato.**
- **API reali**: provato con chiavi vere NVIDIA/Groq. **Nessuna chiave era disponibile: nessuna voce è in questo stato.**
- **Windows CI**: provato su un runner Windows di GitHub Actions (senza LMU).
- **Sintetico**: provato con dati/provider finti, sempre marcati come tali.
- **Fatti pubblici**: letto dalla documentazione pubblica del provider in data odierna, senza account.

| Elemento | Stato |
|---|---|
| Mapping `LMU_Data`, offset, dimensione 324820 B, `gameVersion` | NON verificato su LMU reale. Strumento pronto: `verify-lmu` (confronta anche gli offset con gli header installati tramite `lmu/header_layout.py`, testato in round-trip) |
| Lettore Windows sola lettura (`OpenFileMappingW`/`FILE_MAP_READ`) | Mai eseguito su LMU. Verifica statica anti-scrittura/iniezione inclusa nel report (`read_only_source`) e nei test |
| Frequenza effettiva, campioni persi, riconnessione, qualità registrazione su LMU | NON verificato (il report le misura) |
| DuckDB reali | NON verificato (nessun file). `duckdb-report` pronto; anomalia G Lat/Long: test a correlazione con verdetto `as_named/swapped/inconclusive`, mai applicato; i canali G restano esclusi dall'import |
| Setup reali | NON verificato. `setup-inspect` accetta `.svm` (INI rFactor-style, **ipotesi non verificata**) e JSON, conserva copia verbatim + SHA256; nessuna proposta numerica senza limiti verificati (un `.svm` non contiene min/max/step) |
| Build Windows (.exe, installer, smoke, SHA256) | Vedi job `windows-bundle` della CI: l'esito è quello dell'ultimo run su GitHub Actions, non una verifica locale |
| NVIDIA | Fatti pubblici: `GET /v1/models` (pubblico) elenca `nvidia/nemotron-3.5-lightning-30b-a3b`. **Non prova** che sia un endpoint gratuito per il tuo account; richieste reali NON eseguite |
| Groq | Fatti pubblici (docs, 2026-11-09): esistono `openai/gpt-oss-120b` e `qwen/qwen3.8-27b`; piano free: 30 RPM, 1K RPD, 8K TPM, 200K TPD. Richieste reali NON eseguite |
| Endurance 24 h | Sintetico, tempo simulato, provider finti: `docs/reports/endurance_sim_24h_synthetic.json`. Non dimostra la disponibilità di provider reali né 24 h di tempo reale |

## Cosa fare sul PC Windows (in ordine)
1. Installa (CI → artefatto `RaceEngineerAI-windows`: Setup .exe o zip; controlla `SHA256SUMS.txt`).
2. In LMU: Settings → Gameplay → **Enable Plugins**, riavvia LMU completamente, carica una sessione, entra in pista.
3. Esegui `VERIFICA_LMU.bat` (60 s) guidando; confronta velocità/RPM/marcia/giro a schermo con la tabella finale del report `.md`. Invia/conserva il report (senza credenziali né nome utente).
4. Trascina un file `UserData\Telemetry\*.duckdb` su `DIAGNOSI_DUCKDB.bat`; leggi `g_force_analysis.verdict`.
5. `DIAGNOSI_SETUP.bat` (senza argomenti elenca i `.svm`; poi trascina uno).
6. Chiavi: imposta `NVIDIA_API_KEY` / `GROQ_API_KEY` oppure incollale in Settings → AI; poi `TEST_AI.bat` o il pulsante "Prova reale".
