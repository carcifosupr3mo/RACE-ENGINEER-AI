import mmap
import os

import pytest

from race_engineer.lmu import layout as L
from race_engineer.lmu.decode import decode_context, decode_sample
from race_engineer.lmu.reader import BytesBackend, FileBackend, MappingNotFound, SharedMemoryReader
from race_engineer.model.provenance import Provenance


def blank():
    buf = bytearray(L.MAPPING_SIZE)
    return buf, L.ObjectOut.from_buffer(buf)


def populate(o):
    o.scoring.scoringInfo.mTrackName = b"Test Track"
    o.scoring.scoringInfo.mSession = 11
    o.scoring.scoringInfo.mNumVehicles = 3
    o.scoring.scoringInfo.mAmbientTemp = 21.5
    o.scoring.scoringInfo.mWind.x, o.scoring.scoringInfo.mWind.z = 3.0, 4.0
    for i in range(3):
        o.scoring.vehScoringInfo[i].mIsPlayer = (i == 2)     # player is NOT slot 0
        o.scoring.vehScoringInfo[i].mLapDist = 100.0 * (i + 1)
    o.scoring.vehScoringInfo[2].mSector = 0
    o.scoring.vehScoringInfo[2].mVehicleClass = b"Hyper"
    o.telemetry.activeVehicles, o.telemetry.playerVehicleIdx, o.telemetry.playerHasVehicle = 3, 1, True
    t = o.telemetry.telemInfo[1]
    t.mElapsedTime, t.mLapStartET, t.mLapNumber = 100.0, 90.0, 4
    t.mLocalVel.x, t.mLocalVel.y, t.mLocalVel.z = 0.0, 0.0, 50.0
    t.mEngineRPM, t.mGear = 7000.0, 5
    t.mUnfilteredThrottle, t.mUnfilteredBrake, t.mUnfilteredSteering = 0.8, 0.1, -0.25
    t.mWheels[3].mTemperature[1] = 273.15 + 90.0
    t.mWheels[3].mPressure = 170.0
    t.mDentSeverity[5] = 2
    t.mVehicleName = b"Car A"
    # decoy telemetry in slot 0 must never be returned
    o.telemetry.telemInfo[0].mElapsedTime = 999.0
    o.telemetry.telemInfo[0].mEngineRPM = 1.0


def test_decode_picks_player_and_converts_units():
    buf, o = blank(); populate(o)
    r = SharedMemoryReader(BytesBackend(buf))
    snap = r.read_snapshot()
    assert snap.player_idx == 1 and snap.veh.mLapDist == 300.0
    s = decode_sample(snap.info, snap.veh, snap.telem)
    assert s["session_time_s"] == 100.0 and s["lap_time_s"] == 10.0 and s["rpm"] == 7000.0
    assert s["speed_kmh"] == pytest.approx(180.0)
    assert s["tyre_rr_temp_center_c"] == pytest.approx(90.0)     # Kelvin -> degC
    assert s["tyre_rr_pressure_kpa"] == 170.0
    assert s["sector"] == 3                                       # LMU 0 == sector 3
    assert s["damage_dent_max"] == 2 and s["wind_ms"] == pytest.approx(5.0)
    assert s["throttle"] == pytest.approx(0.8) and s["steering"] == pytest.approx(-0.25)
    ctx = decode_context(snap.generic, snap.info, snap.veh, snap.telem)
    assert ctx.track_name == "Test Track" and ctx.vehicle_class == "Hyper" and ctx.session_type == "race"


def test_provenance_is_tracked_per_channel():
    buf, o = blank(); populate(o)
    snap = SharedMemoryReader(BytesBackend(buf)).read_snapshot()
    s = decode_sample(snap.info, snap.veh, snap.telem, Provenance.LMU_SHM)
    assert s.provenance_of("rpm") is Provenance.LMU_SHM
    assert s.provenance_of("speed_kmh") is Provenance.COMPUTED
    s2 = decode_sample(snap.info, None, snap.telem, Provenance.LMU_SHM)
    assert s2.provenance_of("lap_dist_m") is Provenance.UNAVAILABLE and s2["lap_dist_m"] is None
    s3 = decode_sample(snap.info, snap.veh, snap.telem, Provenance.SYNTHETIC)
    assert s3.provenance_of("rpm") is Provenance.SYNTHETIC


def test_no_player_vehicle_gives_no_telemetry():
    buf, o = blank(); populate(o); o.telemetry.playerHasVehicle = False
    assert SharedMemoryReader(BytesBackend(buf)).read_snapshot().telem is None


def test_num_vehicles_garbage_is_clamped():
    buf, o = blank(); populate(o); o.scoring.scoringInfo.mNumVehicles = 10**6
    SharedMemoryReader(BytesBackend(buf)).read_snapshot()  # must not raise


def test_file_backend_is_read_only_and_never_creates(tmp_path):
    missing = tmp_path / "LMU_Data"
    with pytest.raises(MappingNotFound):
        FileBackend(str(missing))
    assert not missing.exists()                      # opening must not create the mapping
    p = tmp_path / "LMU_Data_real"
    p.write_bytes(bytes(L.MAPPING_SIZE))
    be = FileBackend(str(p))
    assert be.size == L.MAPPING_SIZE
    with pytest.raises(TypeError):
        be._mm[0] = 1                                # ACCESS_READ: writes are impossible
    be.close()


def test_empty_file_is_not_a_mapping(tmp_path):
    p = tmp_path / "x"; p.write_bytes(b"")
    with pytest.raises(MappingNotFound):
        FileBackend(str(p))


def test_torn_read_retry_returns_consistent_slot():
    buf, o = blank(); populate(o)
    be = BytesBackend(buf)
    reads = {"n": 0}
    orig = be.read
    off = L.OFF_TELEM_INFO + 1 * L.SIZE_TELEM

    def flaky(offset, length):
        if offset == off + L.VehicleTelemetry.mElapsedTime.offset and reads["n"] == 0:
            reads["n"] += 1
            o.telemetry.telemInfo[1].mElapsedTime = 101.0   # game updated between slot read and check read
        return orig(offset, length)
    be.read = flaky
    snap = SharedMemoryReader(be).read_snapshot()
    assert snap.telem.mElapsedTime == 101.0 and reads["n"] == 1
