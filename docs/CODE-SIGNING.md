# Firma digitale degli eseguibili Windows

## Stato attuale
- La **pipeline di firma è pronta e provata in CI** su Windows vero: `scripts/sign_windows.py` firma `RaceEngineerAI.exe`, `race-engineer-cli.exe`, l'installer e il disinstallatore, con marca temporale, e controlla ogni firma dopo averla apposta.
- **Manca il certificato.** Finché non viene configurato, la build prosegue **non firmata** e lo dichiara: nel log, in `dist/SIGNING.txt`, in `build_info.json` (`"signed": false`) e nelle note della release.
- Un certificato di firma del codice attesta l'identità di una persona o di un'azienda verificata da un ente certificatore: non può essere creato dal progetto né da uno strumento automatico. Va richiesto dal titolare.

## Cosa cambia con la firma
| | Non firmato | Certificato autofirmato | Certificato di un ente riconosciuto |
|---|---|---|---|
| «Autore sconosciuto» nelle proprietà/UAC | sì | no, **solo** sui PC dove il certificato è stato installato come attendibile | no, su tutti i PC |
| Avviso SmartScreen al primo avvio di un file scaricato | sì | sì | può comparire finché il certificato non ha accumulato reputazione |
| Garanzia che il file non è stato alterato | solo con l'hash in `SHA256SUMS.txt` | sì (dove il certificato è attendibile) | sì |

## Come ottenere un certificato
Condizioni e prezzi cambiano: verifica sempre sul sito indicato prima di decidere.

1. **SignPath Foundation — gratuito per progetti open source** (<https://signpath.org>). Il repository è già pubblico; servono anche una licenza open source riconosciuta nel repository (oggi **non c'è**: sceglierla è una decisione del titolare), l'autenticazione a due fattori e una pagina con la politica di firma. L'autore mostrato da Windows sarebbe «SignPath Foundation». La firma avviene tramite la loro GitHub Action, non con un file `.pfx`: richiede un piccolo adattamento della build, da fare quando l'account è approvato.
2. **Certificato OV/EV a pagamento** da un ente certificatore. Dal 2023 la chiave privata risiede su token hardware o su un servizio cloud dell'ente e non è esportabile in `.pfx`: in CI si usa il servizio di firma cloud dell'ente scelto.
3. **Azure Artifact Signing** (ex Trusted Signing). Secondo le risposte del supporto Microsoft la verifica come **privato** è aperta solo a USA e Canada; come **organizzazione** anche all'Unione Europea. Utilizzabile quindi solo con una società/partita IVA che superi la verifica.
4. **Certificato autofirmato** — gratuito e immediato, utile **solo per uso personale**: vedi sotto.

## Attivare la firma con un file `.pfx`
Vale per un certificato autofirmato o per qualunque certificato disponibile come `.pfx`.

1. Nel repository GitHub: *Settings → Secrets and variables → Actions → New repository secret*, due segreti:
   - `WINDOWS_SIGN_PFX_BASE64` — il file `.pfx` codificato in base64;
   - `WINDOWS_SIGN_PFX_PASSWORD` — la sua password.
2. Avvia la build (*Actions → ci → Run workflow*, oppure un push). Nel log del job `windows-bundle` compare `signing: OK …` per ogni file.
3. Pubblica la release come sempre: le note riportano «Eseguibili FIRMATI digitalmente».

Il certificato non entra mai nel repository né nel pacchetto: la build lo toglie dall'ambiente prima di avviare npm, pip, i test e lo smoke test, e lo passa solo a `signtool`.

### Creare un certificato autofirmato (uso personale)
In PowerShell sul tuo PC (sostituisci la password):
```powershell
$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Race Engineer AI (autofirmato)" -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(3)
$pw = ConvertTo-SecureString -String "SCEGLI-UNA-PASSWORD" -Force -AsPlainText
Export-PfxCertificate -Cert $c -FilePath "$env:USERPROFILE\reai-firma.pfx" -Password $pw
Export-Certificate -Cert $c -FilePath "$env:USERPROFILE\reai-firma.cer"
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\reai-firma.pfx")) | Set-Clipboard
```
L'ultima riga copia negli appunti il valore da incollare in `WINDOWS_SIGN_PFX_BASE64`. Il file `.pfx` contiene la chiave privata: conservalo in un posto sicuro e non condividerlo.

Perché Windows consideri valida la firma **su un PC**, su quel PC va installato `reai-firma.cer` (doppio clic → *Installa certificato* → *Utente corrente* → archivio *Autorità di certificazione radice attendibili*, e di nuovo in *Autori attendibili*). Fallo solo su PC tuoi: chi installa quel certificato si fida di tutto ciò che è firmato con esso.

## Verificare una firma
```powershell
Get-AuthenticodeSignature .\RaceEngineerAI.exe | Format-List Status, SignerCertificate, TimeStamperCertificate
```
`Status: Valid` = firmato e attendibile su questo PC. `NotSigned` = non firmato. `UnknownError` con un `SignerCertificate` = firmato con un certificato che questo PC non considera attendibile (autofirmato non installato).

## Come viene provata la pipeline
`scripts/test_signing_windows.py` gira a ogni build su Windows: crea un certificato **usa e getta**, firma una **copia** della CLI, controlla che Windows veda la firma e che l'exe firmato parta ancora, poi costruisce un piccolo installer attraverso lo stesso aggancio usato dall'installer vero e controlla che installer e disinstallatore risultino firmati. Nulla di ciò che viene distribuito è toccato dal certificato di prova.
