"""Desktop shell: PySide6 + Qt WebEngine around the SAME backend/UI used by the browser.

Starts the backend in-process (engine + FastAPI/uvicorn on a loopback port), shows the web UI, lives in the system tray,
raises notifications on connection-state changes and shuts everything down in a controlled way.
Windows is the target platform; the code is platform neutral and has been smoke-tested headless on Linux only.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time

from ..lmu.diagnostics import STATE_LABELS_IT, ConnState


RELEASES_URL = "https://github.com/carcifosupr3mo/RACE-ENGINEER-AI/releases"


class Backend:
    """In-process backend with controlled start/stop."""

    def __init__(self, synthetic: str | None, port: int = 0, lan: bool = False):
        import uvicorn
        from ..acquisition.engine import AcquisitionEngine
        from ..api.app import create_app
        from ..lmu.discovery import find_install
        from ..lmu.reader import open_backend
        from ..storage.catalog import Catalog
        from ..storage.paths import data_dir
        root = data_dir()
        self.catalog = Catalog(root / "catalog.sqlite")
        self.game = None
        if synthetic:
            from ..synthetic.game import SyntheticGame
            self.game = SyntheticGame(synthetic, laps=30)
            self._stop_game = threading.Event()
            threading.Thread(target=self._run_game, daemon=True, name="synthetic-game").start()
            opener = lambda: self.game.backend
        else:
            opener = lambda: open_backend()
        self.engine = AcquisitionEngine(opener, catalog=self.catalog, data_root=root)
        self.engine.start()
        with socket.socket() as s:        # pick a free port (loopback unless LAN mode)
            s.bind(("0.0.0.0" if lan else "127.0.0.1", port)); self.port = s.getsockname()[1]
        self.lan = lan
        self._lan_file = root / "lan.json"
        self._lan_cfg = self._load_lan_cfg()
        app = create_app(self.engine, self.catalog, lan_enabled=lan, token=self._lan_cfg.get("token"),
                         install=None if synthetic else find_install())
        self.app, self.token = app, app.state.token
        self._lan_server = None
        app.state.lan["control"] = self.set_lan_access
        self._save_lan_cfg()
        # LAN mode is an explicit opt-in (off by default): bind all interfaces, every /api and /ws call then needs the token
        self.server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0" if lan else "127.0.0.1", port=self.port, log_level="warning",
                                                  log_config=None))   # windowed exe has no stdout/stderr: uvicorn's default colour formatter would crash ("Unable to configure formatter 'default'")
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="uvicorn")
        self.thread.start()
        t0 = time.time()
        while not self.server.started and time.time() - t0 < 15:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("backend did not start")

    # ---- LAN access on/off (in-app switch; no command line). A second listener on all interfaces serves the SAME app; every call from
    # a remote PC needs the token and is refused while the switch is off, the loopback listener is never changed.
    def _load_lan_cfg(self) -> dict:
        try:
            d = json.loads(self._lan_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_lan_cfg(self) -> None:
        self._lan_cfg.update(token=self.token, enabled=bool(self._lan_server))
        try:
            self._lan_file.write_text(json.dumps(self._lan_cfg), encoding="utf-8")
            if sys.platform != "win32":
                os.chmod(self._lan_file, 0o600)
        except OSError:
            pass

    def set_lan_access(self, enabled: bool) -> None:
        import uvicorn
        state = self.app.state.lan
        if not enabled:
            srv, self._lan_server = self._lan_server, None
            state["on"] = False
            if srv:
                srv.should_exit = True
                self._lan_thread.join(5)
            self._save_lan_cfg()
            return
        if self._lan_server:
            return
        want = int(self._lan_cfg.get("port") or 47653)
        last: Exception | None = None
        for port in (want, 0):             # preferred fixed port (stable bookmark on the other screen), else any free one
            try:
                with socket.socket() as s:
                    s.bind(("0.0.0.0", port)); port = s.getsockname()[1]
            except OSError as e:
                last = e
                continue
            srv = uvicorn.Server(uvicorn.Config(self.app, host="0.0.0.0", port=port, log_level="warning", log_config=None))
            th = threading.Thread(target=srv.run, daemon=True, name="uvicorn-lan")
            th.start()
            t0 = time.time()
            while not srv.started and th.is_alive() and time.time() - t0 < 10:
                time.sleep(0.05)
            if srv.started:
                self._lan_server, self._lan_thread = srv, th
                self._lan_cfg["port"] = port
                state.update(on=True, port=port)
                self._save_lan_cfg()
                return
            last = RuntimeError(f"porta {port} non disponibile")
        raise last or RuntimeError("impossibile aprire la rete")

    def _run_game(self):
        while not self._stop_game.is_set() and self.game.step():
            time.sleep(0.01)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/app/" + (f"?token={self.token}" if self.lan else "")

    @property
    def display_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/driving-display" + (f"?token={self.token}" if self.lan else "")

    def lan_display_urls(self) -> list[str]:
        st = self.app.state.lan
        if not st["on"]:
            return []
        from ..api.app import _lan_ips
        return [f"http://{ip}:{st['port'] or self.port}/driving-display?token={self.token}" for ip in _lan_ips()]

    def stop(self):
        if self.game:
            self._stop_game.set()
        if self._lan_server:
            self._lan_server.should_exit = True
        self.server.should_exit = True
        self.thread.join(10)
        self.engine.stop()
        self.catalog.close()


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="race-engineer-desktop")
    ap.add_argument("--synthetic", help="use the SYNTHETIC fake game instead of LMU")
    ap.add_argument("--smoke", action="store_true", help="headless self-test: load the UI, check, exit")
    ap.add_argument("--start-minimized", action="store_true")
    ap.add_argument("--lan", action="store_true", help="expose the Driving Display on the local network (token required; off by default)")
    ap.add_argument("--port", type=int, default=0, help="fixed port (default: a free one); needed by VERIFICA_DISPLAY.bat / live-check")
    ap.add_argument("--display", action="store_true", help="open the Driving Display on the second monitor at start")
    ap.add_argument("--display-auto", action="store_true", help="open the Driving Display at start only if a second monitor is connected")
    ap.add_argument("--quit", action="store_true", help="ask the running copy to shut down cleanly, wait for it, exit (used by the installer)")
    args = ap.parse_args(argv)
    if args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # lean web view: one renderer process, small JS heap, no background network/sync services (RAM and idle CPU)
    lean = "--renderer-process-limit=1 --js-flags=--max-old-space-size=192 --disable-background-networking --disable-sync --disable-breakpad --no-pings"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", ("--no-sandbox --disable-gpu " if args.smoke else "") + lean)
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

    from PySide6.QtCore import QDir, QLockFile
    from PySide6.QtWidgets import QMessageBox
    from .. import __version__
    from ..ai.providers.credentials import RedactFilter
    from . import autostart, single_instance
    from ..storage.paths import data_dir
    import logging
    import logging.handlers
    import traceback
    logdir = data_dir() / "logs"; logdir.mkdir(exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(logdir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.addFilter(RedactFilter())          # an API key can never reach the log file
    logging.basicConfig(level=logging.INFO, handlers=[fh], format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("race_engineer.desktop")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Race Engineer AI")
    lock = QLockFile(QDir.temp().filePath("race_engineer_ai_%s.lock" % ("smoke" if args.smoke else "app")))
    lock.setStaleLockTime(15000)
    instance_name = single_instance.NAME + ("_smoke" if args.smoke else "")
    if args.quit:                         # installer / uninstaller: stop the running copy so no file is in use and the recording is closed
        single_instance.request_quit(instance_name)
        stopped = lock.tryLock(20000)     # the lock is released when the running copy has finished its controlled shutdown
        log.info("--quit: running copy %s", "stopped (or none was running)" if stopped else "did NOT stop within 20 s")
        return 0 if stopped else 1
    if not lock.tryLock(100):             # a second instance would fight over the shared memory reader and data files
        if args.smoke:
            return 3
        if single_instance.notify_running(instance_name):      # normally the running copy just shows its window
            return 0
        QMessageBox.information(None, "Race Engineer AI", "Race Engineer AI è già in esecuzione (controlla l'icona nella barra di sistema).")
        return 3

    def excepthook(et, ev, tb):
        log.error("unhandled: %s", "".join(traceback.format_exception(et, ev, tb)))
        if not args.smoke:
            QMessageBox.warning(None, "Race Engineer AI", f"Errore imprevisto: {ev}\nDettagli in {logdir / 'app.log'}")
    sys.excepthook = excepthook
    app.setQuitOnLastWindowClosed(False)
    pm = QPixmap(64, 64); pm.fill(Qt.GlobalColor.transparent)
    pt = QPainter(pm); pt.setRenderHint(QPainter.RenderHint.Antialiasing); pt.setBrush(QColor("#0b0d10")); pt.setPen(QColor("#38bdf8"))
    pt.drawEllipse(4, 4, 56, 56); pt.setPen(QColor("#e6ebf0")); pt.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "RE"); pt.end()
    icon = QIcon(pm)

    try:
        backend = Backend(args.synthetic, port=args.port, lan=args.lan)
    except Exception as e:
        log.exception("backend failed to start")
        if not args.smoke:
            QMessageBox.critical(None, "Race Engineer AI", f"Impossibile avviare il backend: {e}\nDettagli in {logdir / 'app.log'}")
        print(f"SMOKE backend start failed: {e}")
        return 1
    win = QMainWindow(); win.setWindowTitle("Race Engineer AI"); win.setWindowIcon(icon); win.resize(1400, 900)
    settings = QSettings("RaceEngineerAI", "Desktop")       # window size/position only (per user)
    if not args.smoke and settings.value("geometry") is not None:
        win.restoreGeometry(settings.value("geometry"))
    view = QWebEngineView(); win.setCentralWidget(view); view.load(QUrl(backend.url))
    tray = QSystemTrayIcon(icon, app)
    quitting = {"v": False}
    result = {"loaded": None, "notified": []}

    display = {"win": None}

    def open_display():
        """Driving Display = the same web app at /driving-display in a second window; placed on the 2nd monitor when Windows reports one."""
        if display["win"] is None:
            dw = QMainWindow(); dw.setWindowTitle("Race Engineer AI — Driving Display"); dw.setWindowIcon(icon)
            dv = QWebEngineView(); dw.setCentralWidget(dv); dv.load(QUrl(backend.display_url)); dw.resize(1280, 800)
            QShortcut(QKeySequence("F11"), dw, activated=lambda: dw.showNormal() if dw.isFullScreen() else dw.showFullScreen())
            display["win"], display["view"] = dw, dv
        dw = display["win"]
        screens = QGuiApplication.screens()
        main_screen = win.screen() if win.isVisible() else QGuiApplication.primaryScreen()
        other = next((sc for sc in screens if sc is not main_screen), None)
        if other is not None:
            dw.move(other.geometry().topLeft() + dw.rect().topLeft())
            dw.show(); dw.windowHandle().setScreen(other) if dw.windowHandle() else None
            dw.showFullScreen()
        else:
            dw.show()
        dw.raise_()
        return dw

    def toggle_lan(checked: bool):
        try:
            backend.set_lan_access(bool(checked))
        except Exception as e:
            act_lan.setChecked(False)
            QMessageBox.warning(None, "Display in rete", f"Non riesco ad aprire l'accesso di rete: {e}")
            return
        if checked:
            urls = backend.lan_display_urls()
            QApplication.clipboard().setText(urls[0] if urls else "")
            QMessageBox.information(None, "Display in rete attivo",
                                    "Apri uno di questi indirizzi dal browser dell'altro PC/tablet (il primo è già negli appunti).\n"
                                    "L'indirizzo contiene il token di accesso: tienilo privato.\n"
                                    "Se Windows chiede il permesso di rete, scegli «Consenti» (rete privata).\n\n" + ("\n".join(urls) or "Nessun indirizzo di rete privato trovato."))

    def show_main():
        win.showNormal(); win.raise_(); win.activateWindow()
    def second_launch():
        log.info("second launch: showing the running window")
        show_main()
    def quit_requested():
        log.info("quit requested by another launch (installer/uninstaller)")
        QTimer.singleShot(0, do_quit)
    instance_server = single_instance.listen(second_launch, instance_name, on_quit=quit_requested)      # a second launch lands here instead of a message box
    if instance_server is None:
        log.warning("single-instance channel unavailable: a second launch will only show a notice")

    def open_folder(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def toggle_autostart(on):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            log.warning("autostart toggle failed: %s", e)
            QMessageBox.warning(None, "Race Engineer AI", f"Impossibile modificare l'avvio automatico: {e}")
        act_auto.setChecked(autostart.is_enabled())

    menu = QMenu()
    act_ver = QAction(f"Race Engineer AI {__version__}"); act_ver.setEnabled(False)
    act_open = QAction("Apri Race Engineer AI"); act_open.triggered.connect(lambda: show_main())
    act_data = QAction("Apri cartella dati"); act_data.triggered.connect(lambda: open_folder(data_dir()))
    act_logs = QAction("Apri cartella log"); act_logs.triggered.connect(lambda: open_folder(logdir))
    act_upd = QAction("Scarica aggiornamenti (pagina delle release)…"); act_upd.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
    act_auto = QAction("Avvia con Windows (ridotto a icona)"); act_auto.setCheckable(True); act_auto.setChecked(autostart.is_enabled())
    act_auto.triggered.connect(toggle_autostart)
    act_disp = QAction("Apri Driving Display (secondo monitor)"); act_disp.triggered.connect(lambda: open_display())
    act_lan = QAction("Display in rete (LAN) — ON/OFF"); act_lan.setCheckable(True); act_lan.setChecked(bool(backend.app.state.lan["on"]))
    act_lan.toggled.connect(toggle_lan)
    act_quit = QAction("Esci"); act_quit.triggered.connect(lambda: do_quit())
    menu.addAction(act_ver); menu.addSeparator()
    menu.addAction(act_open); menu.addAction(act_disp); menu.addAction(act_lan); menu.addSeparator()
    menu.addAction(act_data); menu.addAction(act_logs); menu.addAction(act_upd)
    if autostart.supported():
        menu.addAction(act_auto)
    menu.addSeparator(); menu.addAction(act_quit)
    QShortcut(QKeySequence("Ctrl+D"), win, activated=lambda: open_display())
    tray.setContextMenu(menu); tray.setToolTip(f"Race Engineer AI {__version__}")
    tray.activated.connect(lambda r: show_main() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()

    def do_quit():
        quitting["v"] = True
        if not args.smoke:
            settings.setValue("geometry", win.saveGeometry()); settings.sync()
        if instance_server is not None:
            instance_server.close()
        tray.hide(); win.close()
        if display["win"] is not None:
            display["win"].close()
        backend.stop()                 # controlled shutdown of server, engine, recorder
        app.quit()

    def close_event(ev):               # the X closes the whole app: recording is closed and saved, nothing stays running
        if quitting["v"]:
            ev.accept()
        else:
            ev.ignore()
            QTimer.singleShot(0, do_quit)
    win.closeEvent = close_event       # type: ignore[method-assign]

    last = {"s": None}

    def watch():
        st = backend.engine.state
        if st != last["s"]:
            if last["s"] is not None and st in (ConnState.ACQUIRING, ConnState.SESSION_ENDED, ConnState.ERROR, ConnState.SHM_CONNECTED):
                msg = STATE_LABELS_IT[st]
                result["notified"].append(msg)
                if tray.isVisible():
                    tray.showMessage("Race Engineer AI", msg)
            last["s"] = st
    timer = QTimer(); timer.timeout.connect(watch); timer.start(1000)

    log.info("started: version %s, port %s, lan %s", __version__, backend.port, backend.lan)
    if not args.start_minimized and not args.smoke:
        win.show()
    if not args.smoke and (args.display or (args.display_auto and len(QGuiApplication.screens()) > 1)):
        open_display()
    if args.smoke:
        win.show()
        view.loadFinished.connect(lambda ok: result.__setitem__("loaded", ok))

        dview = QWebEngineView(); dview.load(QUrl(backend.display_url)); dview.resize(1024, 600); dview.show()      # Driving Display in the same Qt WebEngine

        def finish():
            title = {"t": None}

            def got_display(v):
                result["display"] = bool(v)
                view.page().runJavaScript("document.querySelector('nav h1') ? document.querySelector('nav h1').textContent : null", lambda t: (title.__setitem__("t", t), report(title["t"])))
            dview.page().runJavaScript("!!document.querySelector('[data-testid=driving-display]')", got_display)

        def api_checks() -> dict:
            import json
            import urllib.request
            base = backend.url.rsplit("/app/", 1)[0]
            out = {}
            try:                                  # the Driving Display page is served by the same backend
                with urllib.request.urlopen(base + "/driving-display", timeout=10) as r:
                    out["/driving-display"] = r.status == 200 and b'id="root"' in r.read()
            except Exception as e:
                out["/driving-display"] = f"{type(e).__name__}: {e}"
            for path in ("/diag", "/api/health", "/api/diagnostics/report", "/api/ai/providers", "/api/endurance/status", "/api/sessions",
                         "/api/engineer/state", "/api/display/info"):
                try:
                    with urllib.request.urlopen(base + path, timeout=10) as r:
                        body = r.read()
                        out[path] = r.status == 200 and (path == "/diag" or bool(json.loads(body) is not None))
                except Exception as e:
                    out[path] = f"{type(e).__name__}: {e}"
            return out

        def report(t):
            checks = api_checks()
            print("SMOKE api", checks)
            print("SMOKE driving-display rendered:", result.get("display"))
            ok = bool(result["loaded"]) and bool(t) and "Race Engineer" in t and all(v is True for v in checks.values()) and bool(result.get("display"))
            print(f"SMOKE loaded={result['loaded']} nav_title={t!r} state={backend.engine.state.value} samples={backend.engine.stats.samples_received}")
            do_quit(); app.exit(0 if ok else 1)
        QTimer.singleShot(8000, finish)
    code = app.exec()
    if not args.smoke:
        os._exit(code)                 # everything is saved by do_quit(): do not wait for stray threads, leave no process behind
    return code


if __name__ == "__main__":
    raise SystemExit(run())
