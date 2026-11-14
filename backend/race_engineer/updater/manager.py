"""The update state machine used by the API/UI. One instance per app; all state is read through ``status()``.

States: idle · checking · up_to_date · offline · available · downloading · verifying · installing · restarting · error
Progress numbers are REAL (bytes written, bytes hashed, files extracted), never simulated.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import apply as apply_mod
from . import signing, source
from .source import PACKAGE_NAME, SUMS_NAME, Policy, Release, UpdateError
from .versions import fmt, parse_loose

RELEASES_PAGE = f"https://github.com/{source.REPO}/releases"
EXE_NAME = {"win32": "RaceEngineerAI.exe"}
UPDATER_EXE = "RaceEngineerUpdater.exe"
AUTO_KEY = "updates.auto"


def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


class UpdateManager:
    def __init__(self, catalog, current_version: str, work_dir: Path, *, policy: Policy | None = None, api_base: str = source.API,
                 platform: str | None = None, install_dir: Path | None = None, frozen: bool | None = None,
                 launcher: Callable[[dict], None] | None = None, quit_cb: Callable[[], None] | None = None,
                 app_args: list[str] | None = None, timeout: float = 8.0, retries: int = 3):
        self.catalog = catalog
        self.current = current_version
        self.work = Path(work_dir)
        self.policy = policy or Policy()
        self.api_base = api_base
        self.platform = platform or sys.platform
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.install_dir = Path(install_dir) if install_dir else Path(sys.executable).resolve().parent
        self.launcher = launcher or self._launch_helper
        self.quit_cb = quit_cb
        self.app_args = [a for a in (app_args if app_args is not None else sys.argv[1:]) if a != "--quit"]
        self.timeout, self.retries = timeout, retries
        self.lock = threading.RLock()
        self.release: Release | None = None
        self.blocked: str | None = None           # why this release cannot be installed from inside the app (incompatible / no package)
        self.dismissed = False                    # "Salta per ora": no popup again during this run
        self.job: threading.Thread | None = None
        self.s: dict = {"state": "idle", "progress": None, "message": "", "error": None, "error_code": None,
                        "bytes": 0, "total": 0, "step": 0}

    # -------------------------------------------------------------------- settings
    @property
    def auto(self) -> bool:
        return bool(self.catalog.get_setting(AUTO_KEY, False))      # OFF until the user turns it on

    def set_auto(self, on: bool) -> None:
        self.catalog.put_setting(AUTO_KEY, bool(on))

    # -------------------------------------------------------------------- status
    def _set(self, **kw) -> None:
        with self.lock:
            self.s.update(kw)

    def can_install_here(self) -> tuple[bool, str]:
        if self.platform not in PACKAGE_NAME:
            return False, "Per questo sistema l'aggiornamento automatico non è disponibile: scarica la nuova versione dalla pagina delle release."
        if not self.frozen:
            return False, "Questa copia gira dai sorgenti (modalità sviluppo): aggiornala con git o scarica la versione installabile."
        if not (self.install_dir / UPDATER_EXE).is_file():
            return False, "Questa installazione non contiene il programma di aggiornamento: scarica l'ultima versione dalla pagina delle release."
        return True, ""

    def status(self) -> dict:
        with self.lock:
            r = self.release
            ok, why = self.can_install_here()
            out = dict(self.s)
            out.update(current=self.current, auto=self.auto, dismissed=self.dismissed, releases_url=RELEASES_PAGE,
                       latest=r.version_str if r else None, notes=r.notes if r else "", release_url=r.page if r else None,
                       can_install=ok and self.blocked is None, blocked=self.blocked, manual_reason=(why or self.s.get("message", "")) if r and (why or self.blocked) else "", last_result=self._peek_result())
            return out

    # -------------------------------------------------------------------- result of a previous update (written by the helper)
    def _result_path(self) -> Path:
        return self.work / "update_result.json"

    def _peek_result(self) -> dict | None:
        try:
            return json.loads(self._result_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def ack_result(self) -> None:
        try:
            self._result_path().unlink()
        except OSError:
            pass

    # -------------------------------------------------------------------- check
    def check(self) -> dict:
        """Look for a newer STABLE release. Never raises: problems become a state the UI can explain."""
        with self.lock:
            if self.s["state"] in ("checking", "downloading", "verifying", "installing", "restarting"):
                return self.status()
            self._set(state="checking", error=None, error_code=None, message="Controllo se esiste una versione più recente…", progress=None)
        try:
            rel = source.latest_stable(source.fetch_releases(self.policy, self.api_base, self.timeout))
        except UpdateError as e:
            self._set(state="offline" if e.code == "offline" else "error", error=e.message, error_code=e.code, message=e.message)
            return self.status()
        installed = parse_loose(self.current)
        if rel is None or installed is None or rel.version <= installed:
            self.release, self.blocked = None, None
            self._set(state="up_to_date", message="Hai già l'ultima versione.", step=0)
            return self.status()
        self.release = rel
        floor = source.min_update_from(rel.notes)
        if floor and installed < floor:
            self.blocked = "incompatible"
            self._set(state="available", error_code="incompatible", message=f"La versione {rel.version_str} richiede prima la {fmt(floor)}: scaricala dalla pagina delle release.")
            return self.status()
        if PACKAGE_NAME.get(self.platform) not in rel.assets or SUMS_NAME not in rel.assets:
            self.blocked = "no_package"
            self._set(state="available", error_code="no_package", message=f"La versione {rel.version_str} non ha ancora un pacchetto verificabile per questo computer: scaricala dalla pagina delle release.")
            return self.status()
        self.blocked = None
        self._set(state="available", error_code=None, message=f"È disponibile la versione {rel.version_str}.")
        return self.status()

    def check_in_background(self, auto_install: bool = True) -> None:
        def go():
            st = self.check()
            if st["state"] == "available" and auto_install and self.auto and self.installable():
                self.start_install()
        threading.Thread(target=go, name="update-check", daemon=True).start()

    def installable(self) -> bool:
        return self.release is not None and self.blocked is None and self.can_install_here()[0]

    def skip(self) -> dict:
        """«Salta per ora» / «Continua senza aggiornare»: no popup again in this run, and a failed attempt stops blocking the screen."""
        self.dismissed = True
        with self.lock:
            if self.s["state"] == "error" and not (self.job and self.job.is_alive()):
                self._set(state="available" if self.release else "idle", error=None, error_code=None, step=0, progress=None, message="")
        return self.status()

    # -------------------------------------------------------------------- install
    def start_install(self) -> dict:
        with self.lock:
            if not self.installable():
                raise UpdateError(self.blocked or "not_installable", self.can_install_here()[1] or self.s.get("message") or "Aggiornamento non disponibile.")
            if self.job and self.job.is_alive():
                return self.status()
            self._set(state="downloading", progress=0.0, bytes=0, total=0, error=None, error_code=None, step=2, message="Scarico la nuova versione…")
            self.job = threading.Thread(target=self._install, name="update-install", daemon=True)
            self.job.start()
        return self.status()

    def _fail(self, e: UpdateError) -> None:
        self._set(state="error", error=e.message, error_code=e.code, message=e.message, progress=None)

    def _install(self) -> None:
        rel = self.release
        assert rel is not None
        folder = self.work / "update" / rel.version_str
        try:
            self._download_verify_extract(rel, folder)
            self._hand_over(rel, folder)
        except UpdateError as e:
            self._fail(e)
        except Exception as e:                      # never leave the UI stuck on a progress bar
            self._fail(UpdateError("unexpected", f"L'aggiornamento non è riuscito ({type(e).__name__}). L'app non è stata modificata."))
        else:
            return
        shutil.rmtree(folder / "staging", ignore_errors=True)    # keep the .part file: a retry resumes it

    def _download_verify_extract(self, rel: Release, folder: Path) -> None:
        pkg = rel.assets[PACKAGE_NAME[self.platform]]
        total = pkg["size"]
        # ---- room for the download, the extracted copy and the backup rename (instant, but the new folder must fit next to the old one)
        folder.mkdir(parents=True, exist_ok=True)
        need = int(total * 3.5) + 50_000_000
        if free_bytes(folder) < need:
            raise UpdateError("no_space", f"Spazio su disco insufficiente: servono circa {need // 1_000_000} MB liberi. Libera spazio e riprova: l'app non è stata modificata.")
        # ---- checksum list from the SAME release
        sums_text = source.read_small(rel.assets[SUMS_NAME]["url"], self.policy)
        if signing.enforced():                                    # a public key is embedded: the checksum list must carry the maintainer's signature
            sig = rel.assets.get(signing.SIG_NAME)
            sig_text = None
            if sig:
                try:
                    sig_text = source.read_small(sig["url"], self.policy)
                except UpdateError:                              # listed but not downloadable = no signature
                    sig_text = None
            if not signing.check_sums(sums_text, sig_text):
                raise UpdateError("bad_signature", "La release non ha una firma valida del progetto: per sicurezza non la installo.")
        sums = source.parse_sums(sums_text)
        want = sums.get(PACKAGE_NAME[self.platform])
        if not want:
            raise UpdateError("no_checksum", "La release non contiene il codice di controllo del pacchetto: per sicurezza non lo installo.")
        # ---- download (with resume after a network loss)
        part = folder / (PACKAGE_NAME[self.platform] + ".part")
        self._set(state="downloading", step=2, total=total, message="Scarico la nuova versione…")
        attempt = 0
        while True:
            have = part.stat().st_size if part.exists() else 0
            if total and have > total:
                part.unlink(); have = 0
            if total and have == total:
                break
            try:
                with open(part, "ab" if have else "wb") as f:
                    for chunk in source.stream(pkg["url"], self.policy, start=have, timeout=self.timeout * 2):
                        f.write(chunk)
                        have += len(chunk)
                        self._set(bytes=have, progress=(have / total) if total else None)
                if total and have < total:                # the server closed the connection early: a short file is an interruption, not a finished download
                    raise UpdateError("interrupted", "La connessione si è interrotta durante il download.")
                break
            except UpdateError as e:
                if e.code not in ("interrupted", "offline", "no_resume"):
                    raise
                attempt += 1
                if e.code == "no_resume":
                    part.unlink(missing_ok=True)
                if attempt >= self.retries:
                    raise UpdateError("interrupted", "Il download si è interrotto e non riesco a riprenderlo. Controlla la connessione e riprova: l'app non è stata modificata.") from e
                self._set(message=f"Connessione interrotta: riprovo ({attempt}/{self.retries - 1})…")
                time.sleep(min(2.0 * attempt, 5.0))
        # ---- integrity
        self._set(state="verifying", step=3, progress=0.0, bytes=0, message="Controllo che il file sia integro…")
        h, done = hashlib.sha256(), 0
        size = part.stat().st_size
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                done += len(chunk)
                self._set(bytes=done, total=size, progress=done / size if size else 1.0)
        if h.hexdigest() != want:
            part.unlink(missing_ok=True)
            raise UpdateError("bad_checksum", "Il file scaricato non corrisponde al codice di controllo (è danneggiato o è stato alterato). Non è stato installato nulla: riprova più tardi.")
        # ---- structure of the package, then extract to a staging folder (zip-slip safe)
        zpath = folder / PACKAGE_NAME[self.platform]
        os.replace(part, zpath)
        exe = EXE_NAME[self.platform]
        staging = folder / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                if exe not in names or UPDATER_EXE not in names:
                    raise UpdateError("bad_package", "Il pacchetto non è una versione valida dell'app. Non è stato installato nulla.")
                root = staging.resolve()
                members = z.infolist()
                self._set(state="installing", step=4, progress=0.0, message="Preparo i file della nuova versione…")
                for i, m in enumerate(members, 1):
                    dest = (staging / m.filename).resolve()
                    if not dest.is_relative_to(root):
                        raise UpdateError("bad_package", "Il pacchetto contiene percorsi non sicuri. Non è stato installato nulla.")
                    z.extract(m, staging)
                    if i % 25 == 0 or i == len(members):
                        self._set(progress=i / len(members))
        except zipfile.BadZipFile as e:
            zpath.unlink(missing_ok=True)
            raise UpdateError("bad_package", "Il pacchetto scaricato è danneggiato. Non è stato installato nulla: riprova più tardi.") from e
        zpath.unlink(missing_ok=True)            # the extracted copy is all that is needed from here

    def _hand_over(self, rel: Release, folder: Path) -> None:
        self._set(state="installing", step=4, progress=1.0, message="Installazione: l'app si chiude e si riapre da sola…")
        self.launcher({"app": self.install_dir, "staging": folder / "staging", "exe": EXE_NAME[self.platform], "pid": os.getpid(),
                       "from": self.current, "to": rel.version_str, "work": self.work, "app_args": self.app_args})
        self._set(state="restarting", step=5, message="Riavvio dell'app…")
        if self.quit_cb:
            time.sleep(0.5)
            self.quit_cb()

    def _launch_helper(self, p: dict) -> None:
        """Copy the small updater out of the install folder (it must not be locked by what it replaces) and start it detached."""
        tmp = Path(tempfile.mkdtemp(prefix="reai-updater-"))
        helper = tmp / UPDATER_EXE
        shutil.copy2(Path(p["app"]) / UPDATER_EXE, helper)
        cmd = [str(helper), "--app", str(p["app"]), "--staging", str(p["staging"]), "--exe", p["exe"], "--pid", str(p["pid"]),
               "--from", p["from"], "--to", p["to"], "--work", str(p["work"]), "--", *p["app_args"]]
        apply_mod.start(helper, cmd[1:])
