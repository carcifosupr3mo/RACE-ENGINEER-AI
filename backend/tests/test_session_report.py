"""Session report: zones, ideal lap, potential, consistency, advice (synthetic sessions with known, different laps)."""
import pytest
from fastapi.testclient import TestClient

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.analysis.align import align_lap
from race_engineer.analysis.corners import detect_corners
from race_engineer.analysis.laps import load_session, segment_laps
from race_engineer.analysis.report import build_report, build_zones
from race_engineer.api.app import create_app
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame

L = 3000.0


def record(tmp_path, scenario, laps):
    cat = Catalog(tmp_path / f"{scenario}.sqlite")
    g = SyntheticGame(scenario, laps=laps)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path / scenario, process_probe=lambda: True, open_retry_s=0)
    while g.step():
        e.poll_once()
    e.stop()
    return cat, e


def build(tmp_path, scenario, laps):
    cat, _ = record(tmp_path, scenario, laps)
    row = cat.list_sessions()[0]
    sd = load_session(row["data_path"], row["track_length_m"] or L)
    ls = [l for l in segment_laps(sd) if l.valid_for_analysis and l.time_s]
    al = {l.number: align_lap(sd, l) for l in ls}
    al = {n: a for n, a in al.items() if a.quality["ok"]}
    cs = detect_corners(next(iter(al.values())))
    return cat, row, sd, ls, al, cs


def test_zones_cover_the_whole_lap_without_overlap(tmp_path):
    _, _, sd, ls, al, cs = build(tmp_path, "constant", 5)
    zones = build_zones(cs, sd.track_length_m)
    assert zones[0]["start_m"] == 0 and zones[-1]["end_m"] == sd.track_length_m
    for a, b in zip(zones, zones[1:]):
        assert a["end_m"] == pytest.approx(b["start_m"]) and a["end_m"] > a["start_m"]
    assert any(z["kind"] == "corner" for z in zones)


def test_identical_laps_have_no_potential(tmp_path):
    _, _, sd, ls, al, cs = build(tmp_path, "constant", 5)
    rep = build_report(al, {l.number: l.time_s for l in ls if l.number in al}, cs, sd.track_length_m, True)
    assert len(rep["laps"]) >= 3 and rep["best_lap"] in al
    assert rep["ideal_time_s"] <= rep["best_time_s"] and rep["ideal_gain_s"] < 0.05
    assert not rep["advice"]


def test_a_bad_corner_on_one_lap_is_found_and_ideal_lap_beats_best(tmp_path):
    _, _, sd, ls, al, cs = build(tmp_path, "mixed", 5)       # lap 2 brakes early, lap 3 throttles late (different corners)
    times = {l.number: l.time_s for l in ls if l.number in al}
    rep = build_report(al, times, cs, sd.track_length_m, True)
    assert rep["ideal_time_s"] < rep["best_time_s"]           # mixing the best zones beats every real lap
    assert rep["ideal_gain_s"] == pytest.approx(rep["best_time_s"] - rep["ideal_time_s"], abs=1e-3)
    assert rep["advice"] and rep["advice"][0]["gain_s"] >= rep["advice"][-1]["gain_s"]
    bad = [r for r in rep["laps"] if not r["is_best"]]
    assert any(max(x for x in r["zones"] if x is not None) > 0.05 for r in bad)       # the heat map shows where they lose time
    assert rep["consistency"] is None or rep["consistency"]["spread_s"] >= 0


def test_report_endpoint_and_errors(tmp_path):
    cat, e = record(tmp_path, "mixed", 5)
    sid = cat.list_sessions()[0]["id"]
    app = create_app(e, cat, install=LmuInstall())
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get(f"/api/sessions/{sid}/report")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["zones"] and j["laps"] and j["ideal_time_s"] and "note" in j
    assert c.get("/api/sessions/nope/report").status_code == 404
