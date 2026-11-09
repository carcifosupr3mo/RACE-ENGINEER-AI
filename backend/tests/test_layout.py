"""Internal-consistency tests of the binary layout.

These do NOT prove the layout matches a real LMU (no installation available): they guard against
regressions/typos in our own table. Real verification: docs/LMU-INTEGRATION.md, `diagnose` on Windows.
"""
import ctypes as C

from race_engineer.lmu import layout as L
from race_engineer.model.channels import CHANNELS, CHANNEL_BY_NAME


def test_pack_is_4_everywhere():
    for cls in (L.Vect3, L.Wheel, L.VehicleTelemetry, L.VehicleScoring, L.ScoringInfo, L.ObjectOut):
        assert cls._pack_ == 4


def test_top_level_offsets_are_contiguous():
    g, p, s, t = L.ObjectOut.generic, L.ObjectOut.paths, L.ObjectOut.scoring, L.ObjectOut.telemetry
    assert g.offset == 0
    assert p.offset == C.sizeof(L.Generic)
    assert s.offset == p.offset + C.sizeof(L.PathData)
    assert t.offset == s.offset + C.sizeof(L.ScoringData)
    assert L.MAPPING_SIZE == t.offset + C.sizeof(L.TelemetryData)


def test_derived_constants():
    assert L.OFF_SCORING_INFO == L.ObjectOut.scoring.offset
    assert L.OFF_VEH_SCORING == L.OFF_SCORING_INFO + C.sizeof(L.ScoringInfo) + 12  # scoringStreamSize[12]
    assert L.OFF_TELEM_INFO == L.OFF_TELEMETRY + 4   # 3 header bytes, padded to 4 by pack=4
    assert L.SIZE_TELEM == C.sizeof(L.VehicleTelemetry)
    assert L.MAX_MAPPED_VEHICLES == 104


def test_wheel_array_order_and_size():
    assert C.sizeof(L.VehicleTelemetry) > 4 * C.sizeof(L.Wheel)
    assert dict(L.VehicleTelemetry._fields_)["mWheels"] == L.Wheel * 4


def test_event_enum_order():
    names = [n for n, _ in L.Events._fields_]
    assert names[0] == "SME_ENTER" and names[10] == "SME_UPDATE_SCORING" and names[11] == "SME_UPDATE_TELEMETRY"


def test_layout_table_covers_everything():
    rows = L.layout_table()
    assert rows[0][0] == "generic" and any(r[0] == "telemetry.telemInfo" for r in rows)


def test_channel_catalogue_unique_and_typed():
    names = [c.name for c in CHANNELS]
    assert len(names) == len(set(names))
    assert {c.dtype for c in CHANNELS} <= {"DOUBLE", "INTEGER", "BOOLEAN", "VARCHAR"}
    assert all(c.kind in ("direct", "computed") for c in CHANNELS)
    assert CHANNEL_BY_NAME["speed_kmh"].kind == "computed"  # no native speed field in LMU
