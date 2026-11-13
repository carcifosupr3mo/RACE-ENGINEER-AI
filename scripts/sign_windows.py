"""Authenticode signing of the Windows executables (signtool). Usage: python scripts/sign_windows.py FILE [FILE...]

The certificate comes from the environment (GitHub Actions secrets), never from the repository:
  WINDOWS_SIGN_PFX_BASE64      the code-signing certificate with its private key (.pfx), base64 encoded
  WINDOWS_SIGN_PFX_PASSWORD    its password
  WINDOWS_SIGN_TIMESTAMP_URLS  optional, comma separated RFC 3161 servers (default: three public ones, tried in order)
Without WINDOWS_SIGN_PFX_BASE64 nothing is signed and the build goes on UNSIGNED (said out loud, never silently).
A file that was asked to be signed and is not correctly signed afterwards fails the build.
"""
from __future__ import annotations

import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_PFX, ENV_PASSWORD, ENV_TIMESTAMP = "WINDOWS_SIGN_PFX_BASE64", "WINDOWS_SIGN_PFX_PASSWORD", "WINDOWS_SIGN_TIMESTAMP_URLS"
TIMESTAMP_URLS = ["http://timestamp.digicert.com", "http://timestamp.sectigo.com", "http://timestamp.globalsign.com/tsa/r6advanced1"]
DESCRIPTION = "Race Engineer AI"


def take_credentials(env=os.environ) -> dict:
    """Remove the signing variables from ``env`` and return them: child processes (npm, pip, tests) must never inherit them."""
    return {k: env.pop(k) for k in (ENV_PFX, ENV_PASSWORD, ENV_TIMESTAMP) if env.get(k)}


def configured(creds: dict) -> bool:
    return bool(creds.get(ENV_PFX))


def find_signtool() -> str:
    found = shutil.which("signtool")
    if found:
        return found
    kits = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe"),
                  key=lambda p: [int(x) if x.isdigit() else 0 for x in Path(p).parts[-3].split(".")])
    if not kits:
        raise RuntimeError("signtool.exe not found (Windows SDK missing)")
    return kits[-1]


def sign_command(signtool: str, pfx: str, password: str, timestamp_url: str, files: list[str]) -> list[str]:
    return [signtool, "sign", "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256", "/d", DESCRIPTION, "/f", pfx, "/p", password, *files]


def ps_env(**extra) -> dict:
    """Environment for a Windows PowerShell 5.1 child. When the build is started from PowerShell 7 the inherited PSModulePath points at
    PowerShell 7 modules, which 5.1 cannot load (no Cert: drive, no ConvertTo-SecureString): drop it so 5.1 uses its own."""
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    env.update(extra)
    return env


def signature_status(path: str) -> tuple[str, str]:
    """(status, signer subject) as Windows reports them, e.g. ('Valid', 'CN=...') or ('NotSigned', '')."""
    ps = "$s = Get-AuthenticodeSignature -LiteralPath $env:RE_SIGN_CHECK; $s.Status; if ($s.SignerCertificate) { $s.SignerCertificate.Subject }"
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=120,
                         env=ps_env(RE_SIGN_CHECK=path)).stdout.split("\n")
    lines = [ln.strip() for ln in out if ln.strip()]
    return (lines[0] if lines else "Unknown"), (lines[1] if len(lines) > 1 else "")


def sign(files: list[str | Path], creds: dict) -> bool:
    """Sign and check every file. Returns False (and signs nothing) when no certificate is configured."""
    files = [str(f) for f in files]
    if not configured(creds):
        print("signing: SKIPPED - no certificate configured (" + ENV_PFX + " is empty): these files stay UNSIGNED:", *files, sep="\n  ")
        return False
    if sys.platform != "win32":
        raise RuntimeError("Authenticode signing needs Windows (signtool)")
    signtool = find_signtool()
    urls = [u.strip() for u in creds.get(ENV_TIMESTAMP, "").split(",") if u.strip()] or TIMESTAMP_URLS
    fd, pfx = tempfile.mkstemp(suffix=".pfx")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(creds[ENV_PFX]))
        last = None
        for url in urls:                   # a public timestamp server can be down: try the next one
            last = subprocess.run(sign_command(signtool, pfx, creds.get(ENV_PASSWORD, ""), url, files), capture_output=True, text=True)
            if last.returncode == 0:
                break
            print(f"signing: timestamp server {url} failed (signtool exit {last.returncode}), trying the next one")
        if last is None or last.returncode != 0:      # the command line holds the password: print signtool's output, never the command
            raise RuntimeError("signtool failed:\n" + (last.stdout + last.stderr if last else "no timestamp server configured"))
    finally:
        os.unlink(pfx)
    for f in files:
        status, subject = signature_status(f)
        if status in ("NotSigned", "HashMismatch", "Unknown") or not subject:
            raise RuntimeError(f"{f}: signature check failed after signing (status {status})")
        note = "" if status == "Valid" else "  <- this PC does not trust the certificate (self-signed or test certificate?)"
        print(f"signing: OK {Path(f).name}: status {status}, signer {subject}{note}")
    return True


if __name__ == "__main__":
    sign(sys.argv[1:], take_credentials())      # any failure raises -> non-zero exit (Inno Setup then stops the installer build)
