"""One running copy. A second launch asks the first one to show its window (it usually lives hidden in the system tray) and
exits; the installer/uninstaller asks it to quit cleanly (`--quit`) so files are not in use and the recording is closed properly."""
from __future__ import annotations

import sys
from typing import Callable

NAME = "race_engineer_ai_app"
SHOW, QUIT = b"show", b"quit"


def _send(command: bytes, name: str, timeout_ms: int) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(command + b"\n")
    sock.waitForBytesWritten(timeout_ms)
    sock.waitForDisconnected(timeout_ms)   # the running copy hangs up once it has read the command
    return True


def notify_running(name: str = NAME, timeout_ms: int = 1000) -> bool:
    """True if a running copy answered; it then shows its window."""
    if sys.platform == "win32":  # pragma: no cover
        try:                              # Windows only lets the foreground process hand the focus over: without this the
            import ctypes                 # running copy could only flash its taskbar button instead of coming to the front
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
    return _send(SHOW, name, timeout_ms)


def request_quit(name: str = NAME, timeout_ms: int = 1000) -> bool:
    """True if a running copy answered; it then shuts down in a controlled way (same path as «Esci» in the tray menu)."""
    return _send(QUIT, name, timeout_ms)


def listen(on_show: Callable[[], None], name: str = NAME, on_quit: Callable[[], None] | None = None):
    """Start answering other launches. Returns the server (keep a reference) or None if the name cannot be taken.
    Only two commands exist and neither carries data; anything else is treated as «show»."""
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(name)       # stale socket file left by a crash (no-op on Windows named pipes)
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)      # same user only

    def accepted():
        conn = srv.nextPendingConnection()
        if conn is None:
            return
        if not conn.bytesAvailable():
            conn.waitForReadyRead(500)     # the client writes right after connecting; a silent one still means «show»
        command = bytes(conn.readAll().data()).strip()
        conn.disconnectFromServer()
        conn.deleteLater()
        (on_quit if command == QUIT and on_quit is not None else on_show)()
    srv.newConnection.connect(accepted)
    return srv if srv.listen(name) else None
