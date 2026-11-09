"""Decode raw LMU structs into normalized ``Sample`` objects (pure functions, no I/O)."""
from __future__ import annotations

import math
import time

from ..model.channels import WHEELS
from ..model.provenance import Provenance
from ..model.sample import Sample, SessionContext, session_type_name
from . import layout as L

KELVIN = 273.15


def _s(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _fin(x: float):
    return float(x) if math.isfinite(x) else None


def decode_context(generic: L.Generic, info: L.ScoringInfo, veh: L.VehicleScoring | None,
                   telem: L.VehicleTelemetry | None) -> SessionContext:
    return SessionContext(
        track_name=_s(info.mTrackName) or (_s(telem.mTrackName) if telem else ""),
        vehicle_name=(_s(telem.mVehicleName) if telem else "") or (_s(veh.mVehicleName) if veh else ""),
        vehicle_class=_s(veh.mVehicleClass) if veh else "",
        driver_name=_s(info.mPlayerName), session_code=int(info.mSession),
        session_type=session_type_name(int(info.mSession)), game_version=int(generic.gameVersion),
        track_length_m=float(info.mLapDist), max_laps=int(info.mMaxLaps),
    )


def decode_sample(info: L.ScoringInfo, veh: L.VehicleScoring | None, t: L.VehicleTelemetry,
                  source: Provenance = Provenance.LMU_SHM, wall_time: float | None = None) -> Sample:
    v: dict = {}
    un: set[str] = set()
    vel = t.mLocalVel
    v["session_time_s"] = _fin(t.mElapsedTime)
    v["delta_time_s"] = _fin(t.mDeltaTime)
    v["lap_number"] = int(t.mLapNumber)
    v["lap_time_s"] = _fin(t.mElapsedTime - t.mLapStartET)
    v["speed_kmh"] = _fin(3.6 * math.sqrt(vel.x ** 2 + vel.y ** 2 + vel.z ** 2))
    v["rpm"] = _fin(t.mEngineRPM)
    v["max_rpm"] = _fin(t.mEngineMaxRPM)
    v["gear"] = int(t.mGear)
    v["water_temp_c"] = _fin(t.mEngineWaterTemp)
    v["oil_temp_c"] = _fin(t.mEngineOilTemp)
    v["fuel_l"] = _fin(t.mFuel)
    v["fuel_capacity_l"] = _fin(t.mFuelCapacity)
    v["brake_bias_rear"] = _fin(t.mRearBrakeBias)
    v["damage_dent_max"] = max(t.mDentSeverity)
    v["parts_detached"] = bool(t.mDetached)
    v["overheating"] = bool(t.mOverheating)
    v["lap_invalidated"] = bool(t.mLapInvalidated)
    v["throttle"] = _fin(t.mUnfilteredThrottle)
    v["brake"] = _fin(t.mUnfilteredBrake)
    v["clutch"] = _fin(t.mUnfilteredClutch)
    v["steering"] = _fin(t.mUnfilteredSteering)
    v["throttle_filtered"] = _fin(t.mFilteredThrottle)
    v["brake_filtered"] = _fin(t.mFilteredBrake)
    v["steering_filtered"] = _fin(t.mFilteredSteering)
    v["local_accel_x_ms2"] = _fin(t.mLocalAccel.x)
    v["local_accel_y_ms2"] = _fin(t.mLocalAccel.y)
    v["local_accel_z_ms2"] = _fin(t.mLocalAccel.z)
    v["pos_x_m"], v["pos_y_m"], v["pos_z_m"] = _fin(t.mPos.x), _fin(t.mPos.y), _fin(t.mPos.z)
    for i, w in enumerate(WHEELS):
        wh = t.mWheels[i]
        v[f"tyre_{w}_pressure_kpa"] = _fin(wh.mPressure)
        for j, side in enumerate(("left", "center", "right")):
            v[f"tyre_{w}_temp_{side}_c"] = _fin(wh.mTemperature[j] - KELVIN)
        v[f"tyre_{w}_carcass_temp_c"] = _fin(wh.mTireCarcassTemperature - KELVIN)
        v[f"tyre_{w}_wear"] = _fin(wh.mWear)
        v[f"tyre_{w}_brake_temp_c"] = _fin(wh.mBrakeTemp)  # header: Celsius
    if veh is not None:
        v["lap_dist_m"] = _fin(veh.mLapDist)
        v["sector"] = {1: 1, 2: 2, 0: 3}.get(int(veh.mSector))
        v["in_pits"] = bool(veh.mInPits)
        v["last_lap_time_s"] = _fin(veh.mLastLapTime)
        v["best_lap_time_s"] = _fin(veh.mBestLapTime)
        v["cur_sector1_s"] = _fin(veh.mCurSector1)
        v["cur_sector2_s"] = _fin(veh.mCurSector2)
    else:
        for k in ("lap_dist_m", "sector", "in_pits", "last_lap_time_s", "best_lap_time_s",
                  "cur_sector1_s", "cur_sector2_s"):
            v[k] = None
            un.add(k)
    w = info.mWind
    v["ambient_temp_c"] = _fin(info.mAmbientTemp)
    v["track_temp_c"] = _fin(info.mTrackTemp)
    v["rain"] = _fin(info.mRaining)
    v["wind_ms"] = _fin(math.sqrt(w.x ** 2 + w.y ** 2 + w.z ** 2))
    v["path_wetness_avg"] = _fin(info.mAvgPathWetness)
    v["session_code"] = int(info.mSession)
    v["game_phase"] = int(info.mGamePhase)
    v["in_realtime"] = bool(info.mInRealtime)
    return Sample(wall_time=time.time() if wall_time is None else wall_time, source=source,
                  values=v, unavailable=frozenset(un | {k for k, x in v.items() if x is None}))
