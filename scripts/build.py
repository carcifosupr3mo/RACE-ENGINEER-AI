"""Release build: frontend -> tests -> PyInstaller bundle -> zip. Usage: python scripts/build.py [--skip-tests]

Produces dist/RaceEngineerAI/ and dist/RaceEngineerAI-<platform>.zip. A Windows .exe can ONLY be produced by running this on Windows.
"""
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent


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
for bat in (root / "scripts" / "windows").glob("*.bat"):          # verification tools next to the exe (used on the Windows PC)
    shutil.copy2(bat, out / bat.name)
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
    import os
    sys.path.insert(0, str(root / "backend"))
    from race_engineer import __version__
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    subprocess.run([iscc, str(root / "packaging" / "installer.iss")], check=True, env={**os.environ, "RE_VERSION": __version__})
write_checksums()
