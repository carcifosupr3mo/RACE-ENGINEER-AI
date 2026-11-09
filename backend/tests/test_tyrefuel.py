import numpy as np
import pytest

from race_engineer.analysis.laps import segment_laps
from race_engineer.analysis.tyrefuel import fuel_report, tyre_report
from .test_analysis import record


@pytest.fixture(scope="module")
def tpf(tmp_path_factory):
    return tmp_path_factory


def clone(sd):
    return type(sd)({k: v.copy() for k, v in sd.cols.items()}, sd.track_length_m, sd.provenance)


def test_fuel_consumption_matches_simulator(tpf):
    sd, laps = record(tpf, "constant", laps=5)
    r = fuel_report(sd, laps, target_laps=20, margin_laps=0.5)
    # simulator burns 0.018 L per throttle-second: constant laps => identical consumption
    assert r["n"] >= 3 and r["std_l_per_lap"] < 0.01
    assert r["mean_l_per_lap"] == pytest.approx(r["per_lap"][0]["fuel_used_l"], abs=0.01)
    assert r["laps_remaining"] == pytest.approx(r["current_fuel_l"] / r["mean_l_per_lap"], rel=1e-3)
    plan = r["plan"]
    assert plan["fuel_needed_l"] == pytest.approx(20 * r["mean_l_per_lap"], abs=0.05)
    assert plan["safety_margin_provenance"] == "manual"
    assert plan["fuel_with_margin_l"] > plan["fuel_needed_l"]


def test_refuel_lap_is_excluded_and_reported(tpf):
    sd, laps = record(tpf, "constant", laps=5)
    sd2 = clone(sd)
    l2 = laps[1]
    sd2.cols["fuel_l"][l2.i0 + 500:] += 20.0            # a refuel mid lap 2 (and afterwards)
    r = fuel_report(sd2, laps)
    assert 2 not in r["laps_used"] and any(e["lap"] == 2 and "refuel" in e["reason"] for e in r["excluded"])


def test_no_estimate_with_less_than_two_clean_laps(tpf):
    sd, laps = record(tpf, "constant", laps=2)
    r = fuel_report(sd, laps)
    assert "mean_l_per_lap" not in r and "note" in r


def test_fuel_channel_missing(tpf):
    sd, laps = record(tpf, "constant", laps=3)
    sd2 = clone(sd); sd2.cols["fuel_l"][:] = np.nan
    assert fuel_report(sd2, laps)["available"] is False


def test_tyre_report_trends_and_missing_channels(tpf):
    sd, laps = record(tpf, "constant", laps=5)
    r = tyre_report(sd, laps)
    assert r["available"] and len(r["laps_used"]) >= 3
    assert r["trends"]["fl.wear_end"]["slope_per_lap"] > 0          # simulator wears linearly with time
    assert r["differences_last_lap"]["pressure_fl_minus_fr_kpa"] == pytest.approx(0.0, abs=1e-6)
    sd2 = clone(sd); sd2.cols["tyre_rr_wear"][:] = np.nan
    r2 = tyre_report(sd2, laps)
    assert "tyre_rr_wear" in r2["missing_channels"] and "rr.wear_end" not in r2["trends"]
