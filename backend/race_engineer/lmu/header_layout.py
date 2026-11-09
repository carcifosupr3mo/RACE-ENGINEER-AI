"""Compute the binary layout (sizes/offsets) of the structs declared in the LMU C++ headers.

This is the strongest check we can do WITHOUT the game running: the installed
``<LMU>/Support/SharedMemoryInterface/*.hpp`` are the authoritative definition shipped by the game
developer. We parse the structs (MSVC x64 rules, ``#pragma pack``), and compare size and field
offsets with ``lmu.layout``. Pure text processing: nothing is executed, nothing is written.

Limits (reported, never hidden): no bit-fields, unions, templates or inheritance. A struct using
them is listed in ``unsupported`` and is NOT compared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import layout as L

_SCALARS = {
    "char": 1, "signed char": 1, "unsigned char": 1, "bool": 1, "int8_t": 1, "uint8_t": 1, "byte": 1,
    "short": 2, "unsigned short": 2, "int16_t": 2, "uint16_t": 2, "wchar_t": 2,
    "int": 4, "unsigned int": 4, "unsigned": 4, "long": 4, "unsigned long": 4, "int32_t": 4, "uint32_t": 4,
    "float": 4, "double": 8, "long long": 8, "unsigned long long": 8, "int64_t": 8, "uint64_t": 8,
    "__int64": 8, "unsigned __int64": 8, "size_t": 8,
}


@dataclass
class StructLayout:
    name: str
    size: int
    align: int
    fields: dict[str, tuple[int, int]] = field(default_factory=dict)   # name -> (offset, size)


def _strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _consts(text: str) -> dict[str, int]:
    c: dict[str, int] = {}
    for m in re.finditer(r"#define\s+(\w+)\s+(\d+)\b", text):
        c[m.group(1)] = int(m.group(2))
    for m in re.finditer(r"(?:static\s+)?(?:constexpr|const)\s+(?:unsigned\s+)?(?:int|long|size_t|uint32_t)\s+(\w+)\s*=\s*(\d+)\s*;", text):
        c[m.group(1)] = int(m.group(2))
    return c


def _enums(text: str, consts: dict[str, int]) -> dict[str, int]:
    """Sizes of enums (name -> bytes) and adds each enumerator's value into ``consts`` (needed for X_MAX)."""
    sizes: dict[str, int] = {}
    for m in re.finditer(r"enum(?:\s+class)?\s+(\w+)\s*(?::\s*([\w\s]+?))?\s*\{([^}]*)\}", text):
        name, base, body = m.group(1), (m.group(2) or "").strip(), m.group(3)
        sizes[name] = _SCALARS.get(base, 4) if base else 4
        val = -1
        for item in [i.strip() for i in body.split(",") if i.strip()]:
            if "=" in item:
                k, v = [x.strip() for x in item.split("=", 1)]
                try:
                    val = int(v, 0)
                except ValueError:
                    val = consts.get(v, val + 1)
            else:
                k, val = item, val + 1
            consts[k] = val
    return sizes


def parse_headers(text: str) -> tuple[dict[str, StructLayout], list[str]]:
    text = _strip(text)
    consts = _consts(text)
    enum_sizes = _enums(text, consts)
    structs: dict[str, StructLayout] = {}
    unsupported: list[str] = []
    pack = 8
    stack: list[int] = []
    # tokenise into: pragma pack lines and struct blocks, in source order
    pos = 0
    pat = re.compile(r"#pragma\s+pack\s*\(([^)]*)\)|(?:typedef\s+)?struct\s+(\w+)\s*(?::[^{]*)?\{", re.M)
    while True:
        m = pat.search(text, pos)
        if not m:
            break
        if m.group(1) is not None:
            arg = [a.strip() for a in m.group(1).split(",") if a.strip()]
            if arg[:1] == ["push"]:
                stack.append(pack)
                if len(arg) > 1 and arg[1].isdigit():
                    pack = int(arg[1])
            elif arg[:1] == ["pop"]:
                pack = stack.pop() if stack else 8
            elif arg and arg[0].isdigit():
                pack = int(arg[0])
            elif not arg:
                pack = 8
            pos = m.end()
            continue
        name = m.group(2)
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        pos = i
        if re.search(r"\bunion\b|:\s*\d+\s*;|\btemplate\b|\bvirtual\b", body):
            unsupported.append(name)
            continue
        lay = _layout_struct(name, body, pack, structs, consts, enum_sizes)
        if lay is None:
            unsupported.append(name)
        else:
            structs[name] = lay
    return structs, unsupported


def _layout_struct(name, body, pack, known, consts, enum_sizes) -> StructLayout | None:
    off, max_al = 0, 1
    fields: dict[str, tuple[int, int]] = {}
    for stmt in body.split(";"):
        stmt = " ".join(stmt.split())
        if not stmt or "(" in stmt or stmt.startswith(("static", "typedef", "using", "enum", "friend", "public", "private")):
            continue
        stmt = re.sub(r"^(?:public|private|protected)\s*:\s*", "", stmt)
        m = re.match(r"^((?:unsigned |signed |struct |const )*[\w:]+(?: long| int| char| short)*)\s+(.+)$", stmt)
        if not m:
            return None
        tname, decls = m.group(1).replace("struct ", "").replace("const ", "").strip(), m.group(2)
        if tname in known:
            size, al = known[tname].size, known[tname].align
        elif tname in _SCALARS:
            size = al = _SCALARS[tname]
        elif tname in enum_sizes:
            size = al = enum_sizes[tname]
        else:
            return None
        for d in decls.split(","):
            d = d.strip().lstrip("*&").strip()
            if d.startswith("*"):
                return None
            dm = re.match(r"^(\w+)((?:\s*\[\s*\w+\s*\])*)(?:\s*=.*)?$", d)
            if not dm:
                return None
            count = 1
            for dim in re.findall(r"\[\s*(\w+)\s*\]", dm.group(2)):
                n = int(dim) if dim.isdigit() else consts.get(dim)
                if n is None:
                    return None
                count *= n
            a = min(pack, al)
            off = (off + a - 1) // a * a
            fields[dm.group(1)] = (off, size * count)
            off += size * count
            max_al = max(max_al, a)
    total = (off + max_al - 1) // max_al * max_al
    return StructLayout(name, total, max_al, fields)


# our ctypes class -> header struct name (S397 naming)
_PAIRS = {
    "LMUVect3": "TelemVect3", "LMUWheel": "TelemWheelV01", "LMUVehicleTelemetry": "TelemInfoV01",
    "LMUVehicleScoring": "VehicleScoringInfoV01", "LMUScoringInfo": "ScoringInfoV01",
    "LMUApplicationState": "ApplicationStateV01", "LMUGeneric": "SharedMemoryGeneric",
    "LMUPathData": "SharedMemoryPathData", "LMUScoringData": "SharedMemoryScoringData",
    "LMUTelemetryData": "SharedMemoryTelemetryData", "LMUObjectOut": "SharedMemoryObjectOut",
}


def _ours() -> dict[str, type]:
    return {c.__name__: c for c in (L.Vect3, L.Wheel, L.VehicleTelemetry, L.VehicleScoring, L.ScoringInfo,
                                    L.AppState, L.Generic, L.PathData, L.ScoringData, L.TelemetryData, L.ObjectOut)}


def compare_with_layout(structs: dict[str, StructLayout]) -> dict:
    """Authoritative-header vs our layout. ``ok`` only when every compared struct matches in size and all common field offsets."""
    out, ok = [], True
    for ours_name, cls in _ours().items():
        hn = _PAIRS[ours_name]
        h = structs.get(hn)
        if h is None:
            out.append({"struct": hn, "status": "not_found_in_headers"})
            continue
        sz_ok = h.size == __import__("ctypes").sizeof(cls)
        bad, missing = [], []
        for fname, _t in cls._fields_:
            if fname not in h.fields:
                missing.append(fname)
            elif h.fields[fname][0] != getattr(cls, fname).offset:
                bad.append({"field": fname, "header_offset": h.fields[fname][0], "our_offset": getattr(cls, fname).offset})
        match = sz_ok and not bad
        ok &= match
        out.append({"struct": hn, "ours": ours_name, "header_size": h.size, "our_size": __import__("ctypes").sizeof(cls),
                    "size_match": sz_ok, "offset_mismatches": bad[:20], "fields_not_named_in_header": missing[:20],
                    "status": "match" if match else "MISMATCH"})
    return {"all_match": ok, "structs": out}


def verify_header_dir(header_dir: str | Path) -> dict:
    texts = []
    for p in sorted(Path(header_dir).glob("*.h*")):
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    if not texts:
        return {"checked": False, "reason": "no readable header"}
    structs, unsupported = parse_headers("\n".join(texts))
    res = compare_with_layout(structs)
    res.update(checked=True, structs_parsed=len(structs), unsupported=unsupported,
               note="MSVC x64 rules; unsupported structs are not compared")
    return res
