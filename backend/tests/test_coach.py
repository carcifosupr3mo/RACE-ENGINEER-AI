"""Coach: instructions, lifecycle, memory (persistence, habits, re-assessment), comparability, review, preferences. SYNTHETIC data only."""
import json

from fastapi.testclient import TestClient

from race_engineer.live import instructions as ins
from race_engineer.live.coach import comparable, lap_conditions, magnitude
from race_engineer.storage.catalog import Catalog
from race_engineer.storage.coach_memory import CoachMemory

from .test_live_engineer import FAST, H, run


ALL_TYPES = ["early_braking", "inefficient_late_braking", "braking_too_long", "abrupt_release", "delayed_acceleration", "insufficient_min_speed",
             "inefficient_line", "insufficient_trail_braking", "excess_trail_braking", "aggressive_throttle", "gear_choice", "entry_loss", "mid_loss",
             "exit_loss", "inconsistent"]
EV = {"diff_m": 12.0, "min_speed_diff_kmh": -3.0, "lap_len_m": 80.0, "ref_len_m": 60.0, "lap_throttle_on_m": 10.0, "ref_throttle_on_m": 1.0, "diff_kmh": 4.0,
      "lap_min_kmh": 80, "ref_min_kmh": 84, "ratio": 1.2, "lap_trail_m": 5.0, "ref_trail_m": 30.0, "lap_ramp_m": 10.0, "ref_ramp_m": 40.0, "ref_gear": 3.0,
      "lap_gear": 2.0, "phase_delta_s": 0.12, "brake_std_m": 6.0, "laps": 5}


def cand(type_, level="alta"):
    return {"id": f"P2.{type_}", "corner": "P2", "type": type_, "label": type_, "phase": "entry", "impact_s": 0.15, "confidence": {"level": level},
            "lap": 3, "ref_lap": 1, "evidence": dict(EV)}


def test_every_type_produces_a_complete_instruction_without_inventing_distances():
    for t in ALL_TYPES:
        hi, lo = ins.build(cand(t, "alta")), ins.build(cand(t, "bassa"))
        for k in ("headline", "what", "how", "why", "goal", "text", "corner_label", "evidence", "confidence"):
            assert hi[k] not in (None, ""), (t, k)
        assert hi["language"] == "it" and hi["corner_label"] == "CURVA P2" and hi["text"].startswith("CURVA P2")
        assert any("provvisoria" in m for m in hi["evidence"]["missing"])
        assert any("traffico" in m for m in hi["evidence"]["missing"])
        # low confidence: no metre figures in the wording
        assert " m" not in (lo["how"] + lo["why"]).replace("m ", " m ").replace("misura", "").replace("minima", "") or " m." not in lo["how"], t
        assert any("confidenza bassa" in m for m in lo["evidence"]["missing"])
    assert "circa 12 m" in ins.build(cand("early_braking", "alta"))["how"]
    assert "circa" not in ins.build(cand("early_braking", "bassa"))["how"]


def test_magnitude_is_a_nonnegative_measure():
    assert magnitude({"type": "early_braking", "evidence": {"diff_m": -9.0}}) == 9.0
    assert magnitude({"type": "gear_choice", "evidence": {}}) is None
    assert magnitude({"type": "aggressive_throttle", "evidence": {"lap_ramp_m": 10, "ref_ramp_m": 40}}) == 30


def test_comparability_rules():
    ref = {"rain": 0.0, "track_temp_c": 30.0, "fuel_l": 60.0, "wear": 0.1}
    assert comparable({"rain": 0.0, "track_temp_c": 31.0, "fuel_l": 55.0, "wear": 0.12}, ref)["ok"]
    r = comparable({"rain": 0.5, "track_temp_c": 30.0, "fuel_l": 60.0, "wear": 0.1}, ref)
    assert not r["ok"] and r["reasons"]
    assert not comparable({"rain": 0.0, "track_temp_c": 42.0, "fuel_l": 60.0, "wear": 0.1}, ref)["ok"]
    w = comparable({"rain": 0.0, "track_temp_c": 30.0, "fuel_l": 20.0, "wear": 0.1}, ref)
    assert w["ok"] and w["warnings"]
    u = comparable({"rain": None, "track_temp_c": None}, ref)
    assert u["ok"] and u["missing"]                     # unknown conditions are reported, never blocking
    assert lap_conditions({"rain": [0.0, 0.2]})["rain"] == 0.1


def test_lifecycle_on_mixed_session_and_review(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, scenario="repeated", laps=10, observe=40)
    mem = live.coach.mem
    tips = mem.recent_tips(live.coach.track, live.coach.vehicle, True, 100)
    assert tips, "tips must be recorded"
    assert all(t["synthetic"] == 1 for t in tips)
    states = {t["status"] for t in tips}
    assert states <= {"nuovo", "mostrato", "applicato", "da_rivalutare", "non_verificabile"}
    assert "applicato" in states, "a corrected problem must be recognised as applied"
    ap = [t for t in tips if t["status"] == "applicato"][0]
    assert ap["outcome"] == "seguito_migliorato" and ap["shown_lap"] is not None
    hb = mem.habits(live.coach.track, live.coach.vehicle, True)
    assert hb and {h["classification"] for h in hb} <= {"nuovo", "occasionale", "abitudine", "corretto"}
    assert any(h["classification"] == "corretto" for h in hb)
    # only ONE main instruction at a time and coherent with the short suggestion
    for s in snaps:
        m = s["suggestion"]["main"]
        if m:
            assert s["suggestion"]["main"].get("instruction") is None or s["suggestion"]["main"]["instruction"]["corner"] == m["corner"]
    rv = live.last_review
    assert rv and rv["synthetic"] is True and rv["summary"].startswith("GIRO")
    assert "driver" not in json.dumps(rv).lower()
    assert rv["comparable"]["ok"] and rv["missing"]
    assert mem.laps_analysed(live.coach.track, live.coach.vehicle, True) >= 3
    assert not live.errors, live.errors
    # synthetic memory is separate from real memory
    assert mem.recent_tips(live.coach.track, live.coach.vehicle, False) == []
    assert mem.habits(live.coach.track, live.coach.vehicle, False) == []
    e.stop()


def test_single_lap_error_is_not_advised(tmp_path, catalog):
    """mixed = one early-braking lap and one late-throttle lap, each ONCE: lap-to-lap noise, so no instruction may be created."""
    g, e, app, live, snaps = run(tmp_path, catalog, scenario="mixed", laps=8, observe=40)
    assert live.coach.mem.recent_tips(live.coach.track, live.coach.vehicle, True) == []
    assert all(s["suggestion"]["main"] is None for s in snaps)
    e.stop()


def test_improvement_needs_a_confirming_lap_before_applied(catalog):
    from race_engineer.live.coach import Coach
    co = Coach(catalog, lambda: 1000.0)
    co.bind("s", "T", "V", True)
    tid = co.mem.new_tip(session_id="s", track="T", vehicle="V", synthetic=True, corner="P1", type_="early_braking", lap=1, confidence="media",
                         impact_s=0.2, mag=10.0, instruction={"headline": "x", "corner_label": "CURVA P1"})
    co._tips["P1.early_braking"] = tid
    co.mem.mark_shown(tid, 1)
    ok = {"ok": True, "verified": True, "reasons": [], "warnings": [], "missing": []}
    e1 = co.lap_closed({"findings": [], "corners": []}, lap=2, comp=ok)
    assert e1[0]["outcome"] == "miglioramento_osservato" and co.mem.tip(tid)["status"] == "mostrato"      # one lap could be luck
    assert co.mem.habit("T", "V", True, "P1", "early_braking")["classification"] != "corretto"
    e2 = co.lap_closed({"findings": [], "corners": []}, lap=3, comp=ok)
    assert e2[0]["status"] == "applicato" and co.mem.tip(tid)["outcome"] == "seguito_migliorato"


def test_unknown_conditions_are_not_verifiable_and_cap_confidence(catalog):
    from race_engineer.live.coach import Coach, cap_confidence
    unknown = comparable({"rain": 0.0, "track_temp_c": 30.0}, None)
    assert unknown["ok"] and unknown["verified"] is False
    res = {"findings": [{"confidence": {"level": "alta", "score": 0.9, "reasons": []}}]}
    cap_confidence(res, unknown)
    assert res["findings"][0]["confidence"]["level"] == "media"
    co = Coach(catalog, lambda: 1000.0)
    co.bind("s", "T", "V", True)
    tid = co.mem.new_tip(session_id="s", track="T", vehicle="V", synthetic=True, corner="P1", type_="early_braking", lap=1, confidence="media",
                         impact_s=0.2, mag=10.0, instruction={"headline": "x", "corner_label": "CURVA P1"})
    co._tips["P1.early_braking"] = tid
    co.mem.mark_shown(tid, 1)
    ev = co.lap_closed({"findings": [], "corners": []}, lap=2, comp=unknown)
    assert ev[0]["outcome"] == "non_verificabile" and co.mem.tip(tid)["evaluations"] == 0       # never judged on an unverifiable comparison


def test_memory_persists_across_restart(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, scenario="repeated", laps=8)
    tr, ve = live.coach.track, live.coach.vehicle
    n_tips, n_habits, n_laps = len(live.coach.mem.recent_tips(tr, ve, True)), len(live.coach.mem.habits(tr, ve, True)), live.coach.mem.laps_analysed(tr, ve, True)
    live.coach.mem.set_prefs({"min_confidence": "media", "verbosity": "breve"})
    e.stop()
    cat2 = Catalog(tmp_path / "catalog.sqlite")
    try:
        mem2 = CoachMemory(cat2)
        assert len(mem2.recent_tips(tr, ve, True)) == n_tips > 0
        assert len(mem2.habits(tr, ve, True)) == n_habits
        assert mem2.laps_analysed(tr, ve, True) == n_laps >= 1
        assert mem2.prefs()["min_confidence"] == "media" and mem2.prefs()["verbosity"] == "breve"
        assert mem2.progress(tr, ve, True) and mem2.summary(tr, ve, True)["laps_analysed"] == n_laps
    finally:
        cat2.close()


def test_habit_classification_and_real_synthetic_separation(catalog):
    mem = CoachMemory(catalog, clock=lambda: 1000.0)
    for lap in range(1, 6):
        mem.save_lap("s1", lap, "T", "V", True, 90.0, 0.0, 1, {})
    assert mem.habit("T", "V", True, "P1", "early_braking")["classification"] == "nuovo"
    mem.seen("T", "V", True, "s1", "P1", "early_braking", 0.1)
    assert mem.habit("T", "V", True, "P1", "early_braking")["classification"] == "occasionale"
    for _ in range(3):
        mem.seen("T", "V", True, "s1", "P1", "early_braking", 0.1)
    assert mem.habit("T", "V", True, "P1", "early_braking")["classification"] == "abitudine"
    assert mem.habit("T", "V", False, "P1", "early_braking")["classification"] == "nuovo"      # real data never mixes with synthetic
    mem.mark_fixed("T", "V", True, "P1", "early_braking")
    assert mem.habit("T", "V", True, "P1", "early_braking")["classification"] == "corretto"
    mem.seen("T", "V", True, "s1", "P1", "early_braking", 0.1)                                   # it came back
    assert mem.habit("T", "V", True, "P1", "early_braking")["classification"] != "corretto"


def test_prefs_validation(catalog):
    mem = CoachMemory(catalog)
    p = mem.set_prefs({"min_confidence": "nonsense", "verbosity": "breve", "show_review_s": 9999, "max_tips_per_corner": 2})
    assert p["min_confidence"] == "bassa" and p["verbosity"] == "breve" and p["show_review_s"] == 25 and p["max_tips_per_corner"] == 2


def test_opposite_advice_is_suppressed_unless_confidence_is_high(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=3)
    co = live.coach
    tid = co.mem.new_tip(session_id=co.sid, track=co.track, vehicle=co.vehicle, synthetic=True, corner="P9", type_="early_braking", lap=2,
                         confidence="media", impact_s=0.2, mag=10.0, instruction={"headline": "x"})
    co.mem.mark_shown(tid, 2)
    co.lap_now = 3

    class C:
        def __init__(self, level):
            self.type, self.corner, self.confidence = "inefficient_late_braking", "P9", {"level": level}
    assert co._suppressed_by_opposite(C("media")) is True
    assert co._suppressed_by_opposite(C("alta")) is False
    co.lap_now = 9
    assert co._suppressed_by_opposite(C("media")) is False       # outside the window
    e.stop()


def test_min_confidence_preference_filters_candidates(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=6)
    live.coach.mem.set_prefs({"min_confidence": "alta"})

    class C:
        def __init__(self, level):
            self.type, self.corner, self.key, self.score, self.confidence = "early_braking", "P1", "P1.early_braking", 1.0, {"level": level}
    out = live.coach.decorate([C("bassa"), C("media"), C("alta")])
    assert [c.confidence["level"] for c in out] == ["alta"]
    e.stop()


def test_reassessment_after_repeated_unfollowed_advice(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=3)
    co = live.coach
    f = {"corner": "P7", "type": "early_braking", "label": "x", "time_impact_s": 0.2, "evidence": {"diff_m": 10.0}}
    tid = co.mem.new_tip(session_id=co.sid, track=co.track, vehicle=co.vehicle, synthetic=True, corner="P7", type_="early_braking", lap=1,
                         confidence="alta", impact_s=0.2, mag=10.0, instruction={"headline": "FRENA", "corner_label": "CURVA P7"})
    co._tips["P7.early_braking"] = tid
    co.mem.mark_shown(tid, 1)
    ok = {"ok": True, "verified": True, "reasons": [], "warnings": [], "missing": []}
    ev1 = co.lap_closed({"findings": [f], "corners": []}, lap=2, comp=ok)
    ev1 = [x for x in ev1 if x["tip_id"] == tid]
    assert ev1[0]["outcome"] == "non_seguito" and ev1[0]["status"] == "mostrato"
    ev2 = [x for x in co.lap_closed({"findings": [f], "corners": []}, lap=3, comp=ok) if x["tip_id"] == tid]
    assert ev2[0]["status"] == "da_rivalutare"
    class C:
        type, corner, key, score, confidence = "early_braking", "P7", "P7.early_braking", 1.0, {"level": "alta"}
    out = co.decorate([C])
    assert out[0].reassess and out[0].score == 0.4                  # not repeated forever: lower priority
    i = co.instruction(cand("early_braking") | {"corner": "P7", "id": "P7.early_braking"}, corner=None, mode={}, rel={}, reassess=True)
    assert "meno priorità" in i["reassessment"]
    e.stop()


def test_non_comparable_lap_does_not_judge_tips(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=3)
    co = live.coach
    tid = co.mem.new_tip(session_id=co.sid, track=co.track, vehicle=co.vehicle, synthetic=True, corner="P5", type_="early_braking", lap=1,
                         confidence="alta", impact_s=0.2, mag=10.0, instruction={"headline": "FRENA", "corner_label": "CURVA P5"})
    co._tips["P5.early_braking"] = tid
    co.mem.mark_shown(tid, 1)
    bad = {"ok": False, "reasons": ["pioggia diversa"], "warnings": [], "missing": []}
    for lap in (2, 3, 4):
        ev = [x for x in co.lap_closed({"findings": [], "corners": []}, lap=lap, comp=bad) if x["tip_id"] == tid]
        assert ev[0]["outcome"] == "non_confrontabile"
    t = co.mem.tip(tid)
    assert t["status"] == "non_verificabile" and t["skipped"] == 3 and t["evaluations"] == 0
    e.stop()


def test_never_shown_tip_is_closed_when_problem_vanishes(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=3)
    co = live.coach
    tid = co.mem.new_tip(session_id=co.sid, track=co.track, vehicle=co.vehicle, synthetic=True, corner="P6", type_="gear_choice", lap=1,
                         confidence="media", impact_s=0.1, mag=None, instruction={"headline": "x", "corner_label": "CURVA P6"})
    co.lap_closed({"findings": [], "corners": []}, lap=5, comp={"ok": True, "reasons": [], "warnings": [], "missing": []})
    assert co.mem.tip(tid)["outcome"] == "non_mostrato" and co.mem.tip(tid)["status"] == "non_verificabile"
    e.stop()


def test_coach_api_and_shared_state(tmp_path, catalog):
    g, e, app, live, snaps = run(tmp_path, catalog, laps=6)
    c = TestClient(app)
    s = c.get("/api/coach/summary", headers=H).json()
    assert s["synthetic"] is True and s["laps_analysed"] >= 1 and "tips_by_status" in s
    assert c.get("/api/coach/progress", headers=H).status_code == 200
    assert c.get("/api/coach/tips", headers=H).status_code == 200
    r = c.get("/api/coach/review", headers=H).json()
    assert r.get("summary")
    p = c.put("/api/coach/prefs", json={"min_confidence": "media"}, headers=H).json()
    assert p["min_confidence"] == "media"
    assert c.get("/api/coach/prefs", headers=H).json()["min_confidence"] == "media"
    st = live.snapshot()
    assert "prefs" in st["coach"] and "review" in st      # prefs reach the shared state on the next tick
    e.stop()
