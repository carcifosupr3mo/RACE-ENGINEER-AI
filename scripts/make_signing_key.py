"""Generates the release signing key pair with OpenSSL (no extra dependency). Run ONCE on the maintainer's machine.

  python scripts/make_signing_key.py [outdir]

Prints the PUBLIC key (64 hex) to paste into backend/race_engineer/updater/signing.py (PUBLIC_KEY_HEX), and writes the PRIVATE key
PEM to outdir/release_signing_key.pem. The private key goes ONLY into the GitHub secret RELEASE_SIGNING_KEY_PEM and a private backup;
never commit it. Losing it means shipping a new app version with a new public key by hand (installed apps cannot trust a new key by themselves).
"""
import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
pem = out / "release_signing_key.pem"
if pem.exists():
    raise SystemExit(f"{pem} esiste già: non lo sovrascrivo.")
subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(pem)], check=True)
der = subprocess.run(["openssl", "pkey", "-in", str(pem), "-pubout", "-outform", "DER"], check=True, capture_output=True).stdout
print("PUBLIC_KEY_HEX =", der[-32:].hex())
print("Chiave privata:", pem, "(segreto: NON committare)")
