"""Desktop shell: PySide6 + Qt WebEngine around the SAME backend/UI used by the browser.

Starts the backend in-process (engine + FastAPI/uvicorn on a loopback port), shows the web UI, lives in the system tray,
raises notifications on connection-state changes and shuts everything down in a controlled way.
Windows is the target platform; the code is platform neutral and has been smoke-tested headless on Linux only.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time

from ..lmu.diagnostics import STATE_LABELS_IT, ConnState


class Backend:
    """In-process backend with controlled start/stop."""

    def __init__(self, synthetic: str | None, port: int = 0):
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
        with socket.socket() as s:        # pick a free loopback port
            s.bind(("127.0.0.1", port)); self.port = s.getsockname()[1]
        app = create_app(self.engine, self.catalog, lan_enabled=False, install=None if synthetic else find_install())
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="uvicorn")
        self.thread.start()
        t0 = time.time()
        while not self.server.started and time.time() - t0 < 15:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("backend did not start")

    def _run_game(self):
        while not self._stop_game.is_set() and self.game.step():
            time.sleep(0.01)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/app/"

    def stop(self):
        if self.game:
            self._stop_game.set()
        self.server.should_exit = True
        self.thread.join(10)
        self.engine.stop()
        self.catalog.close()


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="race-engineer-desktop")
    ap.add_argument("--synthetic", help="use the SYNTHETIC fake game instead of LMU")
    ap.add_argument("--smoke", action="store_true", help="headless self-test: load the UI, check, exit")
    ap.add_argument("--start-minimized", action="store_true")
    args = ap.parse_args(argv)
    if args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu" if args.smoke else "")
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Race Engineer AI")
    app.setQuitOnLastWindowClosed(False)
    pm = QPixmap(64, 64); pm.fill(Qt.GlobalColor.transparent)
    pt = QPainter(pm); pt.setRenderHint(QPainter.RenderHint.Antialiasing); pt.setBrush(QColor("#0b0d10")); pt.setPen(QColor("#38bdf8"))
    pt.drawEllipse(4, 4, 56, 56); pt.setPen(QColor("#e6ebf0")); pt.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "RE"); pt.end()
    icon = QIcon(pm)

    backend = Backend(args.synthetic)
    win = QMainWindow(); win.setWindowTitle("Race Engineer AI"); win.setWindowIcon(icon); win.resize(1400, 900)
    view = QWebEngineView(); win.setCentralWidget(view); view.load(QUrl(backend.url))
    tray = QSystemTrayIcon(icon, app)
    quitting = {"v": False}
    result = {"loaded": None, "notified": []}

    menu = QMenu()
    act_open = QAction("Apri Race Engineer AI"); act_open.triggered.connect(lambda: (win.showNormal(), win.activateWindow()))
    act_quit = QAction("Esci"); act_quit.triggered.connect(lambda: do_quit())
    menu.addAction(act_open); menu.addSeparator(); menu.addAction(act_quit)
    tray.setContextMenu(menu); tray.setToolTip("Race Engineer AI")
    tray.activated.connect(lambda r: win.showNormal() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()

    def do_quit():
        quitting["v"] = True
        tray.hide(); win.close()
        backend.stop()                 # controlled shutdown of server, engine, recorder
        app.quit()

    def close_event(ev):               # closing the window minimizes to tray while the engine keeps recording
        if not quitting["v"] and tray.isVisible():
            ev.ignore(); win.hide()
            tray.showMessage("Race Engineer AI", "In esecuzione in background. Usa «Esci» dal menu per chiudere.")
        else:
            ev.accept()
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

    if not args.start_minimized and not args.smoke:
        win.show()
    if args.smoke:
        win.show()
        view.loadFinished.connect(lambda ok: result.__setitem__("loaded", ok))

        def finish():
            title = {"t": None}
            view.page().runJavaScript("document.querySelector('nav h1') ? document.querySelector('nav h1').textContent : null", lambda v: (title.__setitem__("t", v), report(title["t"])))

        def report(t):
            ok = bool(result["loaded"]) and bool(t) and "Race Engineer" in t
            print(f"SMOKE loaded={result['loaded']} nav_title={t!r} state={backend.engine.state.value} samples={backend.engine.stats.samples_received}")
            do_quit(); app.exit(0 if ok else 1)
        QTimer.singleShot(8000, finish)
    code = app.exec()
    return code


if __name__ == "__main__":
    raise SystemExit(run())
