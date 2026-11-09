"""Analyzer validated on SYNTHETIC scenarios with known, quantified differences."""
from pathlib import Path

import numpy as np
import pytest

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.analysis.align import align_lap, delta_time
from race_engineer.analysis.compare import compare, consistency, corner_metrics
from race_engineer.analysis.corners import detect_corners
from race_engineer.analysis.laps import load_session, segment_laps, summarize
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame
from race_engineer.synthetic.track import SCENARIOS, Scenario

CACHE: dict = {}


def record(tmp_path_factory, scenario, laps=4):
    key = (scenario if isinstance(scenario, str) else scenario.name, laps)
    if key in CACHE:
        return CACHE[key]
    d = tmp_path_factory.mktemp("an")
    cat = Catalog(d / "c.sqlite")
    g = SyntheticGame(scenario, laps=laps)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=d, process_probe=lambda: True, open_retry_s=0)
    while g.step():
        e.poll_once()
    e.stop()
    s = cat.list_sessions()[0]
    sd = load_session(s["data_path"], 3000.0)
    CACHE[key] = (sd, segment_laps(sd))
    return CACHE[key]


@pytest.fixture(scope="module")
def tpf(tmp_path_factory):
    return tmp_path_factory


def test_lap_segmentation_and_times(tpf):
    sd, laps = record(tpf, "constant")
    assert [l.status for l in laps] == ["complete"] * 3 + ["incomplete"]
    assert laps[-1].reasons == ["lap_not_closed"] and laps[0].time_source == "game_last_lap_time"
    s = summarize(laps)
    assert s["laps_valid"] == 3 and s["std_time_s"] < 0.02 and s["best_time_s"] == pytest.approx(59.1, abs=0.02)


def test_pit_and_invalid_laps_excluded(tpf):
    sd, laps = record(tpf, "constant")
    sd2 = type(sd)({k: v.copy() for k, v in sd.cols.items()}, sd.track_length_m, sd.provenance)
    l1, l2 = laps[0], laps[1]
    sd2.cols["lap_invalidated"][l1.i0 + 10] = 1
    sd2.cols["in_pits"][l2.i0 + 10] = 1
    laps2 = segment_laps(sd2)
    assert laps2[0].status == "invalid" and not laps2[0].valid_for_analysis
    assert laps2[1].status == "complete" and "pit_lane" in laps2[1].reasons and not laps2[1].valid_for_analysis
    assert summarize(laps2)["laps_valid"] == 1


def test_missing_samples_make_lap_non_analyzable_when_gap_large(tpf):
    sd, laps = record(tpf, "constant")
    sd2 = type(sd)({k: v.copy() for k, v in sd.cols.items()}, sd.track_length_m, sd.provenance)
    l = laps[1]
    for k, v in sd2.cols.items():
        sd2.cols[k] = np.delete(v, np.arange(l.i0 + 1000, l.i0 + 1400))   # ~ 4 s hole
    laps2 = segment_laps(sd2)
    assert laps2[1].status == "incomplete" and any(r.startswith("distance_gap") for r in laps2[1].reasons)


def test_alignment_uses_distance_and_delta_is_zero_for_identical_laps(tpf):
    sd, laps = record(tpf, "constant")
    a, b = align_lap(sd, laps[0]), align_lap(sd, laps[1])
    assert a.quality["ok"] and b.quality["ok"]
    d = delta_time(b, a)
    assert np.nanmax(np.abs(d)) < 0.03


def test_corner_detection_matches_known_apexes(tpf):
    sd, laps = record(tpf, "constant")
    cs = detect_corners(align_lap(sd, laps[1]))
    assert [c.id for c in cs] == ["P1", "P2", "P3", "P4"] and all(c.provisional for c in cs)
    for c, apex in zip(cs, (600, 1300, 1800, 2400)):
        assert c.apex_m == pytest.approx(apex, abs=5)


def run_vs_ref(tpf, scenario):
    sd_c, laps_c = record(tpf, "constant")
    ref = align_lap(sd_c, laps_c[1])
    cs = detect_corners(ref)
    sd, laps = record(tpf, scenario)
    lap = align_lap(sd, laps[1])
    return compare(lap, ref, cs), cs


def types(res):
    return {(f["type"], f["corner"]) for f in res["findings"]}


def test_early_braking_detected_with_correct_magnitude(tpf):
    res, _ = run_vs_ref(tpf, "early_brake")
    f = next(f for f in res["findings"] if f["type"] == "early_braking" and f["corner"] == "P2")
    assert f["evidence"]["diff_m"] == pytest.approx(-40, abs=8)
    assert f["time_impact_s"] > 0.5
    assert res["total_delta_s"] == pytest.approx(1.83, abs=0.15)
    assert not any(t == "early_braking" and c != "P2" for t, c in types(res))   # no false positives elsewhere


def test_late_throttle_detected(tpf):
    res, _ = run_vs_ref(tpf, "late_throttle")
    f = next(f for f in res["findings"] if f["type"] == "late_throttle")
    assert f["corner"] == "P3" and f["evidence"]["diff_m"] == pytest.approx(35, abs=10)


def test_slower_pace_flags_only_corners_above_threshold(tpf):
    res, cs = run_vs_ref(tpf, "slower")
    flagged = {c for t, c in types(res) if t == "low_min_speed"}
    # apex speeds drop 3%: P1 -2.7, P3 -3.6 km/h flagged; P2 -1.8 km/h is below the 2 km/h threshold
    assert {"P1", "P3"} <= flagged and "P2" not in flagged
    assert res["total_delta_s"] > 0.5


def test_late_brake_detected_as_later_braking(tpf):
    res, _ = run_vs_ref(tpf, "late_brake")
    assert any(t == "late_braking" for t, _ in types(res)) and res["total_delta_s"] < 0


def test_constant_lap_has_no_findings(tpf):
    sd, laps = record(tpf, "constant")
    ref = align_lap(sd, laps[0])
    cs = detect_corners(ref)
    res = compare(align_lap(sd, laps[2]), ref, cs)
    assert res["findings"] == []


def test_consistency_of_constant_laps_is_near_zero(tpf):
    sd, laps = record(tpf, "constant")
    al = [align_lap(sd, l) for l in laps[:3]]
    cons = consistency(al, detect_corners(al[0]))
    assert all(c["min_speed_std_kmh"] < 0.5 for c in cons)


def test_incomplete_telemetry_leaves_metrics_none_not_invented(tpf):
    sd, laps = record(tpf, "constant")
    sd2 = type(sd)({k: v.copy() for k, v in sd.cols.items()}, sd.track_length_m, sd.provenance)
    sd2.cols["brake"][:] = np.nan
    al = align_lap(sd2, laps[1])
    ref = align_lap(sd, laps[1])
    m = corner_metrics(al, detect_corners(ref)[0])
    assert m.brake_start_m is None and m.brake_peak in (None, 0.0) or np.isnan(m.brake_peak)


# ---------------------------------------------------------------- API + import (Phase 2/3)
from fastapi.testclient import TestClient

from race_engineer.api.app import create_app
from race_engineer.importers.session_import import import_lmu_duckdb
from race_engineer.lmu.discovery import LmuInstall
from race_engineer.synthetic.lmu_duckdb_fixture import build


def _app(tmp_path, scenario_sessions):
    cat = Catalog(tmp_path / "c.sqlite")
    ids = []
    for sc in scenario_sessions:
        g = SyntheticGame(sc, laps=4)
        e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=tmp_path, process_probe=lambda: True, open_retry_s=0)
        while g.step():
            e.poll_once()
        e.stop()
    e2 = AcquisitionEngine(lambda: None, catalog=cat, data_root=tmp_path, record=False)
    app = create_app(e2, cat, install=LmuInstall(), allowed_import_dirs=[tmp_path])
    return TestClient(app, base_url="http://127.0.0.1"), cat


def test_api_laps_compare_corners_profile(tmp_path):
    c, cat = _app(tmp_path, ["early_brake"])
    sid = cat.list_sessions()[0]["id"]
    laps = c.get(f"/api/sessions/{sid}/laps").json()
    assert laps["summary"]["laps_valid"] == 3
    cr = c.get(f"/api/sessions/{sid}/corners").json()
    assert cr["provisional"] is True and len(cr["corners"]) == 4
    cmp_ = c.get(f"/api/sessions/{sid}/compare", params={"lap": 2, "ref": 1}).json()
    assert cmp_["findings"] == [] and cmp_["corners_provisional"] is True          # same scenario, same laps
    tr = c.get(f"/api/sessions/{sid}/trace", params={"laps": "1,2"}).json()
    assert len(tr["distance_m"]) == len(tr["laps"]["1"]["speed_kmh"]) == 600
    assert c.get(f"/api/sessions/{sid}/consistency").status_code == 200
    # manual profile replaces provisional ids
    prof = [{"id": "T1", "name": "Test hairpin", "apex_m": 600, "entry_m": 450, "exit_m": 750}]
    assert c.put("/api/tracks/profile", params={"track": cr and laps["session"]["track"]}, json=prof).json()["ok"]
    cr2 = c.get(f"/api/sessions/{sid}/corners").json()
    assert cr2["provisional"] is False and cr2["corners"][0]["id"] == "T1"
    assert c.put("/api/tracks/profile", params={"track": "x"}, json=[{"id": "bad"}]).status_code == 422
    assert c.get("/api/sessions/nope/laps").status_code == 404


def test_import_native_duckdb_as_session_and_analyze(tmp_path):
    src = build(tmp_path / "lmu.duckdb", scenario="late_throttle", laps=4)
    import hashlib
    h = hashlib.sha256(src.read_bytes()).hexdigest()
    cat = Catalog(tmp_path / "c.sqlite")
    r = import_lmu_duckdb(src, cat, tmp_path, track_length_m=3000.0)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == h                    # original untouched
    s = cat.get_session(r["session_id"])
    assert s["source"] == "duckdb_import" and s["status"] == "complete" and r["warnings"]
    sd = load_session(s["data_path"], 3000.0)
    assert set(sd.cols["provenance"]) == {"duckdb_import"}
    ls = segment_laps(sd)
    assert sum(l.valid_for_analysis for l in ls) >= 2 and ls[0].time_s == pytest.approx(59.65, abs=0.2)
    assert np.isnan(sd.cols["fuel_l"]).sum() == 0 and np.nanmax(sd.cols["throttle"]) <= 1.0


def test_import_rejects_files_without_laps(tmp_path):
    src = build(tmp_path / "x.duckdb", drop_channels=("Lap Dist",))
    with pytest.raises(ValueError):
        import_lmu_duckdb(src, Catalog(tmp_path / "c.sqlite"), tmp_path)


def test_mixed_session_findings_per_lap(tpf):
    sd, laps = record(tpf, "mixed", laps=4)
    ref = align_lap(sd, laps[0])
    cs = detect_corners(ref)
    r2 = compare(align_lap(sd, laps[1]), ref, cs)
    r3 = compare(align_lap(sd, laps[2]), ref, cs)
    assert ("early_braking", "P2") in types(r2) and not any(t == "late_throttle" for t, _ in types(r2))
    assert ("late_throttle", "P3") in types(r3) and not any(t == "early_braking" for t, _ in types(r3))
    cons = consistency([align_lap(sd, l) for l in laps[:3]], cs)
    p2 = next(c for c in cons if c["corner"] == "P2")
    assert p2["brake_start_std_m"] > 10          # inconsistency across laps is measured, not asserted
