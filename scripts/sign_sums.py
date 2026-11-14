"""Signs SHA256SUMS.txt -> SHA256SUMS.txt.sig (base64 of the raw 64-byte Ed25519 signature). Used by release.yml.

  python scripts/sign_sums.py <SHA256SUMS.txt> <private_key.pem>
"""
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

sums, pem = Path(sys.argv[1]), Path(sys.argv[2])
with tempfile.TemporaryDirectory() as d:
    raw = Path(d) / "sig.bin"
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(pem), "-rawin", "-in", str(sums), "-out", str(raw)], check=True)
    sig = raw.read_bytes()
assert len(sig) == 64
Path(str(sums) + ".sig").write_text(base64.b64encode(sig).decode() + "\n")
print("firmato:", str(sums) + ".sig")
