# Come creare una release stabile (procedura per il manutentore)

**Regola:** nulla viene pubblicato da solo. Il workflow `release` parte solo se lo avvii tu a mano (Actions → release → Run workflow). Non esiste nessun passo automatico che crei tag o release.

## Come l'app riconosce la nuova versione
All'avvio (e se attivo, in automatico) l'app legge l'elenco delle release del repository `carcifosupr3mo/RACE-ENGINEER-AI` e considera **solo** quelle: non bozze, non pre-release, con tag esattamente `vX.Y.Z`. Se `X.Y.Z` è maggiore della versione installata e la release contiene `RaceEngineerAI-win32.zip` + `SHA256SUMS.txt`, propone l'aggiornamento. Una pre-release (`v0.8.0-rc1`) **non** viene mai offerta.

## Passi
1. **Versione**: aggiorna `backend/race_engineer/__init__.py` (`__version__`), `CHANGELOG.md`. La versione dentro il pacchetto deve coincidere col tag (il workflow lo controlla).
2. **Push** sul branch e attendi la CI **tutta verde** (5 job, in particolare `windows-bundle`: build, smoke, test dell'updater congelato, installer reale, artefatto `RaceEngineerAI-windows`). Annota l'id del run e lo SHA del commit.
3. **Test sul tuo PC** (non automatizzabili): `docs/LMU-TEST-REALE.md` con LMU reale e un aggiornamento da una versione precedente installata.
4. **(Una tantum) Chiave di firma**: `python scripts/make_signing_key.py` → incolla la chiave pubblica in `updater/signing.py` (`PUBLIC_KEY_HEX`), salva la privata nel secret `RELEASE_SIGNING_KEY_PEM` del repository e in un backup privato. Questa modifica va rilasciata **prima** (una versione che contiene già la chiave); da quel momento le app rifiutano release senza firma valida.
5. **Pre-release di prova** (consigliata): Run workflow con `stable=false`, tag `v0.8.0-rc1`. Non viene offerta agli utenti. Scarica, controlla l'hash.
6. **Release stabile**: Run workflow con `run_id`, `tag=v0.8.0`, `commit`, `stable=true`. Il workflow rifiuta se: il run non è verde, il run non è stato costruito da quel commit, i checksum non tornano, la versione nel pacchetto non coincide col tag, manca la firma pur essendo la chiave nell'app.
7. **Dopo la pubblicazione**: su un PC con la versione precedente apri l'app → deve comparire il popup «Aggiornamento disponibile» → AGGIORNA → l'app si riavvia nella nuova versione, i dati restano.

## File della release
| File | A cosa serve |
|---|---|
| `RaceEngineerAI-win32.zip` | pacchetto usato dall'aggiornamento automatico (contiene anche `RaceEngineerUpdater.exe`) |
| `RaceEngineerAI-Setup-<ver>.exe` | installer per nuove installazioni |
| `SHA256SUMS.txt` | hash dei file sopra |
| `SHA256SUMS.txt.sig` | firma Ed25519 di `SHA256SUMS.txt` (quando la chiave è configurata) |

Verifica a mano: `Get-FileHash .\RaceEngineerAI-win32.zip -Algorithm SHA256` deve coincidere con la riga in `SHA256SUMS.txt`. Verifica firma: `openssl pkeyutl -verify -pubin -inkey pub.pem -rawin -in SHA256SUMS.txt -sigfile sig.bin` (con `sig.bin` = base64-decode di `.sig`).

## Sicurezza dell'aggiornamento: cosa protegge e cosa no
- **SHA-256 (sempre)**: protegge da download corrotti/troncati. **Non** protegge se qualcuno può modificare la release (account GitHub rubato): potrebbe cambiare pacchetto e checksum insieme.
- **Firma Ed25519 (da attivare con il passo 4)**: chi modifica la release non può rifirmare senza la chiave privata, che non è su GitHub Releases ma solo nei secret. L'app contiene solo la chiave pubblica. Implementazione di sola libreria standard, nessuna dipendenza nuova; testata con i vettori RFC 8032 e con OpenSSL.
- **Limite**: se la chiave privata viene rubata o persa, serve rilasciare a mano una nuova versione con una nuova chiave pubblica. Un secret di GitHub è leggibile da chi può modificare i workflow: proteggi il branch e i permessi.
- **Firma del codice Windows (Authenticode)**: non c'è certificato; Windows SmartScreen può mostrare un avviso. Il supporto in build esiste (`WINDOWS_SIGN_PFX_BASE64`) ma serve un certificato a pagamento: decisione tua.
- Altre difese già presenti: solo HTTPS e host GitHub (anche dopo i redirect), solo release stabili, estrazione anti zip-slip, controllo spazio disco, backup per rinomina e rollback automatico.
