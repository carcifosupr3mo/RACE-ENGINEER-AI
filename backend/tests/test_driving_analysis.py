"""Driving analysis (corner phases, whole-corner judgement), personal reference and session adaptation.
SYNTHETIC scenarios with known, quantified differences - never evidence of LMU integration."""
import numpy as np
import pytest

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.analysis.align import align_lap
from race_engineer.analysis.corners import detect_corners
from race_engineer.analysis.driving import analyse, driving_metrics, zones
from race_engineer.analysis.laps import load_session, segment_laps
from race_engineer.analysis.reference import PersonalReference
from race_engineer.analysis.session_mode import classify
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame

CACHE: dict = {}


def laps_for(tmp_path_factory, scenario, laps=5):
    key = (scenario, laps)
    if key not in CACHE:
        d = tmp_path_factory.mktemp("drv")
        cat = Catalog(d / "c.sqlite")
        g = SyntheticGame(scenario, laps=laps)
        e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=d, process_probe=lambda: True, open_retry_s=0)
        while g.step():
            e.poll_once()
        e.stop()
        sd = load_session(cat.list_sessions()[0]["data_path"], 3000.0)
        ok = [l for l in segment_laps(sd) if l.valid_for_analysis]
        CACHE[key] = [align_lap(sd, l) for l in ok]
    return CACHE[key]


@pytest.fixture(scope="module")
def tpf(tmp_path_factory):
    return tmp_path_factory


def types(res, corner=None):
    return {(f["corner"], f["type"]) for f in res["findings"] if corner in (None, f["corner"])}


def test_early_braking_found_with_evidence_and_confidence(tpf):
    al = laps_for(tpf, "mixed")
    ref = al[0]
    cs = detect_corners(ref)
    res = analyse(al[1], ref, cs)                       # lap 2: P2 braked 40 m earlier
    f = next(f for f in res["findings"] if f["type"] == "early_braking")
    assert f["corner"] == "P2" and f["phase"] == "entry"
    assert f["evidence"]["diff_m"] == pytest.approx(-40, abs=3)
    assert f["time_impact_s"] > 0.3 and f["confidence"]["level"] in ("alta", "media", "bassa")
    assert f["provenance"] == "computed" and f["confidence"]["reasons"]


def test_delayed_acceleration_found_in_exit_phase(tpf):
    al = laps_for(tpf, "mixed")
    res = analyse(al[2], al[0], detect_corners(al[0]))   # lap 3: P3 throttle 35 m late
    f = next(f for f in res["findings"] if f["type"] == "delayed_acceleration")
    assert f["corner"] == "P3" and f["phase"] == "exit" and f["evidence"]["diff_m"] == pytest.approx(35, abs=4)


def test_later_braking_is_not_automatically_an_error(tpf):
    """late_brake scenario: later brake point AND harder braking -> same lap time; must NOT be reported as an inefficient late braking."""
    al = laps_for(tpf, "late_brake")
    res = analyse(al[1], al[0], detect_corners(al[0]))
    assert not any(f["type"] in ("inefficient_late_braking", "early_braking") for f in res["findings"])


def test_late_braking_that_loses_the_corner_is_flagged_and_one_that_gains_is_a_gain(tpf):
    al = laps_for(tpf, "constant")
    ref, lap = al[0], al[1]
    cs = detect_corners(ref)
    # craft measured-style variations of a real aligned lap: brake 30 m later AND carry less minimum speed / lose time after
    import copy
    bad = copy.deepcopy(lap)
    c = cs[1]
    g = bad.grid
    # simple deterministic edit: remove the first 30 m of braking (later brake point) and slow the car through the corner
    br = bad.ch["brake"].copy()
    i = int(np.flatnonzero(br[int(c.entry_m) - 10:int(c.apex_m)] > 0.1)[0]) + int(c.entry_m) - 10
    br[i:i + 30] = 0.0
    bad.ch["brake"] = br
    bad.ch["speed_kmh"] = bad.ch["speed_kmh"] - np.where((g > c.apex_m - 40) & (g < c.exit_m), 6.0, 0.0)
    bad.t = bad.t + np.where(g > c.apex_m - 40, np.clip((g - (c.apex_m - 40)) / 80.0, 0, 1) * 0.25, 0.0)
    res = analyse(bad, ref, cs)
    assert (c.id, "inefficient_late_braking") in types(res)
    good = copy.deepcopy(bad)
    good.t = lap.t - np.where(g > c.apex_m - 40, np.clip((g - (c.apex_m - 40)) / 80.0, 0, 1) * 0.15, 0.0)
    good.ch["speed_kmh"] = lap.ch["speed_kmh"]
    res2 = analyse(good, ref, cs)
    assert (c.id, "inefficient_late_braking") not in types(res2)
    assert any(x["type"] == "late_braking_gain" and x["corner"] == c.id for x in res2["gains"])


def test_metrics_cover_all_phases_and_segments_sum_to_zone_delta(tpf):
    al = laps_for(tpf, "mixed")
    ref = al[0]
    cs = detect_corners(ref)
    res = analyse(al[1], ref, cs)
    for row in res["corners"]:
        seg = row["segments"]
        assert all(seg[p]["delta_s"] is not None for p in ("entry", "mid", "exit"))
        assert row["zone_delta_s"] == pytest.approx(sum(seg[p]["delta_s"] for p in seg), abs=0.01)
        m = row["lap"]
        for k in ("brake_start_m", "brake_peak", "brake_release_m", "entry_speed_kmh", "min_speed_kmh", "min_speed_m", "throttle_on_m", "exit_speed_kmh"):
            assert k in m
    dm = driving_metrics(ref, cs[0])
    assert dm.brake_length_m and dm.entry_speed_kmh and dm.throttle_on_m


def test_analysis_is_deterministic_and_reference_vs_itself_is_empty(tpf):
    al = laps_for(tpf, "constant")
    cs = detect_corners(al[0])
    a, b = analyse(al[1], al[0], cs), analyse(al[1], al[0], cs)
    assert a == b
    own = analyse(al[0], al[0], cs)
    assert own["findings"] == [] and own["total_delta_s"] == pytest.approx(0, abs=1e-9)


def test_low_reliability_lowers_confidence(tpf):
    al = laps_for(tpf, "mixed")
    cs = detect_corners(al[0])
    hi = next(f for f in analyse(al[1], al[0], cs, reliability=1.0)["findings"] if f["type"] == "early_braking")
    lo = next(f for f in analyse(al[1], al[0], cs, reliability=0.2)["findings"] if f["type"] == "early_braking")
    assert lo["confidence"]["score"] < hi["confidence"]["score"] and lo["confidence"]["level"] == "bassa"


def test_zones_come_from_measured_reference(tpf):
    al = laps_for(tpf, "constant")
    cs = detect_corners(al[0])
    z = zones(al[0], cs)
    kinds = {x["type"] for x in z}
    assert {"brake", "release", "accel"} <= kinds
    for x in z:
        assert x["to_m"] >= x["from_m"] >= 0


def test_reference_is_progressive_persisted_and_synthetic_is_separate(tpf, tmp_path):
    al = laps_for(tpf, "mixed")
    ref = PersonalReference("T", "V", True, store_dir=tmp_path)
    assert ref.reliability()["learning"] and ref.anchor is None
    for i, a in enumerate(al[:3]):
        ref.add(a, 59.1 + i * 0.3, "s1")
        if i == 0:
            assert ref.reliability()["level"] == "apprendimento"
    r3 = ref.reliability()
    assert not r3["learning"] and r3["n_laps"] == 3 and ref.anchor.number == al[0].number
    v = ref.version
    assert not ref.add(al[3], 99.0, "s1")["accepted"]                 # far too slow: does not refine the reference
    assert ref.version == v
    new = ref.add(al[3], 58.9, "s1")                                    # faster -> new anchor, version bumps
    assert new["new_anchor"] and ref.version == v + 1 and ref.anchor.number == al[3].number
    assert ref.targets() and all(t["best_zone_s"] > 0 for t in ref.targets())
    again = PersonalReference("T", "V", True, store_dir=tmp_path)       # persisted, identical anchor
    assert again.anchor.time_s == pytest.approx(58.9) and again.loaded_from_disk == 4
    real = PersonalReference("T", "V", False, store_dir=tmp_path)       # same track/vehicle, but REAL store is separate from SYNTHETIC
    assert real.anchor is None


def test_reference_rejects_unusable_laps(tpf):
    al = laps_for(tpf, "constant")
    ref = PersonalReference("T", "V", True)
    bad = al[0]
    import copy
    b = copy.deepcopy(bad)
    b.quality = {**b.quality, "ok": False}
    assert not ref.add(b, 59.0)["accepted"] and not ref.add(al[0], 0.0)["accepted"]


def test_session_adaptation_changes_priorities_not_the_engine():
    q, r, e, g = classify("qualifying"), classify("race", 600, 1), classify("race", 4000, 1), classify("something")
    assert q["mode"] == "qualifying" and r["mode"] == "race" and e["mode"] == "endurance" and g["mode"] == "generic" and not g["recognized"]
    assert q["weights"]["pace"] > r["weights"]["pace"] > e["weights"]["pace"]
    assert e["weights"]["resources"] > r["weights"]["resources"]
    assert classify("race", 100, 3)["mode"] == "endurance" and classify("practice")["mode"] == "practice" and classify("test")["mode"] == "test"
    assert classify(None)["mode"] == "generic" and classify("warmup")["mode"] == "practice"


# ---------------------------------------------------------------- trail braking / throttle progression / gear (SYNTHETIC laps edited by a known amount)
def _penalised(lap, c, seconds=0.25, kmh=0.0):
    import copy
    bad = copy.deepcopy(lap)
    g = bad.grid
    bad.t = bad.t + np.clip((g - (c.apex_m - 40)) / 80.0, 0, 1) * seconds
    if kmh:
        bad.ch["speed_kmh"] = bad.ch["speed_kmh"] - np.where((g > c.apex_m - 40) & (g < c.exit_m), kmh, 0.0)
    return bad


def test_insufficient_trail_braking_is_found_when_the_corner_is_slower(tpf):
    al = laps_for(tpf, "constant")
    ref, lap = al[0], al[1]
    cs = detect_corners(ref)
    c = cs[1]
    bad = _penalised(lap, c, 0.25, 6.0)
    br = bad.ch["brake"].copy()
    i0 = int(np.flatnonzero(br[int(c.entry_m) - 10:int(c.apex_m)] > 0.1)[0]) + int(c.entry_m) - 10
    br[i0 + 20:int(c.apex_m) + 1] = 0.0                      # releases the brake 20 m after applying it: no trailing into the corner
    bad.ch["brake"] = br
    res = analyse(bad, ref, cs)
    f = next(f for f in res["findings"] if f["type"] == "insufficient_trail_braking" and f["corner"] == c.id)
    assert f["phase"] == "entry" and f["evidence"]["lap_trail_m"] < 0.4 * f["evidence"]["ref_trail_m"]
    assert f["provenance"] == "computed" and f["confidence"]["reasons"]
    assert dm_trail(ref, c) >= 12.0


def dm_trail(lap, c):
    return driving_metrics(lap, c).trail_m


def test_trail_findings_do_not_contradict_release_findings(tpf):
    """A corner already flagged 'braking too long' must not also be told to trail longer."""
    al = laps_for(tpf, "constant")
    ref, lap = al[0], al[1]
    cs = detect_corners(ref)
    c = cs[1]
    bad = _penalised(lap, c, 0.3, 5.0)
    br = bad.ch["brake"].copy()
    br[int(c.apex_m):int(c.apex_m) + 40] = np.maximum(br[int(c.apex_m):int(c.apex_m) + 40], 0.5)   # holds the brake well past the reference release
    bad.ch["brake"] = br
    res = analyse(bad, ref, cs)
    kinds = {f["type"] for f in res["findings"] if f["corner"] == c.id}
    assert not ({"braking_too_long", "abrupt_release"} & kinds and "insufficient_trail_braking" in kinds)


def test_aggressive_throttle_needs_a_progressive_reference_and_a_slower_exit(tpf):
    import copy
    al = laps_for(tpf, "constant")
    cs = detect_corners(al[0])
    c = cs[1]
    ref = copy.deepcopy(al[0])
    m0 = driving_metrics(al[0], c)
    k = int(m0.base.min_speed_m)
    th = ref.ch["throttle"].copy()
    th[k:k + 60] = np.clip(np.linspace(0.1, 1.0, 60), 0, 1)           # a reference that opens the throttle progressively over ~60 m
    th[k + 60:int(c.exit_m) + 60] = 1.0
    ref.ch["throttle"] = th
    assert driving_metrics(ref, c).throttle_ramp_m >= 12.0
    lap = _penalised(al[1], c, 0.4, 4.0)                                # the lap snaps the throttle open (step) and exits slower
    res = analyse(lap, ref, cs)
    assert any(f["type"] == "aggressive_throttle" and f["corner"] == c.id and f["phase"] == "exit" for f in res["findings"])
    clean = analyse(al[1], al[0], cs)                                   # on the unmodified synthetic laps the ramp is 0 m: no invented finding
    assert not any(f["type"] == "aggressive_throttle" for f in clean["findings"])


def test_gear_choice_is_reported_only_with_a_measured_loss(tpf):
    al = laps_for(tpf, "constant")
    ref = al[0]
    cs = detect_corners(ref)
    c = cs[1]
    k = int(driving_metrics(ref, c).base.min_speed_m)
    lap = _penalised(al[1], c, 0.0, 0.0)
    gr = lap.ch["gear"].copy()
    gr[k - 5:k + 6] = gr[k] + 1
    lap.ch["gear"] = gr
    assert not any(f["type"] == "gear_choice" for f in analyse(lap, ref, cs)["findings"])       # different gear, but no time/speed lost: silent
    slow = _penalised(lap, c, 0.2, 5.0)
    f = next(f for f in analyse(slow, ref, cs)["findings"] if f["type"] == "gear_choice" and f["corner"] == c.id)
    assert f["evidence"]["lap_gear"] == f["evidence"]["ref_gear"] + 1
