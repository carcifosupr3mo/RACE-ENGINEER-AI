"""CI proof (Windows only) that the signing pipeline works, WITHOUT a real certificate and WITHOUT touching what ships.

Uses a throw-away self-signed certificate created on the spot (never trusted, never stored, never used for the release files):
  1. signs a COPY of the frozen CLI exe, checks Windows sees the signature and that the signed exe still runs;
  2. builds a tiny Inno Setup installer through the same SignTool hook the real installer uses, installs it and checks that
     both the installer and the uninstaller it embeds are signed.
Usage: python scripts/test_signing_windows.py dist/RaceEngineerAI
"""
import base64
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import sign_windows

SUBJECT = "Race Engineer AI CI TEST (untrusted)"
results = []


def rec(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def throwaway_credentials(tmp: Path) -> dict:
    password, pfx = secrets.token_urlsafe(18), tmp / "test.pfx"
    ps = ("$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject ('CN=' + $env:RE_SUBJ) -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddDays(2);"
          "Export-PfxCertificate -Cert $c -FilePath $env:RE_PFX -Password (ConvertTo-SecureString -String $env:RE_PW -Force -AsPlainText) | Out-Null;"
          "Remove-Item ('Cert:\\CurrentUser\\My\\' + $c.Thumbprint)")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True,
                   env=sign_windows.ps_env(RE_SUBJ=SUBJECT, RE_PFX=str(pfx), RE_PW=password))
    return {sign_windows.ENV_PFX: base64.b64encode(pfx.read_bytes()).decode(), sign_windows.ENV_PASSWORD: password}


def signed_by_test_cert(path) -> tuple[bool, str]:
    status, subject = sign_windows.signature_status(str(path))
    return status not in ("NotSigned", "HashMismatch", "Unknown") and SUBJECT in subject, f"{status} / {subject}"


def main() -> int:
    bundle = Path(sys.argv[1]).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="reai_signtest_"))
    copy = bundle / "race-engineer-cli-signtest.exe"          # next to the real one: a frozen exe needs its _internal folder to run
    try:
        creds = throwaway_credentials(tmp)
        rec("no certificate configured -> nothing signed, build continues", sign_windows.sign([bundle / "race-engineer-cli.exe"], {}) is False)
        shutil.copy2(bundle / "race-engineer-cli.exe", copy)
        rec("unsigned copy reads as NotSigned or carries another signer", SUBJECT not in sign_windows.signature_status(str(copy))[1])
        rec("sign() signs and verifies the copy", sign_windows.sign([copy], creds) is True)
        rec("Windows reports the signature on the copy", *signed_by_test_cert(copy))
        r = subprocess.run([str(copy), "layout"], capture_output=True, text=True, timeout=120)
        rec("the signed exe still runs", r.returncode == 0, f"exit {r.returncode} {r.stderr[-200:]}")

        (tmp / "payload.txt").write_text("signing test\n", encoding="utf-8")
        (tmp / "t.iss").write_text(
            "[Setup]\nAppId={{0B6C0F0E-1111-4222-8333-5A5A5A5A5A5A}\nAppName=REAI signing test\nAppVersion=1.0\nDefaultDirName={localappdata}\\reai_signtest\n"
            "PrivilegesRequired=lowest\nOutputDir=.\nOutputBaseFilename=signtest-setup\nCreateAppDir=yes\nDisableProgramGroupPage=yes\n"
            "SignTool=resign\nSignedUninstaller=yes\n[Files]\nSource: \"payload.txt\"; DestDir: \"{app}\"\n", encoding="utf-8")
        iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        hook = f"/Sresign=$q{sys.executable}$q $q{Path(__file__).with_name('sign_windows.py')}$q $f"       # same hook as scripts/build.py
        r = subprocess.run([iscc, hook, str(tmp / "t.iss")], capture_output=True, text=True, env={**os.environ, **creds})
        rec("Inno Setup builds through the SignTool hook", r.returncode == 0, (r.stdout + r.stderr)[-400:] if r.returncode else "")
        setup = tmp / "signtest-setup.exe"
        rec("installer is signed", *(signed_by_test_cert(setup) if setup.exists() else (False, "no installer produced")))
        target = tmp / "installed"
        if setup.exists():
            subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={target}"], timeout=300)
            unins = target / "unins000.exe"
            rec("embedded uninstaller is signed", *(signed_by_test_cert(unins) if unins.exists() else (False, "no uninstaller")))
            if unins.exists():
                subprocess.run([str(unins), "/VERYSILENT"], timeout=300)
        rec("the files that ship were not signed by the test certificate", all(
            SUBJECT not in sign_windows.signature_status(str(e))[1] for e in (bundle / "race-engineer-cli.exe", bundle / "RaceEngineerAI.exe") if e.exists()))
    finally:
        copy.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed" + (f"; FAILED: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
