"""A *fake game* that publishes SYNTHETIC frames into a buffer using the real LMU binary layout."""
from __future__ import annotations

import ctypes as C
from typing import Iterator

from ..lmu import layout as L
from ..lmu.reader import BytesBackend
from .track import G, SYNTH_PREFIX, Scenario, SyntheticTrack, SCENARIOS, frames


def _put(struct, field: str, text: str) -> None:
    setattr(struct, field, text.encode())


class SyntheticGame:
    """Writes into a bytearray shaped like ``LMU_Data``. Exposes ``backend`` for the reader."""

    def __init__(self, scenario: Scenario | str = "constant", track: SyntheticTrack | None = None,
                 laps: int = 3, hz: int = 100, session_code: int = 1):
        self.scenario = SCENARIOS[scenario] if isinstance(scenario, str) else scenario
        self.track = track or SyntheticTrack()
        self.buf = bytearray(L.MAPPING_SIZE)
        self.obj = L.ObjectOut.from_buffer(self.buf)
        self.backend = BytesBackend(self.buf, "SYNTHETIC in-memory LMU_Data layout")
        self.backend.synthetic = True  # type: ignore[attr-defined]
        self._it: Iterator[dict] = frames(self.track, self.scenario, laps, hz)
        self.frames_total = 0
        self.frames_published = 0
        self.pub_first: int | None = None   # index of first/last published frame (for loss tests)
        self.pub_last: int | None = None
        self.finished = False
        self._init_static(session_code)

    def _init_static(self, session_code: int) -> None:
        o = self.obj
        o.generic.gameVersion = 0
        _put(o.scoring.scoringInfo, "mTrackName", self.track.name)
        o.scoring.scoringInfo.mSession = session_code
        o.scoring.scoringInfo.mLapDist = self.track.length_m
        o.scoring.scoringInfo.mNumVehicles = 1
        o.scoring.scoringInfo.mGamePhase = 5
        o.scoring.scoringInfo.mInRealtime = True
        o.scoring.scoringInfo.mAmbientTemp = 22.0
        o.scoring.scoringInfo.mTrackTemp = 31.0
        _put(o.scoring.scoringInfo, "mPlayerName", "Synthetic Driver")
        v = o.scoring.vehScoringInfo[0]
        v.mIsPlayer = True
        v.mID = 0
        _put(v, "mVehicleName", SYNTH_PREFIX + "GT #00")
        _put(v, "mVehicleClass", "SYNTH")
        o.telemetry.activeVehicles = 1
        o.telemetry.playerVehicleIdx = 0
        t = o.telemetry.telemInfo[0]
        _put(t, "mVehicleName", SYNTH_PREFIX + "GT #00")
        _put(t, "mTrackName", self.track.name)
        t.mFuelCapacity = 100.0
        t.mEngineMaxRPM = 8500.0

    def _write(self, f: dict) -> None:
        o = self.obj
        o.telemetry.playerHasVehicle = True
        t = o.telemetry.telemInfo[0]
        t.mElapsedTime = f["t"]
        t.mDeltaTime = f["dt"]
        t.mLapNumber = f["lap"]
        t.mLapStartET = f["lap_start"]
        t.mLocalVel.z = f["speed_ms"]
        t.mGear = f["gear"]
        t.mEngineRPM = f["rpm"]
        t.mUnfilteredThrottle = t.mFilteredThrottle = f["throttle"]
        t.mUnfilteredBrake = t.mFilteredBrake = f["brake"]
        t.mUnfilteredSteering = t.mFilteredSteering = f["steer"]
        t.mLocalAccel.z = -f["a_long"]   # synthetic convention only (real LMU sign unverified)
        t.mLocalAccel.x = f["a_lat"]
        t.mFuel = f["fuel"]
        t.mPos.x, t.mPos.z = f["pos_x"], f["pos_z"]
        t.mEngineWaterTemp, t.mEngineOilTemp = 88.0, 98.0
        for i in range(4):
            w = t.mWheels[i]
            w.mPressure = 165.0 + 0.8 * (f["tyre_temp"] - 70)
            for j, off in enumerate((-3.0, 0.0, 3.0)):
                w.mTemperature[j] = 273.15 + f["tyre_temp"] + off
            w.mTireCarcassTemperature = 273.15 + f["tyre_temp"] - 5
            w.mWear = min(1.0, 0.0001 * f["t"])
            w.mBrakeTemp = f["brake_temp"]
        sc = o.scoring.scoringInfo
        sc.mCurrentET = f["t"]
        v = o.scoring.vehScoringInfo[0]
        v.mLapDist = f["lap_dist"]
        v.mSector = {1: 1, 2: 2, 3: 0}[f["sector"]]
        v.mLastLapTime, v.mBestLapTime = f["last_lap"], f["best_lap"]
        v.mCurSector1, v.mCurSector2 = f["cur_s1"], f["cur_s2"]
        v.mTotalLaps = f["lap"] - 1
        o.generic.events.SME_UPDATE_TELEMETRY = 1
        o.generic.events.SME_UPDATE_SCORING = 1

    def step(self) -> bool:
        """Advance one simulation tick; publish it unless the scenario drops it. False when done."""
        try:
            f = next(self._it)
        except StopIteration:
            self.finished = True
            return False
        self.frames_total += 1
        if f["incomplete_stop"]:
            self.finished = True
            return False
        if f["published"]:
            self._write(f)
            self.frames_published += 1
            self.pub_first = self.frames_total if self.pub_first is None else self.pub_first
            self.pub_last = self.frames_total
        return True

    def end_session(self) -> None:
        self.obj.generic.events.SME_END_SESSION = 1
        self.obj.scoring.scoringInfo.mGamePhase = 8
        self.obj.telemetry.playerHasVehicle = False
