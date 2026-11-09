"""CLI: python -m race_engineer {diagnose|serve|record|inspect-duckdb|layout|verify-lmu|duckdb-report|setup-inspect|ai-test|endurance-sim}"""
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


def cmd_verify(args) -> int:
    from .lmu.verify import run
    rep, md = run(seconds=args.seconds, out_dir=args.out, shm_path=args.shm_path)
    print("\nVERDICT:", rep["verdict"])
    print("Report:", md, "(+ .json). Contains no credentials; share it if useful.")
    return 0 if not rep["verdict"].startswith(("NOT", "INCONCLUSIVE")) else 3


def cmd_duckdb_report(args) -> int:
    from .importers.diagnostic_report import report
    if not args.path:                      # no argument: list the native LMU telemetry files found (read-only scan)
        inst = find_install()
        files = sorted(inst.duckdb_files, reverse=True)
        print(f"{len(files)} .duckdb file(s) found in {inst.telemetry_dir}")
        for f in files[:30]:
            print(" ", f)
        return 0 if files else 2
    rep, md = report(args.path, out_dir=args.out)
    print(f"ok={rep['ok']} channels={len(rep['channels'])} events={len(rep['events'])} g_force={rep['g_force_analysis'].get('verdict')}")
    print("original file modified:", rep["original_modified"], "\nReport:", md)
    return 0 if rep["ok"] else 2


def cmd_setup_inspect(args) -> int:
    from .setup.inspect import find_setup_files, inspect_file
    if not args.path:
        inst = find_install()
        files = find_setup_files(inst.user_data) if inst.user_data else []
        print(f"{len(files)} .svm file(s) found" + ("" if files else " (UserData/player/Settings not found or empty)"))
        for f in files[:50]:
            print(" ", f)
        print("Pass one of them: python -m race_engineer setup-inspect <file>")
        return 0 if files else 2
    rep, md = inspect_file(args.path, out_dir=args.out)
    print(f"format={rep['format']} sha256={rep['file']['sha256'][:16]}... verbatim copy identical={rep.get('verbatim_copy_identical')}\nReport: {md}")
    return 0


def cmd_ai_test(args) -> int:
    from .ai.providers import selftest
    from .ai.providers.chain import get_manager
    rep = selftest.run(get_manager(), send=not args.no_send)
    print(json.dumps(rep, indent=2, default=str))
    return 0 if any(r.get("ok") for r in rep["routes"]) else 2


def cmd_endurance_sim(args) -> int:
    from .synthetic.endurance_sim import run
    rep = run(hours=args.hours, out_dir=args.out, seed=args.seed)
    return 0 if all(v in (True, None) for v in rep["checks"].values()) else 2


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
    p = sub.add_parser("duckdb-report", help="local schema/quality report of a real LMU .duckdb (nothing uploaded)")
    p.add_argument("path", nargs="?"); p.add_argument("--out"); p.set_defaults(fn=cmd_duckdb_report)
    p = sub.add_parser("setup-inspect", help="inspect a real LMU setup file (or list the .svm files found); keeps a verbatim copy")
    p.add_argument("path", nargs="?"); p.add_argument("--out"); p.set_defaults(fn=cmd_setup_inspect)
    p = sub.add_parser("ai-test", help="one real minimal request per configured FREE provider route (keys from env/Credential Manager)")
    p.add_argument("--no-send", action="store_true", help="only check keys and model listing"); p.set_defaults(fn=cmd_ai_test)
    p = sub.add_parser("endurance-sim", help="accelerated SYNTHETIC endurance simulation with fake AI providers")
    p.add_argument("--hours", type=float, default=24.0); p.add_argument("--out", default="."); p.add_argument("--seed", type=int, default=7)
    p.set_defaults(fn=cmd_endurance_sim)
    p = sub.add_parser("verify-lmu", help="real-LMU verification run + sanitized report (run on the Windows PC)")
    p.add_argument("--seconds", type=int, default=60); p.add_argument("--out"); p.add_argument("--shm-path")
    p.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
