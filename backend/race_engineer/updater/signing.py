"""Ed25519 signature of ``SHA256SUMS.txt`` (pure Python, standard library only, verification side).

WHY: SHA-256 from the same release only proves the download is not corrupted. Whoever can edit the release (stolen GitHub
account/token) can replace the package AND its checksums. A signature made with a PRIVATE key that never leaves the
maintainer's secret store (a CI secret) closes that hole: the app embeds only the PUBLIC key.

ACTIVATION: ``PUBLIC_KEY_HEX`` is empty until the maintainer generates a key pair (``scripts/make_signing_key.py``) and pastes the public
key here. While it is empty the app behaves as before (SHA-256 only) and the Updates screen says the release is not signed. Once a key
is embedded, a release without a valid ``SHA256SUMS.txt.sig`` is REFUSED. Verification follows RFC 8032 section 5.1.7 (tested with its vectors
and against OpenSSL).
"""
from __future__ import annotations

import base64
import binascii
import hashlib

PUBLIC_KEY_HEX = ""          # 64 hex characters; set by the maintainer (see docs/RELEASE.md)
SIG_NAME = "SHA256SUMS.txt.sig"

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, -1, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)
_B = (15112221349535400772501151409588531511454012693041857206046113283949847762202,
      46316835694926478169428394003475163141307993866256225615783033603165251855960, 1, 0)
_B = (_B[0], _B[1], 1, _B[0] * _B[1] % _P)


def _add(p, q):
    a, b = (p[1] - p[0]) * (q[1] - q[0]) % _P, (p[1] + p[0]) * (q[1] + q[0]) % _P
    c, d = 2 * p[3] * q[3] * _D % _P, 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    r = (0, 1, 1, 0)
    while s:
        if s & 1:
            r = _add(r, p)
        p = _add(p, p)
        s >>= 1
    return r


def _decode(b: bytes):
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, -1, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _eq(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True only for a valid Ed25519 signature; never raises on malformed input."""
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        a, r = _decode(public_key), _decode(signature[:32])
        s = int.from_bytes(signature[32:], "little")
        if a is None or r is None or s >= _L:
            return False
        k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _L
        return _eq(_mul(s, _B), _add(r, _mul(k, a)))
    except (ValueError, ArithmeticError):
        return False


def enforced() -> bool:
    return bool(PUBLIC_KEY_HEX.strip())


def check_sums(sums_text: str, sig_text: str | None, public_key_hex: str | None = None) -> bool:
    """Is ``sig_text`` (base64 or hex of the 64 raw bytes) a valid signature of ``sums_text`` for the embedded key?"""
    key = (PUBLIC_KEY_HEX if public_key_hex is None else public_key_hex).strip()
    if not key or sig_text is None:
        return False
    try:
        pub = binascii.unhexlify(key)
        raw = sig_text.strip()
        sig = binascii.unhexlify(raw) if len(raw) == 128 else base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return False
    return verify(pub, sums_text.encode("utf-8"), sig)
