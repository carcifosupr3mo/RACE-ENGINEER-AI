"""Defects seen in REAL LMU data (user's Monza session), reproduced on the synthetic session:
at the start line the lap counter and the lap distance do not change on the same sample, the game's last-lap time is
published late, and the poller can miss a few samples. None of these may make a good lap unusable."""
import numpy as np
import pytest

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.analysis.align import align_lap
from race_engineer.analysis.compare import compare
from race_engineer.analysis.corners import detect_corners
from race_engineer.analysis.laps import SessionData, load_session, segment_laps
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame

L = 3000.0
_BASE: dict = {}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    if "sd" not in _BASE:
        d = tmp_path_factory.mktemp("defects")
        cat = Catalog(d / "c.sqlite")
        g = SyntheticGame("constant", laps=6)
        e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=d, process_probe=lambda: True, open_retry_s=0)
        while g.step():
            e.poll_once()
        e.stop()
        _BASE["sd"] = load_session(cat.list_sessions()[0]["data_path"], L)
        cat.close()
    return _BASE["sd"]


def mutated(base, fn) -> SessionData:
    sd = SessionData({k: v.copy() for k, v in base.cols.items()}, L, base.provenance)
    fn(sd.cols)
    return sd


def bounds(c):
    ln = c["lap_number"]
    return [i for i in range(1, len(ln)) if ln[i] != ln[i - 1]]


def dist_lags_behind(c):            # the new lap number is out one sample BEFORE the distance wraps (real LMU)
    for b in bounds(c):
        c["lap_dist_m"][b] = c["lap_dist_m"][b - 1] + 0.5


def dist_lags_behind_3(c):
    for b in bounds(c):
        for k in range(3):
            c["lap_dist_m"][b + k] = L - 2 + 0.4 * k


def lap_number_lags_behind(c):      # the distance wraps 2 samples BEFORE the lap number changes
    for b in bounds(c):
        c["lap_number"][b - 2:b] = c["lap_number"][b]


@pytest.mark.parametrize("defect", [dist_lags_behind, dist_lags_behind_3, lap_number_lags_behind])
def test_start_line_race_between_lap_counter_and_distance_keeps_the_laps_usable(base, defect):
    sd = mutated(base, defect)
    laps = [l for l in segment_laps(sd) if l.valid_for_analysis]
    assert len(laps) >= 4, [(l.number, l.status, l.reasons) for l in segment_laps(sd)]
    ref, lap = align_lap(sd, laps[0]), align_lap(sd, laps[2])
    assert ref.quality["ok"] and lap.quality["ok"], (ref.quality, lap.quality)
    assert ref.quality["coverage"] > 0.99 and ref.quality["dropped_backwards"] <= 3
    res = compare(lap, ref, detect_corners(ref))
    assert abs(res["total_delta_s"]) < 0.2                         # same synthetic lap: no phantom time difference


def test_game_last_lap_time_published_late_does_not_give_two_laps_the_same_time(base):
    """Real data: laps 1 and 2 both read 1:55.425 to the millisecond - the first samples of a lap still carry the previous lap's value."""
    b = bounds(base.cols)[1]                                              # first sample of lap 3: it carries lap 2's time
    settled = float(base.cols["last_lap_time_s"][b + 100])

    def stale(c):
        c["last_lap_time_s"][b:b + 40] = 57.0                             # old value, shown for 40 samples before the game updates it
    lap2 = {l.number: l for l in segment_laps(mutated(base, stale))}[2]
    assert lap2.time_s == pytest.approx(settled, abs=0.001) and lap2.time_source == "game_last_lap_time"


def test_game_time_that_disagrees_with_the_clock_is_not_trusted(base):
    def wrong(c):
        b = bounds(c)[1]
        c["last_lap_time_s"][b:] = 80.0                                  # nonsense for the whole next lap
    sd = mutated(base, wrong)
    lap2 = {l.number: l for l in segment_laps(sd)}[2]
    assert lap2.time_s == pytest.approx(59.1, abs=0.1) and lap2.time_source == "computed_from_session_time"
    assert any(n.startswith("game_time_mismatch") for n in lap2.notes)


def test_a_short_poller_stall_is_a_note_not_a_reason_to_discard_the_lap(base):
    def stall(c):
        t = c["session_time_s"]
        b = bounds(c)[0]                                                  # first sample of lap 2
        t[b + 3000:] += 0.18                                              # 0.18 s without samples in the middle of lap 2 (real: lap 4)
    sd = mutated(base, stall)
    lap2 = {l.number: l for l in segment_laps(sd)}[2]
    assert lap2.valid_for_analysis and lap2.status == "complete", lap2.reasons
    assert any(n.startswith("time_gap") for n in lap2.notes)


def test_a_long_gap_still_invalidates_the_lap(base):
    def hole(c):
        t = c["session_time_s"]
        b = bounds(c)[0]
        t[b + 3000:] += 1.5
    lap2 = {l.number: l for l in segment_laps(mutated(base, hole))}[2]
    assert not lap2.valid_for_analysis and any(r.startswith("time_gap") for r in lap2.reasons)


# ---- API level: what the user saw on screen (Lap Analyzer error, Track Analysis with an empty "confirmed" profile) ----
def _client_with_session(tmp_path, monkeypatch, defect):
    from fastapi.testclient import TestClient
    from race_engineer.analysis import laps as laps_mod
    from race_engineer.api import app as app_mod
    from race_engineer.lmu.discovery import LmuInstall
    cat = Catalog(tmp_path / "c.sqlite")
    g = SyntheticGame("constant", laps=5)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
    while g.step():
        e.poll_once()
    e.stop()
    row = cat.list_sessions()[0]
    real = laps_mod.load_session

    def patched(path, tl):
        sd = real(path, tl or L)
        defect(sd.cols)
        return sd
    monkeypatch.setattr(app_mod, "load_session", patched)
    return TestClient(app_mod.create_app(e, cat, install=LmuInstall()), base_url="http://127.0.0.1", raise_server_exceptions=False), row, cat


@pytest.mark.parametrize("defect", [dist_lags_behind, dist_lags_behind_3, lap_number_lags_behind])
def test_api_compare_and_corners_work_with_the_start_line_defect(tmp_path, monkeypatch, defect):
    c, row, cat = _client_with_session(tmp_path, monkeypatch, defect)
    sid = row["id"]
    ls = c.get(f"/api/sessions/{sid}/laps").json()["laps"]
    ok = [l["number"] for l in ls if l["valid_for_analysis"]]
    assert len(ok) >= 3
    for ep, q in (("compare", f"lap={ok[1]}&ref={ok[0]}"), ("driving", f"lap={ok[1]}&ref={ok[0]}"), ("corners", f"ref={ok[0]}"), ("trace", f"laps={ok[1]},{ok[0]}&step=2")):
        r = c.get(f"/api/sessions/{sid}/{ep}?{q}")
        assert r.status_code == 200, (ep, r.status_code, r.text[:200])
    assert len(c.get(f"/api/sessions/{sid}/corners?ref={ok[0]}").json()["corners"]) >= 1
    cat.close()


def test_unusable_lap_gives_a_readable_error_never_a_silent_empty_result(tmp_path, monkeypatch):
    def wreck(cols):
        cols["lap_dist_m"][:] = np.linspace(0, 5, len(cols["lap_dist_m"]))      # distance never advances: no lap can be aligned
    c, row, cat = _client_with_session(tmp_path, monkeypatch, wreck)
    r = c.get(f"/api/sessions/{row['id']}/corners")
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    cat.close()


def test_empty_track_profile_is_refused_and_an_old_empty_one_counts_as_absent(tmp_path):
    from fastapi.testclient import TestClient
    from race_engineer.api.app import create_app
    from race_engineer.lmu.discovery import LmuInstall
    cat = Catalog(tmp_path / "c.sqlite")
    cat.put_track_profile("Monza", [])                                  # what older versions stored when the user pressed Save on an empty table
    assert cat.get_track_profile("Monza") is None
    g = SyntheticGame("constant", laps=2)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
    c = TestClient(create_app(e, cat, install=LmuInstall()), base_url="http://127.0.0.1", raise_server_exceptions=False)
    r = c.put("/api/tracks/profile?track=Monza", json=[])
    assert r.status_code == 422 and "Nessuna curva" in r.json()["detail"]
    assert c.get("/api/tracks/profile?track=Monza").json()["corners"] is None
    cat.close()
