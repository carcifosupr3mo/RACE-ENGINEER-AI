import pytest
from fastapi.testclient import TestClient

from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall, find_install
from race_engineer.synthetic.game import SyntheticGame

from .conftest import make_engine
from .test_import_discovery_diag import make_fake_steam


@pytest.fixture
def live(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog)
    for _ in range(150):
        g.step(); e.poll_once()
    yield g, e
    e.stop()


def client(e, catalog, **kw):
    return TestClient(create_app(e, catalog, install=kw.pop("install", LmuInstall()), **kw), base_url="http://127.0.0.1")


def test_status_live_and_sessions(live, catalog):
    g, e = live
    c = client(e, catalog)
    assert c.get("/api/health").json()["lan_enabled"] is False
    st = c.get("/api/status").json()
    assert st["state"] == "acquiring" and st["synthetic"] is True and st["state_label"] == "Acquisizione attiva"
    lv = c.get("/api/live").json()
    assert lv["source"] == "synthetic" and lv["provenance"]["speed_kmh"] == "synthetic"
    assert c.get("/api/sessions").json()[0]["is_synthetic"] == 1
    assert c.get("/api/layout").json()["verified_against_real_lmu"] is False
    assert "SYNTHETIC" in c.get("/api/diagnostics/report").json()["verdict"]
    assert "Race Engineer" in c.get("/diag").text
    assert c.get("/", follow_redirects=False).status_code in (200, 307)


def test_foreign_host_header_is_rejected(live, catalog):
    _, e = live
    c = client(e, catalog)
    assert c.get("/api/status", headers={"Host": "evil.example.com"}).status_code == 403


def test_lan_mode_requires_token(live, catalog):
    _, e = live
    app = create_app(e, catalog, lan_enabled=True, token="secret-token", install=LmuInstall())
    c = TestClient(app, base_url="http://192.168.1.5")
    assert c.get("/api/status").status_code == 403
    assert c.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert c.get("/api/status", headers={"Authorization": "Bearer secret-token"}).status_code == 200
    assert c.get("/api/status?token=secret-token").status_code == 200


def test_websocket_streams_and_rejects_foreign_origin(live, catalog):
    _, e = live
    c = client(e, catalog)
    with c.websocket_connect("/ws/live", headers={"host": "127.0.0.1"}) as ws:
        msg = ws.receive_json()
    assert msg["status"]["state"] == "acquiring" and msg["sample"]["values"]["gear"] >= 1
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/live", headers={"host": "127.0.0.1", "origin": "http://evil.example.com"}):
            pass


def test_duckdb_inspect_is_restricted_to_telemetry_folder(live, catalog, tmp_path):
    _, e = live
    lib, game = make_fake_steam(tmp_path / "fs")
    c = client(e, catalog, install=find_install(roots=[lib]))
    files = c.get("/api/duckdb/files").json()
    ok = c.get("/api/duckdb/inspect", params={"path": files[0]["path"]})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert c.get("/api/duckdb/inspect", params={"path": "/etc/passwd"}).status_code == 404
    assert c.get("/api/duckdb/inspect", params={"path": str(game / "UserData" / "Telemetry" / ".." / ".." / "x.duckdb")}).status_code == 404


def test_cross_site_origin_is_rejected_on_loopback(live, catalog):
    """A web page open in the user's browser must not be able to drive the local API (CSRF): foreign Origin -> 403."""
    game, e = live
    c = client(e, catalog)
    assert c.post("/api/ai/providers/test", headers={"Origin": "http://evil.example.com"}).status_code == 403
    assert c.get("/api/status", headers={"Origin": "http://evil.example.com"}).status_code == 403
    assert c.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.get("/api/status", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/status", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_runtime_lan_switch_gates_remote_clients(live, catalog):
    """In-app ON/OFF: a remote PC (non-loopback source address) is refused while LAN is off, needs the token while on;
    only this PC may flip the switch; the local app keeps working without a token either way."""
    _, e = live
    app = create_app(e, catalog, token="tok-123456", install=LmuInstall())
    state = app.state.lan
    calls = []
    state["control"] = lambda on: (calls.append(on), state.update(on=on, port=47653 if on else None))
    local = TestClient(app, base_url="http://127.0.0.1")
    remote = TestClient(app, base_url="http://192.168.1.5:47653", client=("192.168.1.5", 50000))
    assert local.get("/api/lan").json()["enabled"] is False
    assert remote.get("/api/status?token=tok-123456").status_code == 403          # off: even the right token is refused
    assert remote.put("/api/lan", json={"enabled": True}).status_code == 403
    r = local.put("/api/lan", json={"enabled": True}).json()
    assert r["enabled"] is True and r["token"] == "tok-123456" and calls == [True]
    assert local.get("/api/status").status_code == 200                              # local app unaffected, no token needed
    assert remote.get("/api/status").status_code == 403
    assert remote.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert remote.get("/api/status?token=tok-123456").status_code == 200
    assert remote.put("/api/lan?token=tok-123456", json={"enabled": False}).status_code == 403   # a remote PC cannot switch it
    assert local.put("/api/lan", json={"enabled": "yes"}).status_code == 422
    local.put("/api/lan", json={"enabled": False})
    assert remote.get("/api/status?token=tok-123456").status_code == 403


def test_lan_switch_unavailable_without_desktop_shell(live, catalog):
    _, e = live
    c = client(e, catalog)
    assert c.get("/api/lan").json()["available"] is False
    assert c.put("/api/lan", json={"enabled": True}).status_code == 409
