"""One running copy. A second launch asks the first one to show its window (it usually lives hidden in the system tray) and exits."""
from __future__ import annotations

import sys
from typing import Callable

NAME = "race_engineer_ai_app"


def notify_running(name: str = NAME, timeout_ms: int = 1000) -> bool:
    """True if a running copy answered. The message carries no data: the only thing the other side ever does is show its window."""
    from PySide6.QtNetwork import QLocalSocket
    if sys.platform == "win32":  # pragma: no cover
        try:                              # Windows only lets the foreground process hand the focus over: without this the
            import ctypes                 # running copy could only flash its taskbar button instead of coming to the front
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(b"show\n")
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


def listen(on_show: Callable[[], None], name: str = NAME):
    """Start answering second launches. Returns the server (keep a reference) or None if the name cannot be taken."""
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(name)       # stale socket file left by a crash (no-op on Windows named pipes)
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)      # same user only

    def accepted():
        conn = srv.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        on_show()
    srv.newConnection.connect(accepted)
    return srv if srv.listen(name) else None
