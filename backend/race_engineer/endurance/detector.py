"""Continuous LOCAL analysis: turns the sample stream into laps, stints and important events.

Thresholds are generic DEFAULTS (not compound- or car-specific, units as in the channel catalog); every one is configurable.
Memory is bounded: only small deques are kept. Nothing here talks to the network.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..ai.providers.types import Priority

TYRES = ("fl", "fr", "rl", "rr")


@dataclass
class Thresholds:
    fuel_low_laps: float = 3.0
    fuel_critical_laps: float = 1.5
    tyre_temp_high_c: float = 115.0
    tyre_temp_sustain_s: float = 20.0
    water_temp_high_c: float = 112.0
    oil_temp_high_c: float = 145.0
    off_pace_ratio: float = 1.04
    rain_on: float = 0.15
    rain_off: float = 0.05
    event_gap_s: float = 90.0           # per event kind, minimum race-time between two events of the same kind


@dataclass
class Event:
    kind: str
    severity: Priority
    lap: int
    race_s: float
    data: dict
    dedup_key: str


@dataclass
class _Lap:
    lap: int = 0
    fuel_start: float | None = None
    tyre_max: float = 0.0
    wear_min: float = 1.0
    start_s: float = 0.0
    had_pit: bool = False


class EventDetector:
    def __init__(self, th: Thresholds | None = None):
        self.th = th or Thresholds()
        self.cur = _Lap()
        self.fuel_hist: deque[float] = deque(maxlen=6)
        self.lap_hist: deque[float] = deque(maxlen=10)
        self.best: float | None = None
        self.stint = 1
        self.stint_laps: list[float] = []
        self.stint_fuel = 0.0
        self.stint_start_s = 0.0
        self.in_pits = False
        self.rain = False
        self.dent = 0
        self.detached = False
        self.hot_since: float | None = None
        self.last_event_s: dict[str, float] = {}
        self.samples = 0
        self.last_values: dict = {}

    # -------------------------------------------------------------- helpers
    def fuel_per_lap(self) -> float | None:
        return sum(self.fuel_hist) / len(self.fuel_hist) if self.fuel_hist else None

    def laps_of_fuel(self, fuel_l: float) -> float | None:
        f = self.fuel_per_lap()
        return fuel_l / f if f and f > 0.05 else None

    def _emit(self, out: list, kind, sev, lap, t, data, key=None, bypass_gap=False):
        if not bypass_gap and t - self.last_event_s.get(kind, -1e18) < self.th.event_gap_s:
            return
        self.last_event_s[kind] = t
        out.append(Event(kind, sev, lap, t, data, key or kind))

    # -------------------------------------------------------------- main
    def feed(self, v: dict) -> list[Event]:
        """v = Sample.values. Returns the events triggered by this sample (usually none)."""
        self.samples += 1
        self.last_values = v
        out: list[Event] = []
        t, lap = float(v.get("session_time_s", 0.0)), int(v.get("lap_number", 0))
        th = self.th
        tyre_t = max((v.get(f"tyre_{w}_temp_center_c") or 0.0) for w in TYRES)
        wears = [v.get(f"tyre_{w}_wear") for w in TYRES if v.get(f"tyre_{w}_wear") is not None]
        c = self.cur
        c.tyre_max = max(c.tyre_max, tyre_t)
        if wears:
            c.wear_min = min(c.wear_min, min(wears))
        # ---- lap boundary
        if c.fuel_start is None:
            c.fuel_start, c.lap, c.start_s = float(v.get("fuel_l", 0.0)), lap, t
        elif lap != c.lap:
            self._lap_done(out, v, t, lap)
        # ---- pits
        pits = bool(v.get("in_pits"))
        if pits and not self.in_pits:
            self.in_pits = True
            self.cur.had_pit = True
            self._stint_end(out, t, lap)
            self._emit(out, "pit_in", Priority.HIGH, lap, t, {"fuel_l": round(float(v.get("fuel_l", 0)), 1)}, "pit_in", True)
        elif not pits and self.in_pits:
            self.in_pits = False
            self.stint += 1
            self.stint_laps, self.stint_fuel, self.stint_start_s = [], 0.0, t
            self.cur.had_pit = True
            self._emit(out, "pit_out", Priority.NORMAL, lap, t, {"stint": self.stint, "fuel_l": round(float(v.get("fuel_l", 0)), 1)}, "pit_out", True)
        # ---- fuel
        lf = self.laps_of_fuel(float(v.get("fuel_l", 0.0)))
        if lf is not None and not self.in_pits:
            if lf < th.fuel_critical_laps:
                self._emit(out, "fuel_critical", Priority.CRITICAL, lap, t, {"laps_of_fuel": round(lf, 1)}, "fuel_critical")
            elif lf < th.fuel_low_laps:
                self._emit(out, "fuel_low", Priority.HIGH, lap, t, {"laps_of_fuel": round(lf, 1)}, "fuel_low")
        # ---- temperatures
        if tyre_t > th.tyre_temp_high_c:
            self.hot_since = self.hot_since if self.hot_since is not None else t
            if t - self.hot_since >= th.tyre_temp_sustain_s:
                self._emit(out, "tyre_temp_high", Priority.NORMAL, lap, t, {"tyre_temp_c": round(tyre_t, 0)}, "tyre_temp_high")
        else:
            self.hot_since = None
        if (v.get("water_temp_c") or 0) > th.water_temp_high_c or (v.get("oil_temp_c") or 0) > th.oil_temp_high_c or v.get("overheating"):
            self._emit(out, "engine_temp_high", Priority.HIGH, lap, t,
                       {"water_c": round(v.get("water_temp_c") or 0, 0), "oil_c": round(v.get("oil_temp_c") or 0, 0)}, "engine_temp_high")
        # ---- damage: edge-triggered (a damaged car sitting in the pits must not flood events); repairs lower the level
        d = int(v.get("damage_dent_max") or 0)
        detached = bool(v.get("parts_detached"))
        if d > self.dent or (detached and not self.detached):
            self._emit(out, "damage", Priority.HIGH, lap, t, {"dent_max": d, "detached": detached}, f"damage{d}", True)
        self.dent, self.detached = d, detached
        # ---- weather (hysteresis)
        rain = float(v.get("rain") or 0.0)
        if not self.rain and rain >= th.rain_on:
            self.rain = True
            self._emit(out, "rain_start", Priority.HIGH, lap, t, {"rain": round(rain, 2)}, "rain_start", True)
        elif self.rain and rain <= th.rain_off:
            self.rain = False
            self._emit(out, "rain_stop", Priority.NORMAL, lap, t, {"rain": round(rain, 2)}, "rain_stop", True)
        return out

    def _lap_done(self, out, v, t, new_lap):
        c = self.cur
        lt = float(v.get("last_lap_time_s") or 0.0)
        fuel_now = float(v.get("fuel_l", 0.0))
        used = max(0.0, (c.fuel_start or fuel_now) - fuel_now)
        valid = lt > 0 and not c.had_pit
        if valid and used > 0.05:
            self.fuel_hist.append(used)
        if valid:
            self.lap_hist.append(lt)
            self.stint_laps.append(lt)
            self.stint_fuel += used
            if self.best is None or lt < self.best:
                self.best = lt
        data = {"time_s": round(lt, 3), "valid": valid, "fuel_used_l": round(used, 2),
                "tyre_max_c": round(c.tyre_max, 0), "wear_min": round(c.wear_min, 3), "stint": self.stint,
                "delta_best_s": None if (self.best is None or not valid) else round(lt - self.best, 3)}
        self._emit(out, "lap_completed", Priority.LOW, c.lap, t, data, f"lap{c.lap}", True)
        if valid and self.best and lt > self.best * self.th.off_pace_ratio:
            self._emit(out, "off_pace", Priority.NORMAL, c.lap, t, {"time_s": round(lt, 3), "best_s": round(self.best, 3)}, "off_pace")
        self.cur = _Lap(lap=new_lap, fuel_start=fuel_now, start_s=t, tyre_max=0.0, wear_min=1.0, had_pit=self.in_pits)

    def _stint_end(self, out, t, lap):
        n = len(self.stint_laps)
        avg = sum(self.stint_laps) / n if n else None
        self._emit(out, "stint_end", Priority.HIGH, lap, t,
                   {"stint": self.stint, "laps": n, "avg_lap_s": None if avg is None else round(avg, 3),
                    "fuel_used_l": round(self.stint_fuel, 1), "start_s": round(self.stint_start_s), "end_s": round(t)}, "stint_end", True)

    # -------------------------------------------------------------- persistence (restart without re-firing old events)
    def export_state(self) -> dict:
        return {"stint": self.stint, "best": self.best, "fuel_hist": list(self.fuel_hist), "lap_hist": list(self.lap_hist),
                "stint_laps": self.stint_laps, "stint_fuel": self.stint_fuel, "stint_start_s": self.stint_start_s,
                "in_pits": self.in_pits, "rain": self.rain, "dent": self.dent, "detached": self.detached, "last_event_s": self.last_event_s}

    def import_state(self, st: dict) -> None:
        if not st:
            return
        self.stint, self.best, self.stint_laps = st["stint"], st["best"], st["stint_laps"]
        self.stint_fuel, self.stint_start_s = st["stint_fuel"], st["stint_start_s"]
        self.in_pits, self.rain, self.dent, self.detached = st["in_pits"], st["rain"], st["dent"], st["detached"]
        self.fuel_hist.extend(st["fuel_hist"])
        self.lap_hist.extend(st["lap_hist"])
        self.last_event_s = dict(st["last_event_s"])

    # -------------------------------------------------------------- snapshot used by summaries
    def snapshot(self) -> dict:
        v = self.last_values
        lf = self.laps_of_fuel(float(v.get("fuel_l", 0.0))) if v else None
        n = len(self.lap_hist)
        return {"lap": self.cur.lap, "stint": self.stint, "in_pits": self.in_pits, "best_lap_s": self.best and round(self.best, 3),
                "avg_last_laps_s": round(sum(self.lap_hist) / n, 3) if n else None, "last_laps_s": [round(x, 3) for x in list(self.lap_hist)[-5:]],
                "fuel_l": v and round(float(v.get("fuel_l", 0)), 1), "fuel_per_lap_l": self.fuel_per_lap() and round(self.fuel_per_lap(), 2),
                "laps_of_fuel": lf and round(lf, 1), "rain": bool(self.rain), "stint_laps": len(self.stint_laps),
                "tyre_max_c_this_lap": round(self.cur.tyre_max, 0), "wear_min_this_lap": round(self.cur.wear_min, 3)}
