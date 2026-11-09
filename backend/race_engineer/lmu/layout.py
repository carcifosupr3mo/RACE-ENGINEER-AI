"""Binary layout of the LMU native shared memory mapping ``LMU_Data``.

PROVENANCE / VERIFICATION STATUS (read this before trusting any offset)
-----------------------------------------------------------------------
* The field list, order, types and 4-byte packing below were transcribed from the
  public third-party Python mapping ``TinyPedal/pyLMUSharedMemory`` (master branch,
  fetched 2026-11-09), which itself maps S397's ``InternalsPlugin.hpp`` and
  ``SharedMemoryInterface.hpp`` shipped in ``<LMU>/Support/SharedMemoryInterface``.
* It has NOT been compared with the headers of an installed LMU: no LMU installation
  was available when this file was written. ``verify_against_header()`` in
  ``lmu.diagnostics`` performs a field-name drift check against the installed header
  and ``MappingProbe`` compares the real mapping size with ``sizeof(LMUObjectOut)``.
* Offsets are *computed* by ctypes from this table; none are hard-coded by hand.

Everything here is read-only data description; nothing writes to the game.
"""
from __future__ import annotations

import ctypes as C
from typing import Iterable

LMU_SHARED_MEMORY_NAME = "LMU_Data"
LMU_PROCESS_HINT = "le mans ultimate"
MAX_MAPPED_VEHICLES = 104
MAX_PATH_LENGTH = 260
LAYOUT_PACK = 4
LAYOUT_SOURCE = "TinyPedal/pyLMUSharedMemory@master (maps S397 SharedMemoryInterface.hpp)"

_T = {
    "d": C.c_double, "f": C.c_float, "i": C.c_int, "I": C.c_uint,
    "B": C.c_ubyte, "b": C.c_byte, "?": C.c_bool, "h": C.c_short,
    "H": C.c_ushort, "Q": C.c_ulonglong, "c": C.c_char,
}


def _ty(spec):
    """'d' -> c_double, 'd*3' -> c_double*3, 's64' -> c_char*64, Structure -> itself."""
    if isinstance(spec, type) and issubclass(spec, C.Structure):
        return spec
    if isinstance(spec, tuple):  # (structure, count)
        return spec[0] * spec[1]
    if spec.startswith("s") and spec[1:].isdigit():
        return C.c_char * int(spec[1:])
    if "*" in spec:
        base, n = spec.split("*")
        return _T[base] * int(n)
    return _T[spec]


def _make(name: str, fields: Iterable[tuple[str, object]]) -> type[C.Structure]:
    fl = list(fields)
    cls = type(name, (C.Structure,), {"_pack_": LAYOUT_PACK, "_fields_": [(n, _ty(t)) for n, t in fl]})
    cls.FIELD_SPEC = fl  # type: ignore[attr-defined]
    return cls


Vect3 = _make("LMUVect3", [("x", "d"), ("y", "d"), ("z", "d")])  # TelemVect3

Wheel = _make("LMUWheel", [  # TelemWheelV01
    ("mSuspensionDeflection", "d"), ("mRideHeight", "d"), ("mSuspForce", "d"), ("mBrakeTemp", "d"),
    ("mBrakePressure", "d"), ("mRotation", "d"), ("mLateralPatchVel", "d"), ("mLongitudinalPatchVel", "d"),
    ("mLateralGroundVel", "d"), ("mLongitudinalGroundVel", "d"), ("mCamber", "d"), ("mLateralForce", "d"),
    ("mLongitudinalForce", "d"), ("mTireLoad", "d"), ("mGripFract", "d"), ("mPressure", "d"),
    ("mTemperature", "d*3"), ("mWear", "d"), ("mTerrainName", "s16"), ("mSurfaceType", "B"),
    ("mFlat", "?"), ("mDetached", "?"), ("mStaticUndeflectedRadius", "B"), ("mVerticalTireDeflection", "d"),
    ("mWheelYLocation", "d"), ("mToe", "d"), ("mTireCarcassTemperature", "d"),
    ("mTireInnerLayerTemperature", "d*3"), ("mOptimalTemp", "f"), ("mCompoundIndex", "B"),
    ("mCompoundType", "B"), ("mExpansion", "B*18"),
])

VehicleTelemetry = _make("LMUVehicleTelemetry", [  # TelemInfoV01
    ("mID", "i"), ("mDeltaTime", "d"), ("mElapsedTime", "d"), ("mLapNumber", "i"), ("mLapStartET", "d"),
    ("mVehicleName", "s64"), ("mTrackName", "s64"), ("mPos", Vect3), ("mLocalVel", Vect3),
    ("mLocalAccel", Vect3), ("mOri", (Vect3, 3)), ("mLocalRot", Vect3), ("mLocalRotAccel", Vect3),
    ("mGear", "i"), ("mEngineRPM", "d"), ("mEngineWaterTemp", "d"), ("mEngineOilTemp", "d"),
    ("mClutchRPM", "d"), ("mUnfilteredThrottle", "d"), ("mUnfilteredBrake", "d"),
    ("mUnfilteredSteering", "d"), ("mUnfilteredClutch", "d"), ("mFilteredThrottle", "d"),
    ("mFilteredBrake", "d"), ("mFilteredSteering", "d"), ("mFilteredClutch", "d"),
    ("mSteeringShaftTorque", "d"), ("mFront3rdDeflection", "d"), ("mRear3rdDeflection", "d"),
    ("mFrontWingHeight", "d"), ("mFrontRideHeight", "d"), ("mRearRideHeight", "d"), ("mDrag", "d"),
    ("mFrontDownforce", "d"), ("mRearDownforce", "d"), ("mFuel", "d"), ("mEngineMaxRPM", "d"),
    ("mScheduledStops", "B"), ("mOverheating", "?"), ("mDetached", "?"), ("mHeadlights", "?"),
    ("mDentSeverity", "B*8"), ("mLastImpactET", "d"), ("mLastImpactMagnitude", "d"),
    ("mLastImpactPos", Vect3), ("mEngineTorque", "d"), ("mCurrentSector", "i"), ("mSpeedLimiter", "B"),
    ("mMaxGears", "B"), ("mFrontTireCompoundIndex", "B"), ("mRearTireCompoundIndex", "B"),
    ("mFuelCapacity", "d"), ("mFrontFlapActivated", "B"), ("mRearFlapActivated", "B"),
    ("mRearFlapLegalStatus", "B"), ("mIgnitionStarter", "B"), ("mFrontTireCompoundName", "s18"),
    ("mRearTireCompoundName", "s18"), ("mSpeedLimiterAvailable", "B"), ("mAntiStallActivated", "B"),
    ("mUnused", "B*2"), ("mVisualSteeringWheelRange", "f"), ("mRearBrakeBias", "d"),
    ("mTurboBoostPressure", "d"), ("mPhysicsToGraphicsOffset", "f*3"), ("mPhysicalSteeringWheelRange", "f"),
    ("mDeltaBest", "d"), ("mBatteryChargeFraction", "d"), ("mElectricBoostMotorTorque", "d"),
    ("mElectricBoostMotorRPM", "d"), ("mElectricBoostMotorTemperature", "d"),
    ("mElectricBoostWaterTemperature", "d"), ("mElectricBoostMotorState", "B"), ("mLapInvalidated", "?"),
    ("mABSActive", "?"), ("mTCActive", "?"), ("mSpeedLimiterActive", "?"), ("mWiperState", "B"),
    ("mTC", "B"), ("mTCMax", "B"), ("mTCSlip", "B"), ("mTCSlipMax", "B"), ("mTCCut", "B"),
    ("mTCCutMax", "B"), ("mABS", "B"), ("mABSMax", "B"), ("mMotorMap", "B"), ("mMotorMapMax", "B"),
    ("mMigration", "B"), ("mMigrationMax", "B"), ("mFrontAntiSway", "B"), ("mFrontAntiSwayMax", "B"),
    ("mRearAntiSway", "B"), ("mRearAntiSwayMax", "B"), ("mLiftAndCoastProgress", "B"),
    ("mTrackLimitsSteps", "B"), ("mRegen", "f"), ("mStateOfCharge", "f"), ("mVirtualEnergy", "f"),
    ("mTimeGapCarAhead", "f"), ("mTimeGapCarBehind", "f"), ("mTimeGapPlaceAhead", "f"),
    ("mTimeGapPlaceBehind", "f"), ("mVehicleModel", "s30"), ("mVehicleClass", "B"),
    ("mVehicleChampionship", "B"), ("mExpansion", "B*20"), ("mWheels", (Wheel, 4)),
])

VehicleScoring = _make("LMUVehicleScoring", [  # VehicleScoringInfoV01
    ("mID", "i"), ("mDriverName", "s32"), ("mVehicleName", "s64"), ("mTotalLaps", "h"), ("mSector", "b"),
    ("mFinishStatus", "b"), ("mLapDist", "d"), ("mPathLateral", "d"), ("mTrackEdge", "d"),
    ("mBestSector1", "d"), ("mBestSector2", "d"), ("mBestLapTime", "d"), ("mLastSector1", "d"),
    ("mLastSector2", "d"), ("mLastLapTime", "d"), ("mCurSector1", "d"), ("mCurSector2", "d"),
    ("mNumPitstops", "h"), ("mNumPenalties", "h"), ("mIsPlayer", "?"), ("mControl", "b"), ("mInPits", "?"),
    ("mPlace", "B"), ("mVehicleClass", "s32"), ("mTimeBehindNext", "d"), ("mLapsBehindNext", "i"),
    ("mTimeBehindLeader", "d"), ("mLapsBehindLeader", "i"), ("mLapStartET", "d"), ("mPos", Vect3),
    ("mLocalVel", Vect3), ("mLocalAccel", Vect3), ("mOri", (Vect3, 3)), ("mLocalRot", Vect3),
    ("mLocalRotAccel", Vect3), ("mHeadlights", "B"), ("mPitState", "B"), ("mServerScored", "B"),
    ("mIndividualPhase", "B"), ("mQualification", "i"), ("mTimeIntoLap", "d"), ("mEstimatedLapTime", "d"),
    ("mPitGroup", "s24"), ("mFlag", "B"), ("mUnderYellow", "?"), ("mCountLapFlag", "B"),
    ("mInGarageStall", "?"), ("mUpgradePack", "B*16"), ("mPitLapDist", "f"), ("mBestLapSector1", "f"),
    ("mBestLapSector2", "f"), ("mSteamID", "Q"), ("mVehFilename", "s32"), ("mAttackMode", "h"),
    ("mFuelFraction", "B"), ("mDRSState", "?"), ("mExpansion", "B*4"),
])

ScoringInfo = _make("LMUScoringInfo", [  # ScoringInfoV01
    ("mTrackName", "s64"), ("mSession", "i"), ("mCurrentET", "d"), ("mEndET", "d"), ("mMaxLaps", "i"),
    ("mLapDist", "d"), ("mResultsStreamPointer", "B*8"), ("mNumVehicles", "i"), ("mGamePhase", "B"),
    ("mYellowFlagState", "c"), ("mSectorFlag", "B*3"), ("mStartLight", "B"), ("mNumRedLights", "B"),
    ("mInRealtime", "?"), ("mPlayerName", "s32"), ("mPlrFileName", "s64"), ("mDarkCloud", "d"),
    ("mRaining", "d"), ("mAmbientTemp", "d"), ("mTrackTemp", "d"), ("mWind", Vect3),
    ("mMinPathWetness", "d"), ("mMaxPathWetness", "d"), ("mGameMode", "B"), ("mIsPasswordProtected", "?"),
    ("mServerPort", "H"), ("mServerPublicIP", "I"), ("mMaxPlayers", "i"), ("mServerName", "s32"),
    ("mStartET", "f"), ("mAvgPathWetness", "d"), ("mSessionTimeRemaining", "f"), ("mTimeOfDay", "f"),
    ("mIsFixedSetup", "?"), ("mTrackGripLevel", "B"), ("mCloudCoverage", "B"),
    ("mTrackLimitsStepsPerPenalty", "B"), ("mTrackLimitsStepsPerPoint", "B"), ("mExpansion", "B*187"),
    ("mVehiclePointer", "B*8"),
])

AppState = _make("LMUApplicationState", [  # ApplicationStateV01
    ("mAppWindow", "Q"), ("mWidth", "I"), ("mHeight", "I"), ("mRefreshRate", "I"), ("mWindowed", "I"),
    ("mOptionsLocation", "B"), ("mOptionsPage", "s31"), ("mExpansion", "B*204"),
])

EVENT_NAMES = (  # SharedMemoryEvent enum order (SME_MAX omitted)
    "SME_ENTER", "SME_EXIT", "SME_STARTUP", "SME_SHUTDOWN", "SME_LOAD", "SME_UNLOAD",
    "SME_START_SESSION", "SME_END_SESSION", "SME_ENTER_REALTIME", "SME_EXIT_REALTIME",
    "SME_UPDATE_SCORING", "SME_UPDATE_TELEMETRY", "SME_INIT_APPLICATION", "SME_UNINIT_APPLICATION",
    "SME_SET_ENVIRONMENT", "SME_FFB",
)
Events = _make("LMUEvents", [(n, "I") for n in EVENT_NAMES])
Generic = _make("LMUGeneric", [("events", Events), ("gameVersion", "i"), ("FFBTorque", "f"), ("appInfo", AppState)])
PathData = _make("LMUPathData", [(n, f"s{MAX_PATH_LENGTH}") for n in
                                  ("userData", "customVariables", "stewardResults", "playerProfile", "pluginsFolder")])
ScoringData = _make("LMUScoringData", [
    ("scoringInfo", ScoringInfo), ("scoringStreamSize", "B*12"),
    ("vehScoringInfo", (VehicleScoring, MAX_MAPPED_VEHICLES)), ("scoringStream", "s65536"),
])
TelemetryData = _make("LMUTelemetryData", [
    ("activeVehicles", "B"), ("playerVehicleIdx", "B"), ("playerHasVehicle", "?"),
    ("telemInfo", (VehicleTelemetry, MAX_MAPPED_VEHICLES)),
])
ObjectOut = _make("LMUObjectOut", [
    ("generic", Generic), ("paths", PathData), ("scoring", ScoringData), ("telemetry", TelemetryData),
])

MAPPING_SIZE = C.sizeof(ObjectOut)


def offset_of(*path: str) -> int:
    """Byte offset of a dotted field path inside ObjectOut, e.g. offset_of('telemetry', 'telemInfo')."""
    cls: type[C.Structure] = ObjectOut
    total = 0
    for name in path:
        f = getattr(cls, name)
        total += f.offset
        t = dict(cls._fields_)[name]  # type: ignore[attr-defined]
        if isinstance(t, type) and issubclass(t, C.Structure):
            cls = t
    return total


OFF_GENERIC = offset_of("generic")
SIZE_GENERIC = C.sizeof(Generic)
OFF_SCORING_INFO = offset_of("scoring", "scoringInfo")
SIZE_SCORING_INFO = C.sizeof(ScoringInfo)
OFF_VEH_SCORING = offset_of("scoring", "vehScoringInfo")
SIZE_VEH_SCORING = C.sizeof(VehicleScoring)
OFF_TELEMETRY = offset_of("telemetry")
OFF_TELEM_INFO = offset_of("telemetry", "telemInfo")
SIZE_TELEM = C.sizeof(VehicleTelemetry)


def layout_table() -> list[tuple[str, int, int, str]]:
    """Flattened (path, offset, size, ctype) table of every top-level struct field (for docs)."""
    rows: list[tuple[str, int, int, str]] = []

    def walk(cls, prefix, base, depth):
        for name, typ in cls._fields_:
            f = getattr(cls, name)
            path = f"{prefix}{name}"
            rows.append((path, base + f.offset, f.size, getattr(typ, "__name__", str(typ))))
            if depth < 1 and isinstance(typ, type) and issubclass(typ, C.Structure):
                walk(typ, path + ".", base + f.offset, depth + 1)

    walk(ObjectOut, "", 0, 0)
    return rows
