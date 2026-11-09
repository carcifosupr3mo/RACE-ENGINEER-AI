"""CLI: python -m race_engineer {diagnose|serve|record|inspect-duckdb|layout}"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading
import time
from pathlib import Path

from .acquisition.engine import AcquisitionEngine
from .lmu import layout as L
from .lmu.diagnostics import STATE_LABELS_IT, build_report
from .lmu.discovery import find_install, is_lmu_process_running
from .lmu.reader import MappingNotFound, open_backend
from .storage.catalog import Catalog
from .storage.paths import data_dir


def _engine(args, record=True):
    root = data_dir()
    cat = Catalog(root / "catalog.sqlite")
    if getattr(args, "synthetic", None):
        from .synthetic.game import SyntheticGame
        game = SyntheticGame(args.synthetic, laps=getattr(args, "laps", 3))
        stop = threading.Event()

        def run():  # fake game publishing at real time (SYNTHETIC)
            while not stop.is_set() and game.step():
                time.sleep(0.01)
            game.end_session()
        threading.Thread(target=run, daemon=True).start()
        return AcquisitionEngine(lambda: game.backend, catalog=cat, data_root=root, record=record), cat
    return AcquisitionEngine(lambda: open_backend(path_override=args.shm_path), catalog=cat, data_root=root, record=record), cat


def cmd_diagnose(args) -> int:
    inst = find_install()
    size, err, ver = None, None, None
    try:
        be = open_backend(path_override=args.shm_path)
        size = be.size
        from .lmu.reader import SharedMemoryReader
        ver = SharedMemoryReader(be).read_generic().gameVersion
        be.close()
    except MappingNotFound as e:
        err = str(e)
    rep = build_report(inst, is_lmu_process_running(), size, err, ver, sys.platform)
    print(json.dumps({"install": dataclasses.asdict(inst), "report": rep.to_json()}, indent=2, default=str))
    return 0 if err is None else 2


def cmd_serve(args) -> int:
    import uvicorn
    from .api.app import create_app
    eng, cat = _engine(args)
    eng.start()
    inst = find_install() if not args.synthetic else None
    app = create_app(eng, cat, lan_enabled=args.lan, install=inst)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    if args.lan:
        print(f"LAN access ENABLED. Bearer token (keep private): {app.state.token}")
    print(f"UI: http://127.0.0.1:{args.port}/   (synthetic={bool(args.synthetic)})")
    try:
        uvicorn.run(app, host=host, port=args.port, log_level="warning")
    finally:
        eng.stop()
    return 0


def cmd_record(args) -> int:
    eng, cat = _engine(args)
    eng.start()
    t_end = time.time() + args.seconds
    try:
        while time.time() < t_end:
            time.sleep(1)
            s = eng.latest
            line = f"[{STATE_LABELS_IT[eng.state]}] rx={eng.stats.samples_received} lost={eng.stats.samples_lost} hz={eng.effective_hz():.0f}"
            if s:
                line += f" v={s['speed_kmh']:.0f}km/h rpm={s['rpm']:.0f} gear={s['gear']} thr={s['throttle']:.2f} brk={s['brake']:.2f} src={s.source.value}"
            print(line)
    finally:
        eng.stop()
    for row in cat.list_sessions()[:3]:
        print(row)
    return 0


def cmd_inspect(args) -> int:
    from .importers.lmu_duckdb import LmuDuckdb
    with LmuDuckdb(args.path, copy_first=True) as d:
        print(json.dumps(dataclasses.asdict(d.inspect()), indent=2, default=str))
    return 0


def cmd_layout(args) -> int:
    print(f"# mapping '{L.LMU_SHARED_MEMORY_NAME}' expected size {L.MAPPING_SIZE} B (pack={L.LAYOUT_PACK}); source: {L.LAYOUT_SOURCE}")
    for path, off, size, typ in L.layout_table():
        print(f"{off:8d} {size:8d}  {path}  [{typ}]")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="race_engineer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("diagnose", cmd_diagnose), ("serve", cmd_serve), ("record", cmd_record)):
        p = sub.add_parser(name)
        p.add_argument("--shm-path", help="read this file instead of the OS mapping (Wine bridge, tests)")
        p.add_argument("--synthetic", choices=["constant", "slower", "early_brake", "late_brake", "late_throttle",
                                               "missing_samples", "incomplete", "no_tyre_data", "mixed"],
                       help="use the SYNTHETIC fake game (never real LMU data)")
        p.add_argument("--laps", type=int, default=3, help="laps of the synthetic session")
        if name == "serve":
            p.add_argument("--lan", action="store_true", help="expose on the LAN (off by default; token required)")
            p.add_argument("--port", type=int, default=8765)
        if name == "record":
            p.add_argument("--seconds", type=int, default=15)
        p.set_defaults(fn=fn)
    p = sub.add_parser("inspect-duckdb"); p.add_argument("path"); p.set_defaults(fn=cmd_inspect)
    p = sub.add_parser("layout"); p.set_defaults(fn=cmd_layout)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
