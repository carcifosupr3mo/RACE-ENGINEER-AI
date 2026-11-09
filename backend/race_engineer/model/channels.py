"""Normalized telemetry channel catalogue (single source of truth).

Units are SI-ish and fixed: pedals/steering as fractions (0..1, steering -1..1), temperatures in
degC, pressures in kPa, speeds km/h, distances m, times s. Wheels are ordered FL, FR, RL, RR
(LMU documents ``mWheels``: 0=front left, 1=front right, 2=rear left, 3=rear right).

``kind``: 'direct'   = field copied from LMU (pure unit conversion allowed, documented in ``src``)
          'computed' = derived by this software (formula in ``src``)
"""
from __future__ import annotations

from dataclasses import dataclass

WHEELS = ("fl", "fr", "rl", "rr")


@dataclass(frozen=True)
class Channel:
    name: str
    dtype: str      # DuckDB type
    unit: str
    kind: str       # 'direct' | 'computed'
    src: str        # LMU field(s) / formula
    note: str = ""


def _c(*a, **k) -> Channel:
    return Channel(*a, **k)


_BASE = [
    # --- timing / track position
    _c("session_time_s", "DOUBLE", "s", "direct", "telem.mElapsedTime"),
    _c("delta_time_s", "DOUBLE", "s", "direct", "telem.mDeltaTime", "time since last game update"),
    _c("lap_number", "INTEGER", "", "direct", "telem.mLapNumber"),
    _c("lap_time_s", "DOUBLE", "s", "computed", "telem.mElapsedTime - telem.mLapStartET"),
    _c("lap_dist_m", "DOUBLE", "m", "direct", "scoring[player].mLapDist"),
    _c("sector", "INTEGER", "", "computed", "scoring[player].mSector remapped (1->1, 2->2, 0->3)",
       "LMU: 0=sector3, 1=sector1, 2=sector2"),
    _c("in_pits", "BOOLEAN", "", "direct", "scoring[player].mInPits"),
    _c("lap_invalidated", "BOOLEAN", "", "direct", "telem.mLapInvalidated"),
    _c("last_lap_time_s", "DOUBLE", "s", "direct", "scoring[player].mLastLapTime", "<=0 means none"),
    _c("best_lap_time_s", "DOUBLE", "s", "direct", "scoring[player].mBestLapTime", "<=0 means none"),
    _c("cur_sector1_s", "DOUBLE", "s", "direct", "scoring[player].mCurSector1"),
    _c("cur_sector2_s", "DOUBLE", "s", "direct", "scoring[player].mCurSector2", "cumulative (S1+S2)"),
    # --- vehicle
    _c("speed_kmh", "DOUBLE", "km/h", "computed", "3.6*|telem.mLocalVel|", "no native speed field"),
    _c("rpm", "DOUBLE", "rpm", "direct", "telem.mEngineRPM"),
    _c("max_rpm", "DOUBLE", "rpm", "direct", "telem.mEngineMaxRPM"),
    _c("gear", "INTEGER", "", "direct", "telem.mGear", "-1 reverse, 0 neutral"),
    _c("water_temp_c", "DOUBLE", "degC", "direct", "telem.mEngineWaterTemp"),
    _c("oil_temp_c", "DOUBLE", "degC", "direct", "telem.mEngineOilTemp"),
    _c("fuel_l", "DOUBLE", "L", "direct", "telem.mFuel"),
    _c("fuel_capacity_l", "DOUBLE", "L", "direct", "telem.mFuelCapacity"),
    _c("brake_bias_rear", "DOUBLE", "", "direct", "telem.mRearBrakeBias", "fraction on rear"),
    _c("damage_dent_max", "INTEGER", "", "computed", "max(telem.mDentSeverity[0..7])", "0 none, 1 some, 2 more"),
    _c("parts_detached", "BOOLEAN", "", "direct", "telem.mDetached"),
    _c("overheating", "BOOLEAN", "", "direct", "telem.mOverheating"),
    # --- driver inputs
    _c("throttle", "DOUBLE", "0..1", "direct", "telem.mUnfilteredThrottle"),
    _c("brake", "DOUBLE", "0..1", "direct", "telem.mUnfilteredBrake"),
    _c("clutch", "DOUBLE", "0..1", "direct", "telem.mUnfilteredClutch"),
    _c("steering", "DOUBLE", "-1..1", "direct", "telem.mUnfilteredSteering", "LMU: left to right"),
    _c("throttle_filtered", "DOUBLE", "0..1", "direct", "telem.mFilteredThrottle"),
    _c("brake_filtered", "DOUBLE", "0..1", "direct", "telem.mFilteredBrake"),
    _c("steering_filtered", "DOUBLE", "-1..1", "direct", "telem.mFilteredSteering"),
    # --- dynamics (local vehicle axes, raw: sign convention NOT yet verified against a real LMU)
    _c("local_accel_x_ms2", "DOUBLE", "m/s2", "direct", "telem.mLocalAccel.x"),
    _c("local_accel_y_ms2", "DOUBLE", "m/s2", "direct", "telem.mLocalAccel.y"),
    _c("local_accel_z_ms2", "DOUBLE", "m/s2", "direct", "telem.mLocalAccel.z"),
    _c("pos_x_m", "DOUBLE", "m", "direct", "telem.mPos.x", "world frame, y = elevation"),
    _c("pos_y_m", "DOUBLE", "m", "direct", "telem.mPos.y"),
    _c("pos_z_m", "DOUBLE", "m", "direct", "telem.mPos.z"),
    # --- environment (scoring)
    _c("ambient_temp_c", "DOUBLE", "degC", "direct", "scoring.mAmbientTemp"),
    _c("track_temp_c", "DOUBLE", "degC", "direct", "scoring.mTrackTemp"),
    _c("rain", "DOUBLE", "0..1", "direct", "scoring.mRaining"),
    _c("wind_ms", "DOUBLE", "m/s", "computed", "|scoring.mWind|", "unit of mWind not verified"),
    _c("path_wetness_avg", "DOUBLE", "0..1", "direct", "scoring.mAvgPathWetness"),
    # --- session context per sample
    _c("session_code", "INTEGER", "", "direct", "scoring.mSession",
       "0 test day, 1-4 practice, 5-8 qualifying, 9 warmup, 10-13 race"),
    _c("game_phase", "INTEGER", "", "direct", "scoring.mGamePhase"),
    _c("in_realtime", "BOOLEAN", "", "direct", "scoring.mInRealtime"),
]

_TYRE = [
    ("pressure_kpa", "kPa", "mPressure"),
    ("temp_left_c", "degC", "mTemperature[0] - 273.15 (Kelvin->degC)"),
    ("temp_center_c", "degC", "mTemperature[1] - 273.15"),
    ("temp_right_c", "degC", "mTemperature[2] - 273.15"),
    ("carcass_temp_c", "degC", "mTireCarcassTemperature - 273.15"),
    ("wear", "0..1", "mWear (fraction of max)"),
    ("brake_temp_c", "degC", "mBrakeTemp"),
]
for _w_i, _w in enumerate(WHEELS):
    for _n, _u, _s in _TYRE:
        _BASE.append(_c(f"tyre_{_w}_{_n}", "DOUBLE", _u, "direct", f"telem.mWheels[{_w_i}].{_s}",
                        "left/center/right = LMU wheel-relative, not inner/outer" if "temp_" in _n else ""))

CHANNELS: tuple[Channel, ...] = tuple(_BASE)
CHANNEL_BY_NAME = {c.name: c for c in CHANNELS}
COMPUTED_FIELDS = frozenset(c.name for c in CHANNELS if c.kind == "computed")
