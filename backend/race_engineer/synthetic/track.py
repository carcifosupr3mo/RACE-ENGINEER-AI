"""Deterministic synthetic lap simulator. SYNTHETIC DATA - never evidence of LMU integration.

A kinematic model: the car follows a reference speed profile v_ref(s) built from corner apex
speeds, a braking envelope and an acceleration envelope. Scenarios perturb that profile in
known, quantified ways so analysers can be tested for *detecting a known difference*.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterator

import numpy as np

SYNTH_PREFIX = "[SYNTHETIC] "
G = 9.81


@dataclass(frozen=True)
class Corner:
    number: int
    s_apex: float          # m along lap
    v_apex_kmh: float
    direction: int         # +1 right, -1 left


@dataclass(frozen=True)
class SyntheticTrack:
    name: str = SYNTH_PREFIX + "Test Circuit"
    length_m: float = 3000.0
    corners: tuple[Corner, ...] = (Corner(1, 600, 90, +1), Corner(2, 1300, 60, -1),
                                   Corner(3, 1800, 120, +1), Corner(4, 2400, 70, -1))
    vmax_kmh: float = 250.0
    a_brake: float = 1.4 * G   # m/s2 reference braking decel
    a_accel: float = 0.55 * G  # m/s2 reference acceleration (decays with speed below)


@dataclass(frozen=True)
class Scenario:
    name: str = "constant"
    pace_scale: float = 1.0              # multiplies apex and max speeds
    brake_shift_m: dict[int, float] = field(default_factory=dict)  # corner -> metres of EARLIER braking (>=0)
    brake_decel_scale: float = 1.0
    throttle_delay_m: dict[int, float] = field(default_factory=dict)  # corner -> m of delay on exit
    drop_prob: float = 0.0               # probability a frame is not published (missing samples)
    incomplete_after_lap: int | None = None  # stop producing frames mid-lap after this lap
    unavailable: tuple[str, ...] = ()    # channels forced to None (telemetry incompleteness)
    lap_overrides: dict[int, str] = field(default_factory=dict)   # lap -> scenario name for that lap only
    seed: int = 1


SCENARIOS: dict[str, Scenario] = {
    "constant": Scenario("constant"),
    "slower": Scenario("slower", pace_scale=0.97),
    "early_brake": Scenario("early_brake", brake_shift_m={2: 40.0}),
    "late_brake": Scenario("late_brake", brake_decel_scale=1.15),  # later brake point, harder braking
    "late_throttle": Scenario("late_throttle", throttle_delay_m={3: 35.0}),
    "missing_samples": Scenario("missing_samples", drop_prob=0.15),
    "incomplete": Scenario("incomplete", incomplete_after_lap=2),
    "mixed": Scenario("mixed", lap_overrides={2: "early_brake", 3: "late_throttle"}),   # one session, different laps
    "no_tyre_data": Scenario("no_tyre_data", unavailable=tuple(
        f"tyre_{w}_{c}" for w in ("fl", "fr", "rl", "rr") for c in ("pressure_kpa", "wear"))),
}


def reference_profile(track: SyntheticTrack, sc: Scenario, ds: float = 1.0) -> np.ndarray:
    """Reference speed (m/s) at every metre of the lap, honouring scenario perturbations."""
    n = int(track.length_m / ds)
    s = np.arange(n) * ds
    vmax = track.vmax_kmh / 3.6 * sc.pace_scale
    v = np.full(n, vmax)
    ab = track.a_brake * sc.brake_decel_scale
    for c in track.corners:
        vc = c.v_apex_kmh / 3.6 * sc.pace_scale
        shift = max(0.0, sc.brake_shift_m.get(c.number, 0.0))  # early braking only; late = higher decel
        delay = sc.throttle_delay_m.get(c.number, 0.0)
        # signed circular distance from apex
        d = (s - c.s_apex + track.length_m / 2) % track.length_m - track.length_m / 2
        brk = np.where(d < -shift, np.sqrt(vc ** 2 + 2 * ab * np.maximum(-shift - d, 0.0)), vc)
        brk = np.where(d <= 0, brk, vmax)
        acc = np.where(d >= delay, np.sqrt(vc ** 2 + 2 * track.a_accel * np.maximum(d - delay, 0.0)), vc)
        acc = np.where(d > 0, acc, vmax)
        v = np.minimum(v, np.minimum(brk, acc))
    return np.minimum(v, vmax)


def _gear(v_kmh: float) -> int:
    edges = (0, 55, 95, 135, 180, 225)
    return max(i + 1 for i, e in enumerate(edges) if v_kmh >= e)


def frames(track: SyntheticTrack, sc: Scenario, laps: int = 3, hz: int = 100) -> Iterator[dict]:
    """Yield one dict per simulation tick (published or not: see ``published`` flag)."""
    rng = np.random.default_rng(sc.seed)
    ds = 1.0
    vref_default = reference_profile(track, sc, ds)
    vrefs = {lap_no: reference_profile(track, SCENARIOS[name], ds) for lap_no, name in sc.lap_overrides.items()}
    n = len(vref_default)
    dt = 1.0 / hz
    s_total = 0.0
    t = 0.0
    fuel = 80.0
    lap = 1
    lap_start = 0.0
    best = -1.0
    last = -1.0
    s1 = s2 = 0.0
    sec_idx = 1
    v = float(vref_default[0])
    tyre_temp = 70.0
    brake_temp = 150.0
    total = laps * track.length_m
    # steering amplitude per corner
    while s_total < total:
        s = s_total % track.length_m
        i = int(s / ds) % n
        vref = vrefs.get(lap, vref_default)
        v_next = float(vref[(i + 1) % n])
        a = (v_next * v_next - v * v) / (2 * ds)  # dv/dt = v dv/ds
        v = float(vref[i])
        a_b = track.a_brake * sc.brake_decel_scale
        at_vmax = v >= track.vmax_kmh / 3.6 * sc.pace_scale - 0.5
        if a > 0.25:
            thr = min(1.0, 0.55 + a / (track.a_accel * 1.2))
        elif abs(a) <= 0.25:
            thr = 1.0 if at_vmax else 0.3   # full throttle at vmax, maintenance throttle in corners
        else:
            thr = 0.0
        brk = min(1.0, -a / a_b) if a < -0.4 else 0.0
        if brk > 0:
            thr = 0.0
        steer = 0.0
        kappa = 0.0
        for c in track.corners:
            d = (s - c.s_apex + track.length_m / 2) % track.length_m - track.length_m / 2
            w = math.exp(-(d / 70.0) ** 2)
            steer += c.direction * 0.5 * w * (1.0 if v < 50 else 50.0 / v + 0.3)
            kappa += c.direction * w / 120.0
        lat = v * v * kappa
        kmh = v * 3.6
        gear = _gear(kmh)
        lo = (0, 55, 95, 135, 180, 225)[gear - 1]
        rpm = 3500 + min(1.0, (kmh - lo) / 45.0) * 4500 + rng.normal(0, 15)
        fuel -= 0.018 * thr * dt
        tyre_temp += (0.002 * (abs(lat) / G) - 0.0006 * (tyre_temp - 70)) * 1.0
        brake_temp += 400 * brk * dt - 0.4 * (brake_temp - 150) * dt
        elapsed = t
        s_in_lap = s
        frame_sec = 1 if s_in_lap < track.length_m / 3 else (2 if s_in_lap < 2 * track.length_m / 3 else 3)
        if frame_sec == 2 and sec_idx == 1:
            s1 = elapsed - lap_start
            sec_idx = 2
        elif frame_sec == 3 and sec_idx == 2:
            s2 = elapsed - lap_start
            sec_idx = 3
        frame = {
            "t": elapsed, "dt": dt, "lap": lap, "lap_start": lap_start, "lap_dist": s_in_lap,
            "speed_ms": v, "rpm": float(rpm), "gear": gear, "throttle": float(thr), "brake": float(brk),
            "steer": float(max(-1, min(1, steer))), "a_long": float(a), "a_lat": float(lat),
            "fuel": fuel, "sector": frame_sec, "last_lap": last, "best_lap": best,
            "cur_s1": s1 if sec_idx >= 2 else 0.0, "cur_s2": s2 if sec_idx >= 3 else 0.0,
            "tyre_temp": tyre_temp + float(rng.normal(0, 0.05)), "brake_temp": brake_temp,
            "pos_x": track.length_m / (2 * math.pi) * math.cos(2 * math.pi * s_in_lap / track.length_m),
            "pos_z": track.length_m / (2 * math.pi) * math.sin(2 * math.pi * s_in_lap / track.length_m),
            "published": (rng.random() >= sc.drop_prob),
            "incomplete_stop": sc.incomplete_after_lap is not None and lap > sc.incomplete_after_lap
                               and s_in_lap > track.length_m * 0.4,
        }
        yield frame
        step = max(v, 5.0) * dt
        s_total += step
        t += dt
        if s_total // track.length_m + 1 > lap:
            last = t - lap_start
            best = last if best < 0 else min(best, last)
            lap += 1
            lap_start = t
            sec_idx = 1
            s1 = s2 = 0.0
