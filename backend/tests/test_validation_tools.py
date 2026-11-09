"""Tools for the real-LMU / real-file validation phase (run on synthetic inputs here)."""
import json
from pathlib import Path

import duckdb
import numpy as np

from race_engineer.importers.diagnostic_report import gforce_analysis, report
from race_engineer.importers.lmu_duckdb import LmuDuckdb
from race_engineer.lmu import layout as L
from race_engineer.lmu.header_layout import compare_with_layout, parse_headers, verify_header_dir
from race_engineer.lmu.verify import check_read_only_source, sanitize
from race_engineer.synthetic.lmu_duckdb_fixture import build


# ---------------------------------------------------------------- header parser
HDR = """
#pragma pack(push, 4)
// comment
struct A { double x; unsigned char b; int c; };       /* 8 + 1 (+3) + 4 = 16 */
struct B { char name[5]; double d; A a; };           // 5 (+3 pad to 4?) pack=4 -> d at 8
#pragma pack(pop)
struct C { char c; double d; };                       // default pack 8 -> d at 8, size 16
"""


def test_header_parser_pack_rules():
    s, bad = parse_headers(HDR)
    assert not bad
    assert s["A"].size == 16 and s["A"].fields["c"][0] == 12
    assert s["B"].fields["d"][0] == 8 and s["B"].fields["a"][0] == 16 and s["B"].size == 32
    assert s["C"].fields["d"][0] == 8 and s["C"].size == 16


def test_header_parser_constants_and_enum_sizes():
    s, _ = parse_headers("enum E { E_A, E_B, E_MAX }; static constexpr int N = 3;\n#pragma pack(4)\nstruct S { E e[E_MAX]; float f[N]; };")
    assert s["S"].size == 2 * 4 + 3 * 4  # E_MAX == 2


def test_unsupported_structs_are_reported_not_compared():
    s, bad = parse_headers("struct U { union { int a; float b; } x; };")
    assert "U" in bad and "U" not in s


def _header_from_layout() -> str:
    import ctypes as C
    from race_engineer.lmu.header_layout import _PAIRS, _ours
    T = {C.c_double: "double", C.c_float: "float", C.c_int: "int", C.c_uint: "unsigned int", C.c_ubyte: "unsigned char",
         C.c_byte: "signed char", C.c_bool: "bool", C.c_short: "short", C.c_ushort: "unsigned short",
         C.c_ulonglong: "unsigned long long", C.c_char: "char"}

    def ty(t):
        if hasattr(t, "_length_"):
            a, b = ty(t._type_)
            return a, b + f"[{t._length_}]"
        if t.__name__ == "LMUEvents":
            return "unsigned int", f"[{len(t._fields_)}]"
        if issubclass(t, C.Structure):
            return _PAIRS[t.__name__], ""
        return T[t], ""
    out = ["#pragma pack(push, 4)"]
    for n, c in _ours().items():
        out.append(f"struct {_PAIRS[n]} {{")
        for f, t in c._fields_:
            a, b = ty(t)
            out.append(f"  {a} {f}{b};")
        out.append("};")
    return "\n".join(out + ["#pragma pack(pop)"])


def test_layout_roundtrip_through_header_parser(tmp_path):
    (tmp_path / "SharedMemoryInterface.hpp").write_text(_header_from_layout())
    r = verify_header_dir(tmp_path)
    assert r["checked"] and r["all_match"], r
    assert r["structs_parsed"] >= 11


def test_header_mismatch_is_detected(tmp_path):
    txt = _header_from_layout().replace("double mElapsedTime;", "float mElapsedTime;", 1)
    (tmp_path / "x.hpp").write_text(txt)
    r = verify_header_dir(tmp_path)
    assert r["all_match"] is False
    assert any(s["status"] == "MISMATCH" for s in r["structs"])


# ---------------------------------------------------------------- read-only / sanitize
def test_read_only_static_scan_clean():
    r = check_read_only_source()
    assert r["ok"], r


def test_sanitize_shortens_user_paths():
    assert "alice" not in sanitize(r"C:\Users\alice\AppData\x")


# ---------------------------------------------------------------- duckdb report
def _add_g(path: Path, swap: bool):
    with LmuDuckdb(path, copy_first=True) as d:
        spd = d.read_channel("Ground Speed")
        st = d.read_channel("Steering Pos")
    v = spd["values"][:, 0] / 3.6
    acc = np.gradient(np.convolve(v, np.ones(5) / 5, mode="same"), 1 / 100) / 9.81
    lat = st["values"][:, 0] / 100 * v ** 2 / 400.0
    long_, lat_ = (lat, acc) if swap else (acc, lat)
    con = duckdb.connect(str(path))
    for name, arr in (("G Force Long", long_), ("G Force Lat", lat_)):
        con.execute(f'CREATE TABLE "{name}"(value FLOAT)')
        con.execute(f'INSERT INTO "{name}" SELECT unnest(?)', [[float(x) for x in arr]])
        con.execute("INSERT INTO channelsList VALUES (?,?,?)", [name, 100, "g"])
    con.close()


def test_report_never_modifies_original_and_redacts(tmp_path):
    f = build(tmp_path / "a.duckdb", "constant", laps=2)
    rep, md = report(f, out_dir=tmp_path / "out")
    assert rep["original_modified"] is False
    assert rep["metadata"]["DriverName"] == "<redacted>"
    assert md.exists() and (md.with_suffix(".json")).exists()
    assert rep["g_force_analysis"]["verdict"] == "not_testable"
    json.loads(md.with_suffix(".json").read_text())


def test_gforce_verdict_as_named(tmp_path):
    f = build(tmp_path / "b.duckdb", "mixed", laps=3)
    _add_g(f, swap=False)
    with LmuDuckdb(f, copy_first=True) as d:
        g = gforce_analysis(d)
    assert g["verdict"] == "as_named", g


def test_gforce_verdict_swapped_is_reported_not_applied(tmp_path):
    f = build(tmp_path / "c.duckdb", "mixed", laps=3)
    _add_g(f, swap=True)
    with LmuDuckdb(f, copy_first=True) as d:
        g = gforce_analysis(d)
    assert g["verdict"] == "swapped", g
    assert "OUT of the import mapping" in g["action"]


# ---------------------------------------------------------------- setup inspection
SVM = """﻿[GENERAL]
Notes=""
VehicleClassSetting="Hypercar"//class
[FRONTLEFT]
CamberSetting=17//-2.8 deg
PressureSetting=20//145 kPa
[BRAKES]
BrakeBalanceSetting=60//55.5:44.5
"""


def test_setup_inspect_keeps_verbatim_copy_and_no_limits(tmp_path, monkeypatch):
    from race_engineer.setup.inspect import inspect_file
    monkeypatch.setenv("RACE_ENGINEER_DATA", str(tmp_path / "d"))
    f = tmp_path / "car.svm"
    f.write_bytes(SVM.encode("utf-8"))
    before = f.read_bytes()
    rep, md = inspect_file(f, out_dir=tmp_path / "o")
    assert rep["format"] == "svm" and rep["limits_in_file"] is False and rep["keys"] == 5
    assert rep["verbatim_copy_identical"] is True and f.read_bytes() == before and rep["original_modified"] is False
    assert "kPa" in rep["units_in_display"] or "deg" in rep["units_in_display"]


def test_svm_import_is_verbatim_and_advisor_refuses_numbers(tmp_path):
    from race_engineer.setup import advisor
    from race_engineer.storage.catalog import Catalog
    cat = Catalog(tmp_path / "c.sqlite")
    r = advisor.import_setup(cat, SVM, "file")
    row = cat.db.execute("select raw_text, sha256, fmt from setups where id=?", (r["id"],)).fetchone()
    assert row["raw_text"] == SVM and row["fmt"] == "svm" and len(row["sha256"]) == 64
    assert r["parameters_with_limits"] == 0 and "cannot propose" in r["warning"]
    out = advisor.advise(cat, r["id"], [{"type": "early_braking", "corner": "P1", "lap": 2, "evidence": {}}])
    assert out["proposals"] == []


def test_unknown_setup_format_rejected(tmp_path):
    import pytest
    from race_engineer.setup import advisor
    from race_engineer.storage.catalog import Catalog
    with pytest.raises(ValueError):
        advisor.import_setup(Catalog(tmp_path / "c.sqlite"), "just some text", "file")
