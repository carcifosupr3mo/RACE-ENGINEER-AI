"""The real in-process backend: switching LAN access on opens a second listener, off closes it (no command line)."""
import json
import socket
import urllib.request

import pytest

from race_engineer.api.app import _lan_ips


def _get(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError:
        return None, b""


def test_lan_listener_opens_and_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path))
    from race_engineer.desktop.main import Backend
    b = Backend("constant")
    try:
        assert b.app.state.lan["on"] is False
        b.set_lan_access(True)
        st = b.app.state.lan
        assert st["on"] and st["port"] and st["port"] != b.port
        code, body = _get(f"http://127.0.0.1:{st['port']}/api/health")
        assert code == 200 and json.loads(body)["lan_enabled"] is True
        cfg = json.loads((tmp_path / "lan.json").read_text())
        assert cfg["token"] == b.token and cfg["port"] == st["port"]
        for ip in _lan_ips()[:1]:             # from a non-loopback address the token is mandatory
            assert _get(f"http://{ip}:{st['port']}/api/status")[0] == 403
            assert _get(f"http://{ip}:{st['port']}/api/status?token={b.token}")[0] == 200
        assert b.lan_display_urls() == [f"http://{ip}:{st['port']}/driving-display?token={b.token}" for ip in _lan_ips()]
        b.set_lan_access(False)
        assert b.app.state.lan["on"] is False
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", st["port"]), timeout=1).close()
        assert _get(f"http://127.0.0.1:{b.port}/api/health")[0] == 200     # the local app never went away
    finally:
        b.stop()
