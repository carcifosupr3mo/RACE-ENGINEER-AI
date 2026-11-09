import pytest

from race_engineer.synthetic.track import SCENARIOS, SyntheticTrack, frames, reference_profile


def lap_times(name, laps=3):
    last = {}
    for f in frames(SyntheticTrack(), SCENARIOS[name], laps=laps):
        last = f
    return last["best_lap"]


def test_reproducible():
    a = [f["speed_ms"] for f in frames(SyntheticTrack(), SCENARIOS["constant"], laps=1)]
    b = [f["speed_ms"] for f in frames(SyntheticTrack(), SCENARIOS["constant"], laps=1)]
    assert a == b


def test_scenario_laptime_ordering_is_known():
    base = lap_times("constant")
    assert lap_times("slower") > base + 0.5
    assert lap_times("early_brake") > base + 0.5
    assert lap_times("late_throttle") > base + 0.2
    assert lap_times("late_brake") < base            # later braking point -> shorter braking zone


def test_constant_laps_are_identical():
    ts = []
    cur = None
    for f in frames(SyntheticTrack(), SCENARIOS["constant"], laps=4):
        if f["last_lap"] > 0 and f["last_lap"] != cur:
            cur = f["last_lap"]; ts.append(cur)
    assert len(ts) >= 3 and max(ts) - min(ts) < 0.05


def test_early_brake_moves_brake_point_by_known_distance():
    t = SyntheticTrack()
    def brake_start(name):
        for f in frames(t, SCENARIOS[name], laps=1):
            if 1000 < f["lap_dist"] < 1300 and f["brake"] > 0.1:
                return f["lap_dist"]
    assert brake_start("constant") - brake_start("early_brake") == pytest.approx(40.0, abs=8.0)


def test_late_throttle_delays_pickup_after_corner_3():
    def thr_pickup(name):
        for f in frames(SyntheticTrack(), SCENARIOS[name], laps=1):
            if f["lap_dist"] > 1800 and f["throttle"] > 0.9:
                return f["lap_dist"]
    assert thr_pickup("late_throttle") - thr_pickup("constant") == pytest.approx(35.0, abs=10.0)


def test_profile_never_exceeds_vmax_and_is_positive():
    v = reference_profile(SyntheticTrack(), SCENARIOS["constant"])
    assert v.min() > 10 and v.max() <= 250 / 3.6 + 1e-9
