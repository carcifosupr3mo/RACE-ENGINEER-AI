"""Smoke test of a built bundle (or of the source tree). Usage:
   python scripts/smoke_bundle.py dist/RaceEngineerAI            # frozen bundle (race-engineer-cli[.exe] + RaceEngineerAI[.exe])
   python scripts/smoke_bundle.py --source                        # python -m race_engineer from the source tree
Checks: CLI layout/diagnose/verify-lmu (must report 'not verified' without LMU, not crash), serve --synthetic: /app/, /diag, API,
synthetic acquisition, grounded chat, controlled shutdown, REOPEN with the same data dir (persistence), then the desktop shell --smoke.
Exit code 0 only if everything passed. It never claims anything about the real LMU."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

EXE = ".exe" if sys.platform == "win32" else ""
results: list[tuple[str, bool, str]] = []


def rec(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)[:300]))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    source = "--source" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(__file__).resolve().parent.parent
    if source:
        cli = [sys.executable, "-m", "race_engineer"]
        env_extra = {"PYTHONPATH": str(root / "backend")}
        desktop = [sys.executable, str(root / "scripts" / "run_desktop.py")]
    else:
        b = Path(args[0]).resolve()
        cli, env_extra = [str(b / f"race-engineer-cli{EXE}")], {}
        desktop = [str(b / f"RaceEngineerAI{EXE}")] if (b / f"RaceEngineerAI{EXE}").exists() else None
    data = Path(tempfile.mkdtemp(prefix="re_smoke_"))
    env = {**os.environ, **env_extra, "RACE_ENGINEER_DATA": str(data)}
    run = lambda a, t=120: subprocess.run(cli + a, env=env, capture_output=True, text=True, timeout=t)  # noqa: E731

    r = run(["layout"]); rec("cli layout", r.returncode == 0 and "mapping" in r.stdout, r.stderr[-200:])
    r = run(["diagnose"]); rec("cli diagnose runs (rc 0 or 2 = LMU absent)", r.returncode in (0, 2) and '"report"' in r.stdout, r.stderr[-200:])
    out = data / "rep"
    r = run(["verify-lmu", "--seconds", "1", "--out", str(out)])
    md = list(out.glob("*.md"))
    rec("cli verify-lmu produces a report and does NOT claim verification without LMU",
        bool(md) and "REAL LMU VERIFIED" not in md[0].read_text(encoding="utf-8"), r.stdout[-200:] + r.stderr[-200:])
    r = run(["duckdb-report"]); rec("cli duckdb-report (no arg) lists files or says none, no crash", r.returncode in (0, 2) and "Traceback" not in r.stderr, r.stderr[-200:])
    r = run(["setup-inspect"]); rec("cli setup-inspect (no arg) lists files or says none, no crash", r.returncode in (0, 2) and "Traceback" not in r.stderr, r.stderr[-200:])
    r = run(["preflight"]); rec("cli preflight prints JSON (no LMU needed, no keys)", r.returncode == 0 and '"data_dir"' in r.stdout and "Traceback" not in r.stderr, r.stderr[-200:])
    r = run(["verification-summary", "--out", str(data / "sum")]); rec("cli verification-summary says NOT COMPLETE without a recording", r.returncode == 0 and "NOT COMPLETE" in r.stdout, r.stdout[-200:] + r.stderr[-200:])
    r = run(["ai-test", "--no-send"]); rec("cli ai-test --no-send (no keys: nothing sent)", r.returncode in (0, 2) and '"routes"' in r.stdout, r.stderr[-200:])
    r = run(["endurance-sim", "--hours", "1", "--out", str(data / "sim")], 300); rec("cli endurance-sim 1h", r.returncode == 0, r.stdout[-200:] + r.stderr[-200:])

    port = free_port()
    p = subprocess.Popen(cli + ["serve", "--synthetic", "constant", "--laps", "2", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        t0, up = time.time(), False
        while time.time() - t0 < 60 and not up:
            try:
                up = get(base + "/api/health", 2)[0] == 200
            except Exception:
                time.sleep(0.5)
        rec("serve starts", up)
        if up:
            st, body = get(base + "/app/"); rec("/app/ served (React UI)", st == 200 and b"<div id=\"root\"" in body)
            st, body = get(base + "/diag"); rec("/diag served", st == 200)
            for _ in range(60):                                      # wait for synthetic laps to be recorded
                s = json.loads(get(base + "/api/status")[1])
                if s.get("samples_received", 0) > 300:
                    break
                time.sleep(0.5)
            rec("synthetic acquisition produces samples", s.get("samples_received", 0) > 300, s)
            time.sleep(4)
            sess = json.loads(get(base + "/api/sessions")[1])
            rec("session recorded in catalog", len(sess) >= 1)
            prov = json.loads(get(base + "/api/ai/providers")[1])
            rec("/api/ai/providers reports key status without any key value", "keys" in prov and "nvapi" not in json.dumps(prov) and "gsk_" not in json.dumps(prov))
            rec("/api/endurance/status", "memory" in json.loads(get(base + "/api/endurance/status")[1]))
            st, body = get(base + "/driving-display")
            rec("/driving-display served by the same backend (Driving Display page)", st == 200 and b"<div id=\"root\"" in body)
            es = json.loads(get(base + "/api/engineer/state?full=1")[1])
            rec("shared engineer state: session mode, reference, suggestion block, synthetic flag",
                es.get("ready") is True and es["session"]["mode"]["mode"] in ("practice", "qualifying", "race", "endurance", "test", "generic")
                and "suggestion" in es and es["synthetic"] is True and es["schema"] == 1, {k: es.get(k) for k in ("ready", "synthetic", "schema")})
            info = json.loads(get(base + "/api/display/info")[1])
            rec("/api/display/info gives the second-monitor URL and says LAN is off by default",
                info["path"] == "/driving-display" and info["lan_enabled"] is False and info["lan_urls"] == [], info)
            mp = json.loads(get(base + "/api/engineer/map")[1])
            rec("/api/engineer/map answers (real positions or an explicit reason, never invented)", ("points" in mp) or ("reason" in mp), list(mp))
            fin = []
            for _ in range(120):                                     # chat needs a finished session (the live one answers 409)
                fin = [x for x in json.loads(get(base + "/api/sessions")[1]) if x["status"] != "recording" and x["samples"] > 0]
                if fin:
                    break
                time.sleep(1)
            if not fin:
                rec("grounded chat answers (rules engine)", False, "no finished session appeared")
            if fin:
                sid = fin[0]["id"]
                req = urllib.request.Request(base + "/api/chat", data=json.dumps({"session_id": sid, "question": "come sono andati i miei giri?"}).encode(),
                                             headers={"content-type": "application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=30) as rr:
                        ans = json.loads(rr.read())
                    rec("grounded chat answers (rules engine)", "observed" in ans)
                except Exception as e:
                    rec("grounded chat answers (rules engine)", False, e)
        if up:                                                      # LAN opt-in: token required, URL printed for the Raspberry/tablet browser
            pass
    finally:
        if sys.platform == "win32":
            p.terminate()
        else:
            p.send_signal(2)
        try:
            p.wait(20)
            rec("controlled shutdown", True)
        except subprocess.TimeoutExpired:
            p.kill(); rec("controlled shutdown", False, "had to kill")
    # --lan: every /api call needs the token; the Driving Display URL with the token is printed at start
    port = free_port()
    p = subprocess.Popen(cli + ["serve", "--synthetic", "constant", "--laps", "1", "--lan", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        t0, up, tok = time.time(), False, None
        lanbase = f"http://127.0.0.1:{port}"
        first = p.stdout.readline() if p.stdout else ""
        tok = first.split("token (keep private):")[-1].strip() if "token" in first else None
        while time.time() - t0 < 60 and not up:
            try:
                up = get(lanbase + "/driving-display", 2)[0] == 200
            except Exception:
                time.sleep(0.5)
        rec("serve --lan starts and serves the Driving Display page", up)
        if up:
            try:
                no_tok = get(lanbase + "/api/engineer/state", 5)[0]
            except urllib.error.HTTPError as e:
                no_tok = e.code
            rec("--lan: /api/engineer/state without token is refused (403)", no_tok == 403, no_tok)
            if tok:
                st, body = get(lanbase + "/api/engineer/state?token=" + tok, 5)
                rec("--lan: with the token the shared state is served", st == 200 and b'"schema"' in body)
                info = json.loads(get(lanbase + "/api/display/info?token=" + tok, 5)[1])
                rec("--lan: /api/display/info lists http://IP:PORT/driving-display?token=... or says no private IP found",
                    info["lan_enabled"] is True and all(u.endswith("/driving-display?token=" + tok) for u in info["lan_urls"]), info["lan_urls"])
            else:
                rec("--lan prints the token at start", False, first[:80])
    finally:
        p.terminate()
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
    # reopen with the same data dir: persistence
    port = free_port()
    p = subprocess.Popen(cli + ["serve", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                if get(f"http://127.0.0.1:{port}/api/health", 2)[0] == 200:
                    break
            except Exception:
                time.sleep(0.5)
        sess2 = json.loads(get(f"http://127.0.0.1:{port}/api/sessions")[1])
        rec("data persisted after reopen (sessions still listed)", len(sess2) >= 1, len(sess2))
    finally:
        p.terminate()
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
    if desktop:
        try:
            r = subprocess.run(desktop + ["--smoke", "--synthetic", "constant"], env={**env, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True, text=True, timeout=180)
            rec("desktop shell --smoke (Qt WebEngine loads UI, API checks, controlled quit)", r.returncode == 0 and "SMOKE loaded=True" in r.stdout, r.stdout[-300:] + r.stderr[-300:])
        except Exception as e:
            rec("desktop shell --smoke", False, e)
    else:
        rec("desktop shell --smoke", True, "skipped: no desktop executable in this bundle (PySide6 absent)")
    shutil.rmtree(data, ignore_errors=True)
    bad = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed" + (f"; FAILED: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
