"""Unified live engineer: one shared state for dashboard + Driving Display, coherence with the offline analysis, learning state,
single frozen suggestion, real-position map, WebSocket sharing, LAN security. SYNTHETIC data only."""
import json

import pytest
from fastapi.testclient import TestClient

from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.synthetic.game import SyntheticGame
from race_engineer.synthetic.track import SCENARIOS, Scenario

from .conftest import make_engine

H = {"host": "127.0.0.1"}
FAST = {"tick_hz": 1e9, "synchronous": True}          # tick on every sample and analyse laps inline: deterministic tests


def run(tmp_path, catalog, scenario="mixed", laps=6, session_code=1, observe=None, **kw):
    g = SyntheticGame(scenario, laps=laps, session_code=session_code)
    e = make_engine(g, tmp_path, catalog)
    app = create_app(e, catalog, install=LmuInstall(), live_options=FAST, **kw)
    live = app.state.live
    snaps = []
    while g.step():
        e.poll_once()
        if observe and e.stats.samples_received % observe == 0:
            snaps.append(live.snapshot())
    return g, e, app, live, snaps


def strip(st):
    return {k: v for k, v in st.items() if k not in ("connection", "server_time")}


def test_learning_state_until_two_valid_laps_then_single_suggestion(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, scenario="repeated", laps=8, observe=50)
    early = [s for s in snaps if s["ready"] and s["lap"]["number"] == 1]
    assert early and all(s["suggestion"]["state"] == "learning" and s["suggestion"]["main"] is None for s in early)
    assert "Sto imparando" in early[0]["suggestion"]["learning"]["message"]
    ready = [s for s in snaps if s["suggestion"]["state"] in ("ready", "frozen")]
    assert ready, "after enough valid laps a suggestion must appear"
    for s in snaps:
        m = s["suggestion"]["main"]
        assert m is None or (isinstance(m, dict) and m["corner"] and m["text"] and m["confidence"]["level"] in ("alta", "media", "bassa"))
    e.stop()


def test_suggestion_is_frozen_while_driver_is_busy(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, scenario="repeated", laps=8, observe=5)
    prev = None
    n_frozen = 0
    for s in snaps:
        if prev and s["lap"]["number"] == prev["lap"]["number"] and s["corner"]["demanding"] and prev["corner"]["demanding"] and prev["suggestion"]["main"]:
            assert s["suggestion"]["main"]["id"] == prev["suggestion"]["main"]["id"], "suggestion changed while the driver was in a corner/braking"
            assert s["suggestion"]["frozen"] is True
            n_frozen += 1
        prev = s
    assert n_frozen > 20
    e.stop()


def test_live_delta_matches_the_lap_analysis(tmp_path, catalog):
    g = SyntheticGame("mixed", laps=4)
    e = make_engine(g, tmp_path, catalog)
    live = create_app(e, catalog, install=LmuInstall(), live_options=FAST).state.live
    last = {}
    while g.step():
        e.poll_once()
        st = live.snapshot()
        if st["ready"] and st["delta"]["available"]:
            last[st["lap"]["number"]] = st["delta"]["to_ref_s"]
    e.stop()
    live.flush()
    checked = 0
    for lap, res in live.by_lap.items():
        if lap in last and res["total_delta_s"] is not None and res["ref_lap"] == 1:
            assert last[lap] == pytest.approx(res["total_delta_s"], abs=0.05)
            checked += 1
    assert checked >= 2


def test_dashboard_and_display_get_the_same_state_ws_and_rest(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=4)
    c = TestClient(app, base_url="http://127.0.0.1")
    with c.websocket_connect("/ws/live", headers=H) as ws:
        msg = ws.receive_json()
    rest = c.get("/api/engineer/state").json()
    assert "engineer" in msg and msg["engineer"]["ready"] is True
    a, b = strip(msg["engineer"]), strip(rest)
    assert a == b                                                   # identical shared state (WS field == REST), nothing recomputed per consumer
    full = c.get("/api/engineer/state?full=1").json()
    assert full["map_version"] == rest["map_version"] == c.get("/api/engineer/map").json()["version"]
    assert c.get("/api/engineer/reference").json()["version"] == rest["reference"]["version"]
    e.stop()


def test_events_make_new_lap_and_reference_change_visible(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=5)
    c = TestClient(app, base_url="http://127.0.0.1")
    ev = c.get("/api/engineer/events?since=0").json()
    kinds = [x["type"] for x in ev["events"]]
    assert kinds.count("lap_completed") >= 4 and "reference_changed" in kinds and "analysis_ready" in kinds and "session_started" in kinds
    assert [x["seq"] for x in ev["events"]] == sorted(x["seq"] for x in ev["events"])
    assert c.get(f"/api/engineer/events?since={ev['seq']}").json()["events"] == []
    e.stop()


def test_live_analysis_equals_offline_driving_analysis_of_the_recorded_session(tmp_path, catalog):
    """Same laps -> same findings whether computed live or from the recorded session (one implementation: driving.analyse)."""
    g, e, app, live, _ = run(tmp_path, catalog, laps=5)
    e.stop()
    live.flush()
    c = TestClient(app, base_url="http://127.0.0.1")
    sid = catalog.list_sessions()[0]["id"]
    n = 0
    for lap, res in live.by_lap.items():
        if res["ref_lap"] != 1:
            continue
        off = c.get(f"/api/sessions/{sid}/driving?lap={lap}&ref=1")
        assert off.status_code == 200
        off = off.json()
        sig = lambda r: [(f["corner"], f["type"], f["phase"], f["evidence"], f["time_impact_s"]) for f in r["findings"]]
        assert sig(off) == sig(json.loads(json.dumps(res)))
        assert off["total_delta_s"] == pytest.approx(res["total_delta_s"], abs=1e-6)
        assert [r["lap"] for r in off["corners"]] == [r["lap"] for r in res["corners"]]
        n += 1
    assert n >= 2


def test_session_adaptation_in_shared_state(tmp_path, catalog):
    for code, mode in ((1, "practice"), (5, "qualifying"), (10, "race"), (0, "test")):
        d = tmp_path / f"s{code}"
        d.mkdir()
        from race_engineer.storage.catalog import Catalog
        cat = Catalog(d / "c.sqlite")
        g, e, app, live, _ = run(d, cat, scenario="constant", laps=1, session_code=code)
        st = live.snapshot()
        assert st["session"]["mode"]["mode"] == mode and st["session"]["mode"]["recognized"]
        e.stop()
        cat.close()


def test_map_comes_from_real_positions_and_is_absent_without_them(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=3)
    m = live.map_payload()
    assert m["available"] and m["source"] == "reference" and len(m["points"]) > 500 and m["synthetic"] is True
    anchor = live.ref.anchor.aligned
    import numpy as np
    xs = np.array([p[0] for p in m["points"]])
    assert np.allclose(xs, np.round(anchor.ch["pos_x_m"][::3][: len(xs)], 1), atol=0.11)       # exactly the measured positions
    assert {z["type"] for z in m["zones"]} >= {"brake", "release", "accel"} and m["corners"] and m["corners"][0]["apex_xz"]
    e.stop()
    d = tmp_path / "nopos"
    d.mkdir()
    from race_engineer.storage.catalog import Catalog
    cat = Catalog(d / "c.sqlite")
    g2 = SyntheticGame("constant", laps=3)
    e2 = make_engine(g2, d, cat)
    e2.on_sample.insert(0, lambda s: s.values.update(pos_x_m=None, pos_z_m=None))      # position channels unavailable in this session
    live2 = create_app(e2, cat, install=LmuInstall(), live_options=FAST).state.live
    while g2.step():
        e2.poll_once()
    m2 = live2.map_payload()
    assert m2["available"] is False and "reason" in m2 and "points" not in m2
    e2.stop()
    cat.close()


def test_synthetic_reference_never_mixes_with_real_store(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=3)
    e.stop()
    files = sorted(p.name for p in (tmp_path / "references").glob("*.npz"))
    assert files and all(f.startswith("synthetic_") for f in files)
    assert live.snapshot()["synthetic"] is True and live.snapshot()["reference"]["synthetic"] is True


def test_reference_persists_across_sessions(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=3)
    e.stop()
    n = len(live.ref.laps)
    g2, e2, app2, live2, snaps = run(tmp_path, catalog, scenario="constant", laps=2, observe=200)
    assert live2.ref.loaded_from_disk >= n          # the next session starts from the saved reference: no relearning from zero
    ready = [s for s in snaps if s["ready"]]
    assert ready and ready[0]["reference"]["laps"] >= n and ready[0]["suggestion"]["state"] != "learning"
    e2.stop()


def test_engineer_never_breaks_acquisition(tmp_path, catalog):
    g = SyntheticGame("constant", laps=2)
    e = make_engine(g, tmp_path, catalog)
    live = create_app(e, catalog, install=LmuInstall(), live_options=FAST).state.live
    live._finalize = lambda job: (_ for _ in ()).throw(RuntimeError("boom"))       # a failing analysis...
    while g.step():
        e.poll_once()
    assert e.stats.samples_received > 100 and live.errors                           # ...is recorded, acquisition goes on
    e.stop()


def test_display_page_info_and_lan_security(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>app</body></html>")
    c = TestClient(create_app(e, catalog, install=LmuInstall(), webdist=dist, live_options=FAST), base_url="http://127.0.0.1")
    r = c.get("/driving-display")
    assert r.status_code == 200 and "app" in r.text and c.get("/driving-display/").status_code == 200
    info = c.get("/api/display/info").json()
    assert info["path"] == "/driving-display" and info["lan_enabled"] is False and info["lan_urls"] == [] and "Display in rete" in info["how_to_enable_lan"]
    nodist = TestClient(create_app(e, catalog, install=LmuInstall(), webdist=tmp_path / "missing", live_options=FAST), base_url="http://127.0.0.1")
    assert nodist.get("/driving-display").status_code == 503
    lan = TestClient(create_app(e, catalog, install=LmuInstall(), lan_enabled=True, token="tok123", webdist=dist, live_options=FAST), base_url="http://192.168.1.50:8765")
    assert lan.get("/api/engineer/state").status_code == 403 and lan.get("/api/display/info").status_code == 403
    ok = lan.get("/api/display/info", headers={"Authorization": "Bearer tok123"}).json()
    assert ok["lan_enabled"] is True and all(u.endswith("/driving-display?token=tok123") for u in ok["lan_urls"])
    assert lan.get("/api/engineer/state?token=tok123").status_code == 200
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with lan.websocket_connect("/ws/live"):
            pass
    with lan.websocket_connect("/ws/live?token=tok123") as ws:
        assert "engineer" in ws.receive_json()
    e.stop()


def test_websocket_clients_can_reconnect_and_get_current_state(tmp_path, catalog):
    g, e, app, live, _ = run(tmp_path, catalog, laps=3)
    c = TestClient(app, base_url="http://127.0.0.1")
    seqs = []
    for _ in range(3):                      # a display that drops and reconnects (Raspberry Wi-Fi) is served the same current state each time
        with c.websocket_connect("/ws/live", headers=H) as ws:
            seqs.append(ws.receive_json()["engineer"]["seq"])
    assert seqs[0] == seqs[1] == seqs[2] == live.seq
    e.stop()


def test_events_are_pushed_over_websocket(tmp_path, catalog):
    g = SyntheticGame("constant", laps=2)
    e = make_engine(g, tmp_path, catalog)
    app = create_app(e, catalog, install=LmuInstall(), live_options=FAST)
    c = TestClient(app, base_url="http://127.0.0.1")
    for _ in range(100):
        g.step(); e.poll_once()
    with c.websocket_connect("/ws/live", headers=H) as ws:
        first = ws.receive_json()
        while g.step():
            e.poll_once()
        got = []
        for _ in range(200):                                  # messages queued while the (fast) simulation ran are drained in order
            got += [x["type"] for x in ws.receive_json()["events"]]
            if "lap_completed" in got:
                break
    assert "lap_completed" in got
    e.stop()


def test_live_check_is_synthetic_never_real_and_has_no_personal_data(tmp_path, catalog):
    g = SyntheticGame("mixed", laps=8, session_code=1)
    e = make_engine(g, tmp_path, catalog)
    app = create_app(e, catalog, install=LmuInstall(), live_options=FAST)
    live = app.state.live
    while g.step():                                              # stop mid-session: the delta is a LIVE value
        e.poll_once()
        st = live.snapshot()
        if (st.get("reference") or {}).get("laps", 0) >= 3 and (st.get("delta") or {}).get("available"):
            break
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/api/engineer/checklist").json()
    assert r["data_provenance"] == "synthetic" and r["verdict"] == "SYNTHETIC_NOT_REAL"          # a synthetic run can never certify the real chain
    assert r["steps"]["lmu_process"]["status"] == "unverified" and r["steps"]["shared_memory"]["status"] == "unverified"
    for k in ("session", "track", "samples", "map", "braking_points", "acceleration_points", "corner_analysis", "coach_instruction", "lap_review", "coach_memory", "delta"):
        assert r["steps"][k]["status"] == "ok", (k, r["steps"][k])
    assert r["order"] == list(r["titles"]) or set(r["order"]) == set(r["titles"])
    md = c.get("/api/engineer/checklist?format=md").text
    assert "SINTETICI" in md and "SYNTHETIC_NOT_REAL" in md
    blob = json.dumps(r) + md
    assert "driver_name" not in blob and "nvapi" not in blob and "gsk_" not in blob
    e.stop()


def test_live_check_real_requires_every_automatic_step():
    from race_engineer.live import checklist as ck
    snap = {"synthetic": False, "session": {"id": 1, "type": "practice", "track": "T", "track_length_m": 5000, "vehicle": "V", "mode": "practice"},
            "reference": {"laps": 0}, "delta": {"available": False}, "last_lap": None, "suggestion": {"state": "learning"}, "seq": 1}
    diag = {"synthetic": False, "state": "acquiring", "mapping": {"size": 324820, "expected_size": 324820}, "samples_received": 5000, "effective_hz": 60}
    r = ck.build(snapshot=snap, map_payload={"available": False, "reason": "x"}, engine_diag=diag, lmu_process=True, live_status={})
    assert r["data_provenance"] == "lmu_shared_memory" and r["verdict"] == "REAL_INCOMPLETE"
    assert r["steps"]["shared_memory"]["status"] == "ok" and r["steps"]["map"]["status"] == "missing"
