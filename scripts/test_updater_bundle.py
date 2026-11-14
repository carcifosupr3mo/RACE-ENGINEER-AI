"""Real-machine test of the FROZEN updater program (RaceEngineerUpdater.exe on Windows): replace a fake installation, then force a rollback.

    python scripts/test_updater_bundle.py dist/RaceEngineerAI      # uses <bundle>/RaceEngineerUpdater[.exe]
    python scripts/test_updater_bundle.py                           # from sources: python -m race_engineer.updater.apply

Run in CI on Windows because file locking and renaming differ there. It waits for a REAL running process (the "old app") to exit first.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
WIN = sys.platform == "win32"
APP_EXE = "app.cmd" if WIN else "app.sh"
bundle = Path(sys.argv[1]) if len(sys.argv) > 1 else None
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" - {detail}"), flush=True)
    if not ok:
        fails.append(name)


def make_tree(folder: Path, version: str, body: str):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / APP_EXE
    exe.write_text(f"@echo off\r\n{body}\r\n" if WIN else f"#!/bin/sh\n{body}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    (folder / "_internal").mkdir(exist_ok=True)
    (folder / "_internal" / "version.txt").write_text(version)


def updater_cmd() -> list[str]:
    if bundle:
        exe = bundle / ("RaceEngineerUpdater.exe" if WIN else "RaceEngineerUpdater")
        if not exe.is_file():
            raise SystemExit(f"missing {exe}")
        tmp = Path(tempfile.mkdtemp(prefix="upd-copy-")) / exe.name      # like the app does: run a COPY, never the file inside the install folder
        tmp.write_bytes(exe.read_bytes()); tmp.chmod(0o755)
        return [str(tmp)]
    return [sys.executable, "-m", "race_engineer.updater.apply"]


def run_case(new_body: str):
    base = Path(tempfile.mkdtemp(prefix="upd-test-"))
    app = base / "RaceEngineerAI"
    make_tree(app, "old", "exit /b 0" if WIN else "exit 0")
    (app / "mio_file.txt").write_text("dati dell'utente")
    staging = base / "up" / "staging"
    make_tree(staging, "new", new_body)
    work = base / "work"; work.mkdir()
    old_app = subprocess.Popen(["cmd", "/c", "ping -n 4 127.0.0.1 >nul"] if WIN else ["sleep", "2"])      # the "running app" the updater must wait for
    t0 = time.time()
    env = {**os.environ, "PYTHONPATH": str(root / "backend")}
    r = subprocess.run([*updater_cmd(), "--app", str(app), "--staging", str(staging), "--exe", APP_EXE, "--pid", str(old_app.pid), "--from", "0.6.7", "--to", "0.7.0",
                        "--work", str(work), "--watch", "5", "--wait", "60", "--"], env=env, cwd=str(base), capture_output=True, text=True, timeout=180)
    waited = time.time() - t0
    if not (work / "update_result.json").exists():
        print(r.stdout, r.stderr)
    return app, work, r, waited, old_app


app, work, r, waited, old = run_case("exit /b 0" if WIN else "exit 0")
res = json.loads((work / "update_result.json").read_text())
check("updater waited for the old process to exit", old.poll() is not None and waited >= 1.5, f"{waited:.1f}s")
check("success: new files in place", (app / "_internal" / "version.txt").read_text() == "new" and res["ok"], str(res))
check("success: user file kept", (app / "mio_file.txt").read_text() == "dati dell'utente")
check("success: backup removed", not list(app.parent.glob("RaceEngineerAI.old-*")))

app, work, r, waited, old = run_case("exit /b 3" if WIN else "exit 3")
res = json.loads((work / "update_result.json").read_text())
check("rollback: previous version restored when the new one crashes", (app / "_internal" / "version.txt").read_text() == "old" and res["rolled_back"] and not res["ok"], str(res))
check("rollback: user file still there", (app / "mio_file.txt").exists())
print("log:\n" + (work / "update.log").read_text())
raise SystemExit(1 if fails else 0)
