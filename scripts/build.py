"""Release build: frontend -> tests -> PyInstaller bundle -> zip. Usage: python scripts/build.py [--skip-tests]

Produces dist/RaceEngineerAI/ and dist/RaceEngineerAI-<platform>.zip. A Windows .exe can ONLY be produced by running this on Windows.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import sign_windows

SIGN = sign_windows.take_credentials()      # out of os.environ from here on: npm, pip, tests and the smoke run never see the certificate

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "backend"))
from race_engineer import __version__  # noqa: E402  single source of the version (build_info.json, installer)


def run(cmd, cwd=root):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == "win32" and cmd[0] == "npm"))


if (root / "frontend" / "package.json").exists():
    run(["npm", "ci"], root / "frontend")
    run(["npm", "run", "build"], root / "frontend")
    run(["npm", "test"], root / "frontend")
if "--skip-tests" not in sys.argv:
    run([sys.executable, "-m", "pytest", "tests"], root / "backend")
run([sys.executable, "-m", "PyInstaller", "packaging/race_engineer.spec", "--noconfirm", "--distpath", "dist", "--workpath", "build"])
out = root / "dist" / "RaceEngineerAI"
_upd = next((f for f in (root / "dist").glob("RaceEngineerUpdater*") if f.is_file()), None)      # separate updater program (see packaging/race_engineer.spec)
if _upd is None:
    raise SystemExit("RaceEngineerUpdater was not built: in-app updates would not work")
shutil.copy2(_upd, out / _upd.name)
signed = sign_windows.sign([e for e in (out / "RaceEngineerAI.exe", out / "race-engineer-cli.exe", out / "RaceEngineerUpdater.exe") if e.exists()], SIGN)   # before smoke/zip/installer: what is tested is what ships
for bat in [*(root / "scripts" / "windows").glob("*.bat"), *(root / "scripts" / "windows").glob("*.ps1"), *(root / "scripts" / "windows").glob("hud_annotazioni_*.json")]:          # verification tools next to the exe (used on the Windows PC)
    shutil.copy2(bat, out / bat.name)
(out / "docs").mkdir(exist_ok=True)
for d in ("README.md", "docs/VALIDATION.md", "docs/INSTALLATION.md", "docs/AI-PROVIDERS.md", "docs/LMU-INTEGRATION.md", "docs/WINDOWS-PROCEDURA.md", "docs/CODE-SIGNING.md", "docs/UPDATES.md"):
    shutil.copy2(root / d, out / "docs" / Path(d).name)
shutil.copy2(root / "packaging" / "icon.ico", out / "icon.ico")
def _commit():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None
import json, time
(out / "build_info.json").write_text(json.dumps({"commit": _commit(), "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                  "version": __version__, "signed": signed}), encoding="utf-8")


def secret_scan(folder: Path) -> list[str]:
    """Fail the build if any text file in the bundle looks like it contains an API key or a personal path."""
    import re
    pat = re.compile(rb"(nvapi-[A-Za-z0-9_\-]{20,}|gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_\-]{30,}|ghp_[A-Za-z0-9]{30,}|xox[bp]-[A-Za-z0-9-]{20,})")
    hits = []
    for f in folder.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".py", ".json", ".txt", ".md", ".bat", ".ps1", ".js", ".html", ".cfg", ".toml", ".yml", ".sqlite"):
            if pat.search(f.read_bytes()):
                hits.append(str(f.relative_to(folder)))
    return hits


bad = secret_scan(out)
print("secret scan:", "CLEAN" if not bad else bad)
if bad:
    raise SystemExit("possible secrets in bundle: " + ", ".join(bad))
if "--smoke" in sys.argv:                                          # a package that fails its smoke test is never archived
    run([sys.executable, "scripts/smoke_bundle.py", str(out)])
archive = shutil.make_archive(str(root / "dist" / f"RaceEngineerAI-{sys.platform}"), "zip", out)
print("bundle:", out, "\nzip:", archive)


def sha256(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums():
    files = [Path(archive), *sorted((root / "dist").glob("RaceEngineerAI-Setup-*.exe"))]
    (root / "dist" / "SHA256SUMS.txt").write_text("".join(f"{sha256(f)}  {f.name}\n" for f in files), encoding="utf-8")
    print((root / "dist" / "SHA256SUMS.txt").read_text())


if "--installer" in sys.argv and sys.platform == "win32":
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    cmd = [iscc]
    if signed:                              # Inno Setup signs the installer AND the uninstaller it embeds, through the same script ($q = quote, $f = file)
        cmd += ["/DSIGN", f"/Sresign=$q{sys.executable}$q $q{root / 'scripts' / 'sign_windows.py'}$q $f"]
    subprocess.run([*cmd, str(root / "packaging" / "installer.iss")], check=True, env={**os.environ, **SIGN, "RE_VERSION": __version__})
    if signed:
        for setup in (root / "dist").glob("RaceEngineerAI-Setup-*.exe"):
            status, subject = sign_windows.signature_status(str(setup))
            if status in ("NotSigned", "HashMismatch", "Unknown"):
                raise SystemExit(f"{setup.name}: installer is not signed (status {status})")
            print(f"signing: OK {setup.name}: status {status}, signer {subject}")
(root / "dist" / "SIGNING.txt").write_text("Eseguibili FIRMATI digitalmente (Authenticode).\n" if signed else
                                           "Eseguibili NON firmati: Windows SmartScreen puo mostrare un avviso. Verifica l'hash in SHA256SUMS.txt.\n", encoding="utf-8")
write_checksums()
