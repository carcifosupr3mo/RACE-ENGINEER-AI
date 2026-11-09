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
archive = shutil.make_archive(str(root / "dist" / f"RaceEngineerAI-{sys.platform}"), "zip", out)
print("bundle:", out, "\nzip:", archive)
