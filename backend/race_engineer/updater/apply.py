"""Replaces the installed program with a verified, already extracted new version. Runs OUTSIDE the app (the app is closed).

Standard library only: in the Windows build this file is the whole of ``RaceEngineerUpdater.exe``, a separate small program that the
app copies to a temporary folder and starts just before it quits (a running program cannot overwrite itself on Windows).

Steps (every one is logged to ``update.log``; the result is written to ``update_result.json`` for the app to show at next start):
 1. wait for the app to exit;
 2. BACKUP: the installed folder is renamed to ``<folder>.old-<version>`` (atomic, instant, nothing is copied or lost);
 3. the new folder is moved into its place; anything the user had added to the old folder is carried over (never overwritten);
 4. the new program is started and watched for ``--watch`` seconds: if it crashes at once, ROLLBACK;
 5. on success the backup is deleted. On ANY error before that, the old folder is put back and the old program is started again.
User data (database, sessions, profiles, settings) lives in the user's data folder, not here, and is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class Log:
    def __init__(self, path: Path | None):
        self.path = path

    def __call__(self, msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":                      # pragma: no cover  (Windows only)
        # process list only (no process handle is ever opened: same rule as the rest of the app); hidden window
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True, timeout=15,
                                 creationflags=0x08000000).stdout
        except (OSError, subprocess.SubprocessError):
            return True
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return _is_running_posix(pid)      # a zombie (exited, not yet reaped) counts as exited


def _is_running_posix(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def wait_exit(pid: int, timeout: float) -> bool:
    t0 = time.time()
    while pid_alive(pid):
        if time.time() - t0 > timeout:
            return False
        time.sleep(0.3)
    return True


def retry(fn, what: str, log: Log, seconds: float = 40.0):
    """Windows keeps files locked for a moment after a program exits (antivirus, indexer): try again for a while."""
    t0 = time.time()
    while True:
        try:
            return fn()
        except OSError as e:
            if time.time() - t0 > seconds:
                raise
            log(f"{what}: {e} - riprovo")
            time.sleep(1.0)


def swap(app: Path, staging: Path, backup: Path, log: Log) -> None:
    """app -> backup, staging -> app, then carry over what only the user's old folder contained. Raises on failure with the old folder restored."""
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    retry(lambda: os.replace(app, backup), "rinomino la cartella installata", log)
    log(f"backup: {app} -> {backup}")
    try:
        try:
            os.replace(staging, app)
        except OSError:                                   # another drive: copy instead of rename
            shutil.copytree(staging, app)
        log("nuova versione al suo posto")
        for item in backup.iterdir():                     # user-added files/folders (e.g. a data folder kept inside the install folder)
            target = app / item.name
            if not target.exists():                       # COPY (not move): if a rollback is needed the backup must still be whole
                shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
                log(f"conservato: {item.name}")
    except BaseException:
        if app.exists():
            shutil.rmtree(app, ignore_errors=True)
        os.replace(backup, app)
        log("ERRORE durante la sostituzione: versione precedente ripristinata")
        raise


def rollback(app: Path, backup: Path, log: Log) -> None:
    if not backup.exists():
        raise RuntimeError("backup mancante")
    if app.exists():
        retry(lambda: shutil.rmtree(app), "rimuovo la versione nuova", log)
    os.replace(backup, app)
    log("rollback eseguito: versione precedente ripristinata")


def start(exe: Path, args: list[str]) -> subprocess.Popen:
    kw = {}
    if sys.platform == "win32":                           # pragma: no cover
        kw["creationflags"] = 0x00000008 | 0x08000000     # DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    return subprocess.Popen([str(exe), *args], cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def run(*, app: Path, staging: Path, exe_name: str, pid: int, version_from: str, version_to: str, work: Path,
        app_args: list[str], watch_s: float = 20.0, wait_s: float = 90.0) -> dict:
    log = Log(work / "update.log")
    result = {"ok": False, "from": version_from, "to": version_to, "rolled_back": False, "error": None, "t": time.time()}
    backup = app.with_name(f"{app.name}.old-{version_from}")
    log(f"=== aggiornamento {version_from} -> {version_to}; app={app}")

    def finish() -> dict:
        try:
            (work / "update_result.json").write_text(json.dumps(result), encoding="utf-8")
        except OSError as e:
            log(f"impossibile scrivere il risultato: {e}")
        return result

    if not wait_exit(pid, wait_s):
        result["error"] = "L'app non si è chiusa in tempo: l'aggiornamento non è stato installato."
        log(result["error"])
        start(app / exe_name, app_args)
        return finish()
    if not (staging / exe_name).is_file():
        result["error"] = "Il pacchetto scaricato non contiene il programma: nessuna modifica fatta."
        log(result["error"])
        start(app / exe_name, app_args)
        return finish()
    try:
        swap(app, staging, backup, log)
    except Exception as e:                                # old folder already restored by swap()
        result.update(error=f"Non è stato possibile sostituire i file ({e}). È stata mantenuta la versione precedente.", rolled_back=True)
        log(f"fallito: {e!r}")
        start(app / exe_name, app_args)
        return finish()
    try:
        proc = start(app / exe_name, app_args)
        t0 = time.time()
        while time.time() - t0 < watch_s:
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    raise RuntimeError(f"la nuova versione si è chiusa subito (codice {rc})")
                break
            time.sleep(0.5)
        result["ok"] = True
        log("nuova versione avviata correttamente")
    except Exception as e:
        log(f"la nuova versione non parte: {e!r}")
        try:
            rollback(app, backup, log)
            result.update(rolled_back=True, error="La nuova versione non si è avviata: è stata ripristinata la versione precedente.")
            start(app / exe_name, app_args)
        except Exception as e2:
            result.update(rolled_back=False, error=f"Aggiornamento fallito e ripristino non riuscito ({e2}). La versione precedente è nella cartella {backup.name}.")
            log(f"ROLLBACK FALLITO: {e2!r}")
        return finish()
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(staging.parent, ignore_errors=True)
    return finish()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="RaceEngineerUpdater")
    ap.add_argument("--app", required=True)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--from", dest="vfrom", required=True)
    ap.add_argument("--to", dest="vto", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--watch", type=float, default=20.0)
    ap.add_argument("--wait", type=float, default=90.0)
    ap.add_argument("app_args", nargs="*")
    a = ap.parse_args(argv)
    r = run(app=Path(a.app), staging=Path(a.staging), exe_name=a.exe, pid=a.pid, version_from=a.vfrom, version_to=a.vto, work=Path(a.work),
            app_args=a.app_args, watch_s=a.watch, wait_s=a.wait)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
