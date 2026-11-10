# VALIDAZIONE — cosa è verificato e cosa no (aggiornato 2026-11-09)

## Legenda
- **LMU reale**: provato con Le Mans Ultimate in esecuzione su Windows. **Nessuna voce è in questo stato.**
- **API reali**: provato con chiavi vere NVIDIA/Groq. **Nessuna chiave era disponibile: nessuna voce è in questo stato.**
- **Windows CI**: provato su un runner Windows di GitHub Actions (senza LMU).
- **Sintetico**: provato con dati/provider finti, sempre marcati come tali.
- **Fatti pubblici**: letto dalla documentazione pubblica del provider in data odierna, senza account.

## Esito CI più recente (evidenza reale su Windows, SENZA LMU)

| Campo | Valore |
|---|---|
| Commit verificato (build precedente alla procedura) | `fa45cd4` ([run 6 `42654580988`](https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/actions/runs/42654580988)), 2026-11-09, **success**. Rispetto a `5c67308` ([run 5 `42654465650`](https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/actions/runs/42654465650), anch'esso **success**) cambia solo la documentazione: stesso codice |
| Ambiente Windows | runner GitHub `windows-latest`, Python 3.13.17, Inno Setup 6.7.1, PyInstaller 6.22.3, PySide6/WebEngine 6.12.0 |
| Job `frontend` (ubuntu) | success: `npm ci && npm run build && npm test` (4 vitest) |
| Job `backend` (ubuntu) | success: `pytest tests` |
| Job `windows-bundle` | success: build PyInstaller; smoke dell'exe congelato **18/18**; scansione segreti del pacchetto `secret scan: CLEAN`; installer Inno Setup compilato; installazione silenziosa in cartella temporanea; smoke della copia INSTALLATA **18/18** (incl. desktop shell Qt WebEngine `--smoke`); disinstallazione; upload artefatto |
| Artefatto (run 6) | `RaceEngineerAI-windows`, id 13692107404, 580.060.439 B, digest zip `sha256:9db1b657221d9bc6367109a59ea062c4a8a538d995194e817217336829206e74` |
| SHA256 (`SHA256SUMS.txt`, dal log del run 6) | `bc01debf2726e751dfb5ddac299ecd41a867a38c5654d392d68a762f675c9172`  `RaceEngineerAI-Setup-0.1.0.exe`; `461fbd126a32fbfb2a768bca9e0001cab9510b84c3cdefd4ed2bb6524db921ad`  `RaceEngineerAI-win32.zip` |
| Nota sui checksum | Le build non sono riproducibili: ogni run produce hash diversi (run 5: Setup `0590a103...bdfc`, zip `c73b1a92...8cf5`; run 4: Setup `4f536b0f...16dd`). Vale sempre il `SHA256SUMS.txt` dentro l'artefatto che si scarica; ogni push (anche solo documentazione) genera un nuovo run e un nuovo artefatto |
| Storia | run 1 success; run 2 e 3 fallite (solo il controllo "grounded chat" dello smoke: HTTP 409 perche' la sessione live era in registrazione) -> corretto lo smoke (attende una sessione conclusa), nessun controllo ridotto; run 4, 5, 6 verdi |

Dettaglio dei controlli di smoke (identici sull'exe congelato e sulla copia installata): layout CLI; `diagnose`; `verify-lmu` produce report e NON dichiara la verifica senza LMU; `ai-test --no-send` senza chiavi non invia nulla; `endurance-sim` 1 h; `serve` parte; `/app/` e `/diag` serviti; acquisizione sintetica produce campioni; sessione registrata nel catalogo; `/api/ai/providers` non espone valori di chiave; `/api/endurance/status`; chat con dati reali della sessione (motore a regole); spegnimento controllato; persistenza dopo riapertura; desktop shell `--smoke`.

### Test eseguiti in locale (Linux, sandbox) - SINTETICI
- backend: 146 test pytest passati (rc 0), commit `5c67308`.
- frontend: 4 vitest; Playwright e2e 19 controlli (dati sintetici `constant mixed`).
- smoke da sorgente (`scripts/smoke_bundle.py --source`): 18/18 (include i 2 controlli CLI aggiunti: `duckdb-report` senza file, `setup-inspect` senza file).
- endurance 24 h: simulazione a tempo accelerato con provider finti.

### Cosa NON e' stato eseguito
- Qualsiasi prova con LMU reale (shared memory, offset, `gameVersion`, confronto HUD).
- File DuckDB e setup reali. Richieste reali a NVIDIA/Groq (nessuna chiave).
- Comportamento visivo di tray/notifiche; 24 h in tempo reale; installazione su un PC Windows "pulito" con SmartScreen (l'exe non e' firmato).

### Limiti
- Windows CI = runner senza LMU, senza GPU/audio: non prova l'uso con il simulatore.
- Installer e exe non firmati: Windows SmartScreen puo' avvisare.
- La Fase 1 resta "implementata, NON accettata" finche' `verify-lmu` non gira su LMU reale. Procedura: `docs/WINDOWS-PROCEDURA.md`.

## Procedura Windows di verifica definitiva (commit `2a59029`)
**Verificato su runner Windows GitHub, SENZA LMU, con file sintetici** - [run 9 `42677367561`](https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/actions/runs/42677367561), tutti i job success:
| Cosa | Esito |
|---|---|
| backend (ubuntu) / frontend (ubuntu) | success |
| `windows-procedure`: `Test-Procedura.ps1` su **Windows PowerShell 5.1** e su **PowerShell 7** | success, 0 controlli falliti (circa 25 controlli per shell) |
| `windows-bundle`: build, smoke exe congelato **20/20**, `secret scan: CLEAN`, installer, installazione silenziosa + smoke della copia installata **20/20**, disinstallazione, upload | success |
| `windows-bundle`: `Test-Procedura.ps1` contro l'**exe congelato** (PowerShell 7.6.9) | success, tutti i controlli passati |
| Artefatto `RaceEngineerAI-windows` | id 13701747102, 580.173.041 B, digest zip `sha256:710f27bceb5ec4de0879795c2773e41a3fdb55d9ffd6260dda69fe7db6e5130e` |
| SHA256 (`SHA256SUMS.txt`, log) | Setup `4cb5ca8a6c055c7321737d8b27a64f73c92a22c60e97dc84849534fdc56dbb1a`; zip `db5b1338becb3ce8584d33aea76f3149d19dc52dcb8fffce49840b3826659fb7` |

Cosa dimostrano i test PowerShell: report creati, non vuoti e JSON validi; dati da file/bridge => verifica NON reale (codice 3) e riepilogo "NOT COMPLETE / data NOT REAL"; DuckDB e setup trovati automaticamente; HUD non eseguito dichiarato tale; file originali e cartella LMU simulata invariati (hash/dimensioni/date, nessun file creato); nessun nome utente nei report (md e json); seconda esecuzione non sovrascrive i report precedenti; senza LMU/mapping/file: codice 3 con elenco di cio' che manca (nessun crash); percorso inesistente: errore (codice 2); la procedura non usa chiavi AI ne' rete.

Problemi trovati dalla CI Windows e corretti prima di questo esito (run 8, `63c4fac`): nomi utente presenti nei report (JSON con backslash raddoppiati non venivano abbreviati) -> sanitizzazione strutturale; `ExitCode` del processo vuoto in PowerShell 5.1 -> esito deciso dal verdetto nel report; log grezzo della console spostato fuori da `reports`. Correzione di sostanza: `verify-lmu --shm-path` non puo' piu' risultare "REAL"; un mapping non raggiungibile esce con codice 3.

Test Python (offline, sintetici): `backend/tests/test_verification_flow.py` (preflight, verdetto file/bridge non reale anche "su Windows", confronto HUD con latenza/arrotondamenti, errori HUD, offset di numerazione, riepilogo mai "completo", nessun nome utente, nessuna sovrascrittura). Totale locale: 157 pytest.

**Non verificato (richiede LMU reale)**: tutto cio' che riguarda mapping/offset/gameVersion reali, frequenza e campioni da LMU, confronto HUD reale, DuckDB e setup reali, interazione di tasti (INVIO per le marcature) e prompt interattivi (testati solo in modalita' `-NonInteractive`), commit nel pacchetto (`build_info.json`) non asserito dai test sul pacchetto.

## Sistema unificato con Driving Display (v0.5.0) — SOLO dati sintetici, nessun LMU
Eseguito in locale (Linux, sandbox), tutto **sintetico**:
- backend: 184 pytest (157 preesistenti + 27 nuovi: `test_driving_analysis.py`, `test_live_engineer.py`).
- frontend: 8 vitest (4 preesistenti + 4 nuovi); `npm run build` rigenerato in `webdist`.
- `scripts/smoke_bundle.py --source`: 29 controlli (9 nuovi: pagina display, stato condiviso, info display, mappa, `--lan` token/403/URL), incluso lo shell desktop Qt WebEngine che renderizza il display.
- Playwright `frontend/e2e/display.cjs`: banner sintetico, velocità live via WebSocket, stato di apprendimento, mappa da posizioni reali con zone, un solo suggerimento, delta, modalità sessione, zoom, tap su curva, coerenza dashboard/display/REST, stato offline e riconnessione automatica, 4 viewport (1280x800, 1024x600, 800x480, 600x1000) senza scroll né ritagli.

**Non verificato**: LMU reale (posizioni, orientamento assi, numerazione curve su dati veri), secondo monitor fisico, Raspberry/tablet in LAN, provider AI reali, esito CI Windows di questo commit (vedi sezione CI dopo il push).

## Stato per elemento

| Elemento | Stato |
|---|---|
| Mapping `LMU_Data`, offset, dimensione 324820 B, `gameVersion` | NON verificato su LMU reale. Strumento pronto: `verify-lmu` (confronta anche gli offset con gli header installati tramite `lmu/header_layout.py`, testato in round-trip) |
| Lettore Windows sola lettura (`OpenFileMappingW`/`FILE_MAP_READ`) | Mai eseguito su LMU. Verifica statica anti-scrittura/iniezione inclusa nel report (`read_only_source`) e nei test |
| Frequenza effettiva, campioni persi, riconnessione, qualità registrazione su LMU | NON verificato (il report le misura) |
| DuckDB reali | NON verificato (nessun file). `duckdb-report` pronto; anomalia G Lat/Long: test a correlazione con verdetto `as_named/swapped/inconclusive`, mai applicato; i canali G restano esclusi dall'import |
| Setup reali | NON verificato. `setup-inspect` accetta `.svm` (INI rFactor-style, **ipotesi non verificata**) e JSON, conserva copia verbatim + SHA256; nessuna proposta numerica senza limiti verificati (un `.svm` non contiene min/max/step) |
| Build Windows (.exe, installer, smoke, SHA256) | VERIFICATO su runner Windows CI (run 5 e 6, sezione sopra); mai provato su un PC Windows reale con LMU |
| NVIDIA | Fatti pubblici: `GET /v1/models` (pubblico) elenca `nvidia/nemotron-3.5-lightning-30b-a3b`. **Non prova** che sia un endpoint gratuito per il tuo account; richieste reali NON eseguite |
| Groq | Fatti pubblici (docs, 2026-11-09): esistono `openai/gpt-oss-120b` e `qwen/qwen3.8-27b`; piano free: 30 RPM, 1K RPD, 8K TPM, 200K TPD. Richieste reali NON eseguite |
| Endurance 24 h | Sintetico, tempo simulato, provider finti: `docs/reports/endurance_sim_24h_synthetic.json`. Non dimostra la disponibilità di provider reali né 24 h di tempo reale |

## Cosa fare sul PC Windows (in ordine)
1. Installa (CI → artefatto `RaceEngineerAI-windows`: Setup .exe o zip; controlla `SHA256SUMS.txt`). Procedura PowerShell completa: `docs/WINDOWS-PROCEDURA.md` (`scripts\windows\PROCEDURA_VERIFICA.ps1`).
2. In LMU: Settings → Gameplay → **Enable Plugins**, riavvia LMU completamente, carica una sessione, entra in pista.
3. Esegui `VERIFICA_LMU.bat` (60 s) guidando; confronta velocità/RPM/marcia/giro a schermo con la tabella finale del report `.md`. Invia/conserva il report (senza credenziali né nome utente).
4. Trascina un file `UserData\Telemetry\*.duckdb` su `DIAGNOSI_DUCKDB.bat`; leggi `g_force_analysis.verdict`.
5. `DIAGNOSI_SETUP.bat` (senza argomenti elenca i `.svm`; poi trascina uno).
6. Chiavi: imposta `NVIDIA_API_KEY` / `GROQ_API_KEY` oppure incollale in Settings → AI; poi `TEST_AI.bat` o il pulsante "Prova reale".

### Verifica finale locale del sistema unificato (2026-11-10, SINTETICA, esecuzione unica dopo le ultime modifiche)
| Controllo | Comando | Exit code | Risultato |
|---|---|---|---|
| vitest | `npm test` | 0 | 8/8 |
| build frontend | `npm run build` | 0 | webdist rigenerato |
| backend | `pytest tests` | 0 | 184 test passati (nessun FAIL/Traceback nel log) |
| smoke da sorgente | `scripts/smoke_bundle.py --source` | 0 | 29/29 (incl. shell desktop Qt WebEngine e `/api/engineer/checklist`) |
| E2E Playwright Driving Display | `node e2e/display.cjs` | 0 | 38 controlli PASS: live, mappa, zone, suggerimento unico, coerenza dashboard/display/REST, fullscreen (pulsante e tasto F), offline + riconnessione, 4 viewport (1280x800, 1024x600, 800x480, 600x1000) senza scroll né ritagli |
| `live-check` su dati sintetici | `race_engineer live-check` | 3 (atteso) | verdetto `SYNTHETIC_NOT_REAL`: un run sintetico non può certificare la catena reale |

I messaggi `nanobind: leaked ...` stampati da DuckDB alla chiusura dell'interprete sono benigni e preesistenti (non cambiano l'exit code; l'esito conta dal codice di uscita e dal conteggio dei test). Il test «dashboard e display simultanei» su due schermi fisici NON è eseguibile da qui: Playwright usa due pagine dello stesso browser.

Nuovo in questa fase: `/api/engineer/checklist` e `race-engineer-cli live-check` (report sanitizzato in 11 passi, dati REALI/SINTETICI espliciti), `AVVIA_CON_DISPLAY.bat`, `VERIFICA_DISPLAY.bat`, opzione `--port` della shell desktop, pulsante/tasto F per il tutto schermo + wake lock opzionale. Procedura reale e regole firewall: `docs/UNIFIED_DRIVING_DISPLAY.md` §9-10.
