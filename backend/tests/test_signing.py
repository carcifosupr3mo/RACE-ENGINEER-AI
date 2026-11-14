import sys
from pathlib import Path
import base64
import shutil
import subprocess

import pytest

from race_engineer.updater import signing

# RFC 8032 section 7.1 test vectors (public key, message, signature)
V = [
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


@pytest.mark.parametrize("pub,msg,sig", V)
def test_rfc8032_vectors(pub, msg, sig):
    assert signing.verify(bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig))


def test_rejects_tampering():
    pub, msg, sig = V[1][0], bytes.fromhex(V[1][1]), bytes.fromhex(V[1][2])
    assert not signing.verify(bytes.fromhex(pub), msg + b"x", sig)
    bad = bytearray(sig); bad[10] ^= 1
    assert not signing.verify(bytes.fromhex(pub), msg, bytes(bad))
    assert not signing.verify(bytes.fromhex(pub), msg, sig[:63])
    assert not signing.verify(b"\0" * 31, msg, sig)
    assert not signing.verify(bytes.fromhex(pub), msg, sig[:32] + b"\xff" * 32)      # s >= L


def test_check_sums_requires_key_and_signature():
    assert not signing.check_sums("x", None, "aa" * 32)
    assert not signing.check_sums("x", "AAAA", "")
    assert not signing.check_sums("x", "not base64!!", "aa" * 32)


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_openssl_signature_roundtrip(tmp_path):
    pem = tmp_path / "k.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(pem)], check=True)
    pub = subprocess.run(["openssl", "pkey", "-in", str(pem), "-pubout", "-outform", "DER"], check=True, capture_output=True).stdout[-32:].hex()
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text("a" * 64 + "  RaceEngineerAI-win32.zip\n")
    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "sign_sums.py"), str(sums), str(pem)], check=True)
    sig = (tmp_path / "SHA256SUMS.txt.sig").read_text()
    assert signing.check_sums(sums.read_text(), sig, pub)
    assert not signing.check_sums(sums.read_text() + "evil\n", sig, pub)
    other = subprocess.run(["python", "-c", "print('bb'*32)"], capture_output=True, text=True).stdout.strip()
    assert not signing.check_sums(sums.read_text(), sig, other)
