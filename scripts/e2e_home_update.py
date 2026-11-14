"""Browser end-to-end of the Home / simulator choice / update flows (Playwright), against REAL servers of this app and a local stand-in for GitHub.

    python scripts/e2e_home_update.py [screenshot_dir]

Servers are started in-process with a synthetic fake game; update packages are real zip files served over real HTTP with real SHA-256 checks.
The final "restart" step is replaced by a recorder (a test cannot replace its own running files); the replacement itself is covered by backend/tests/test_updater.py.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from fake_github import FakeGithub, release  # noqa: E402
from race_engineer.acquisition.engine import AcquisitionEngine  # noqa: E402
from race_engineer.api.app import create_app  # noqa: E402
from race_engineer.storage.catalog import Catalog  # noqa: E402
from race_engineer.synthetic.game import SyntheticGame  # noqa: E402
from race_engineer.updater.manager import UpdateManager  # noqa: E402
from race_engineer.updater.source import Policy  # noqa: E402

SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
SHOTS.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" — " + detail if detail and not ok else ""), flush=True)


class Server:
    def __init__(self, data: Path, gh: FakeGithub | None, version="0.6.7", auto=None, offline=False):
        data.mkdir(parents=True, exist_ok=True)
        self.catalog = Catalog(data / "catalog.sqlite")
        if auto is not None:
            self.catalog.put_setting("updates.auto", auto)
        game = SyntheticGame("constant", laps=2)
        self.engine = AcquisitionEngine(lambda: game.backend, catalog=self.catalog, data_root=data, process_probe=lambda: True)
        inst = data / "inst"; inst.mkdir(exist_ok=True); (inst / "RaceEngineerUpdater.exe").write_bytes(b"u")
        self.handover = []
        pol = Policy(schemes=("http",), hosts=("127.0.0.1",))
        base = gh.base if gh else "http://127.0.0.1:9"        # nothing listens there = no Internet
        self.updater = UpdateManager(self.catalog, version, data, policy=pol, api_base=base, platform="win32", frozen=True, install_dir=inst,
                                     launcher=self.handover.append, timeout=2)
        self.app = create_app(self.engine, self.catalog, updater=self.updater)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.srv = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        threading.Thread(target=self.srv.run, daemon=True).start()
        while not self.srv.started:
            time.sleep(0.05)
        self.engine.start()
        self.updater.check_in_background()
        self.url = f"http://127.0.0.1:{self.port}/app/"

    def stop(self):
        self.srv.should_exit = True; self.engine.stop(); self.catalog.close(); time.sleep(0.3)


def main():
    root = Path(tempfile.mkdtemp())
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": os.environ["CHROMIUM_PATH"]} if os.environ.get("CHROMIUM_PATH") else {}))
        def page(w=1280, h=800):
            return br.new_page(viewport={"width": w, "height": h})

        # ---------------------------------------------------------------- A: first start, no Internet
        d = root / "A"; s = Server(d, None); p = page()
        p.goto(s.url); p.wait_for_selector("[data-testid=sim-picker]")
        check("A1 first start shows 'Scegli il tuo simulatore'", "Scegli il tuo simulatore" in p.inner_text("h2.hero"))
        check("A2 first start has no active-sim card", p.query_selector("[data-testid=active-sim]") is None)
        check("A3 ten simulators listed", len(p.query_selector_all("article.simcard")) == 10)
        check("A4 only LMU can be chosen", len(p.query_selector_all("button.primary[data-testid^=choose-]")) == 1 and p.is_enabled("[data-testid=choose-lmu]"))
        dis = p.eval_on_selector_all("article.simcard.off button", "bs => bs.every(b => b.disabled)")
        check("A5 unsupported simulators have disabled buttons", dis)
        opts = p.eval_on_selector_all("[data-testid=sim-menu] option", "os => os.filter(o => o.disabled).length")
        check("A6 menu disables the 9 unsupported ones", opts == 9, str(opts))
        check("A7 no update popup without Internet", p.query_selector("[data-testid=update-popup]") is None)
        p.screenshot(path=str(SHOTS / "01-first-run.png"), full_page=True)
        p.click("[data-testid=choose-lmu]"); p.wait_for_selector("[data-testid=active-sim]")
        check("A8 after choosing: active card names the simulator", p.inner_text("[data-testid=active-sim-name]") == "Le Mans Ultimate")
        check("A9 menu follows the choice", p.eval_on_selector("[data-testid=sim-menu]", "e => e.value") == "lmu")
        check("A10 buttons Continua/Apri and Cambia simulatore present", p.is_visible("[data-testid=continue]") and p.is_visible("[data-testid=change-sim]"))
        time.sleep(2.5)
        p.screenshot(path=str(SHOTS / "02-home-active.png"), full_page=True)
        check("A11 connection state is plain language", len(p.inner_text("[data-testid=active-sim-status]")) > 8, p.inner_text("[data-testid=active-sim-status]"))
        p.click("[data-testid=change-sim]"); p.wait_for_selector("[data-testid=sim-picker]")
        check("A12 'Cambia simulatore' reopens the choice", p.is_visible("[data-testid=choose-lmu]"))
        p.click("text=Annulla"); p.wait_for_selector("[data-testid=active-sim]")
        p.click("[data-testid=continue]"); p.wait_for_selector("[data-testid=live]")
        check("A13 Continua opens the live data", True)
        p.click("[data-testid=nav-settings]"); p.wait_for_selector("[data-testid=updates]")
        check("A14 settings show installed version", p.inner_text("[data-testid=installed-version]") == "0.6.7")
        p.click("[data-testid=check-update]"); time.sleep(1.5)
        check("A15 manual check offline explains calmly", "Internet" in p.inner_text("[data-testid=update-line]"), p.inner_text("[data-testid=update-line]"))
        p.screenshot(path=str(SHOTS / "03-settings-updates.png"), full_page=True)
        p.click("[data-testid=auto-update]"); time.sleep(0.8)
        check("A16 auto-update switch turns on", p.get_attribute("[data-testid=auto-update]", "aria-checked") == "true")
        p.close(); s.stop()

        # ---------------------------------------------------------------- B: restart, same data folder
        s = Server(d, None); p = page()
        p.goto(s.url); p.wait_for_selector("[data-testid=active-sim]")
        check("B1 after restart the last simulator is loaded without asking", p.inner_text("[data-testid=active-sim-name]") == "Le Mans Ultimate" and p.query_selector("[data-testid=sim-picker]") is None)
        p.click("[data-testid=nav-settings]"); p.wait_for_selector("[data-testid=updates]")
        check("B2 auto-update choice also survived", p.get_attribute("[data-testid=auto-update]", "aria-checked") == "true")
        p.close(); s.stop()

        # ---------------------------------------------------------------- C: new release, auto OFF -> popup, skip
        gh = FakeGithub(slow=0.0); d = root / "C"
        s = Server(d, gh, auto=False); p = page()
        p.goto(s.url); p.wait_for_selector("[data-testid=update-popup]", timeout=15000)
        txt = p.inner_text("[data-testid=update-popup]")
        check("C1 popup title and question", "Nuovo aggiornamento disponibile" in txt and "Vuoi installarla adesso?" in txt)
        check("C2 popup shows installed + new version + news", "0.6.7" in txt and "0.7.0" in txt and "Novità: prova" in p.inner_text("[data-testid=update-notes]"))
        check("C3 two buttons AGGIORNA / SALTA PER ORA", p.is_visible("[data-testid=update-go]") and p.is_visible("[data-testid=update-skip]"))
        p.screenshot(path=str(SHOTS / "04-update-popup.png"))
        p.click("[data-testid=update-skip]"); time.sleep(0.8)
        check("C4 skip closes the popup and the app starts normally", p.query_selector("[data-testid=update-popup]") is None and p.query_selector("[data-testid=sim-picker]") is not None)
        check("C5 nothing was downloaded or installed", not s.handover and not any("zip" in r[0] for r in gh.requests))
        p.reload(); time.sleep(3)
        check("C6 popup does not come back in the same session", p.query_selector("[data-testid=update-popup]") is None)
        p.close(); s.stop(); gh.close()

        # ---------------------------------------------------------------- D: AGGIORNA with a throttled download
        gh = FakeGithub(package=__import__("fake_github").make_zip({"RaceEngineerAI.exe": b"x", "RaceEngineerUpdater.exe": b"u", "_internal/big.bin": __import__("os").urandom(3_000_000)}), slow=0.12)
        d = root / "D"; s = Server(d, gh, auto=False); p = page()
        p.goto(s.url); p.wait_for_selector("[data-testid=update-go]", timeout=15000)
        p.click("[data-testid=update-go]"); p.wait_for_selector("[data-testid=update-screen]")
        import urllib.request
        seen = set(); widths = []; api_states = []
        stop_sampling = threading.Event()

        def sample():                                    # the server's own numbers, sampled fast in the background
            while not stop_sampling.is_set():
                try:
                    st = json.load(urllib.request.urlopen(s.url.replace("/app/", "/api/update/status")))
                    api_states.append((st["state"], st["progress"]))
                except Exception:
                    pass
                time.sleep(0.02)
        threading.Thread(target=sample, daemon=True).start()
        t0 = time.time()
        while time.time() - t0 < 30 and not any((pr or 0) > 0.3 for stt, pr in api_states if stt == "downloading"):
            time.sleep(0.05)
        seen.add(p.inner_text("[data-testid=update-message]", timeout=2000)[:40])      # what the person sees, mid-download
        widths.append(float(p.eval_on_selector(".progress i", "e => parseFloat(e.style.width)")))
        p.screenshot(path=str(SHOTS / "05-update-progress.png"))
        while time.time() - t0 < 40 and not (api_states and api_states[-1][0] == "restarting"):
            time.sleep(0.05)
        stop_sampling.set()
        dl = [pr for stt, pr in api_states if stt == "downloading" and pr is not None]
        check("D1 update screen appears with the 5 steps", True)
        check("D2 real download progress: many increasing values from 0 to 1", len(set(dl)) >= 5 and dl == sorted(dl) and dl[-1] >= 0.9, f"{len(set(dl))} values {dl[:3]}..{dl[-3:]}")
        check("D3 screen shows downloading text and a bar that is not empty mid-download", any("Scarico" in m for m in seen) and widths and widths[0] > 0, str((seen, widths)))
        order = [stt for i, (stt, _) in enumerate(api_states) if i == 0 or stt != api_states[i - 1][0]]
        check("D3b states go downloading -> verifying -> (installing) -> restarting", order[0] == "downloading" and order[-1] == "restarting", str(order))
        check("D4 hand-over to the updater happened with verified staging", bool(s.handover) and (Path(s.handover[0]["staging"]) / "RaceEngineerAI.exe").is_file())
        time.sleep(1.2)
        check("D5 screen tells the app will restart by itself", "riapre" in p.inner_text("[data-testid=update-screen]"))
        p.screenshot(path=str(SHOTS / "06-update-restarting.png"))
        # the next start reads the helper's result file
        (d / "update_result.json").write_text(json.dumps({"ok": True, "from": "0.6.7", "to": "0.7.0", "rolled_back": False, "error": None}))
        p.close(); s.stop()
        s = Server(d, gh, version="0.7.0", auto=False); p = page(); p.goto(s.url); p.wait_for_selector("[data-testid=update-result]", timeout=10000)
        check("D6 after restart: confirmation of the completed update", "Aggiornamento completato" in p.inner_text("[data-testid=update-result]") and "0.7.0" in p.inner_text("[data-testid=update-result]"))
        p.screenshot(path=str(SHOTS / "07-update-done.png"))
        p.click("[data-testid=update-result] button"); time.sleep(0.8)
        check("D7 confirmation can be dismissed and does not return", p.query_selector("[data-testid=update-result]") is None and not (d / "update_result.json").exists())
        p.close(); s.stop(); gh.close()

        # ---------------------------------------------------------------- E: auto ON -> straight to the update screen, no question
        gh = FakeGithub(slow=0.05); d = root / "E"; s = Server(d, gh, auto=True); p = page()
        p.goto(s.url)
        try:
            p.wait_for_selector("[data-testid=update-screen]", timeout=15000); ok = True
        except Exception:
            ok = False
        check("E1 auto ON: update starts by itself, no popup", ok and p.query_selector("[data-testid=update-popup]") is None)
        t0 = time.time()
        while time.time() - t0 < 20 and not s.handover:
            time.sleep(0.1)
        check("E2 auto ON: hand-over done", bool(s.handover))
        p.close(); s.stop(); gh.close()

        # ---------------------------------------------------------------- F: corrupted package
        gh = FakeGithub(tamper=True); d = root / "F"; s = Server(d, gh, auto=False); p = page()
        p.goto(s.url); p.wait_for_selector("[data-testid=update-go]", timeout=15000); p.click("[data-testid=update-go]")
        p.wait_for_selector("[data-testid=update-error]", timeout=15000)
        et = p.inner_text("[data-testid=update-error]")
        check("F1 corrupted package: clear message, nothing installed", "danneggiato" in et and not s.handover, et)
        check("F2 offers retry and continue without updating", p.is_visible("text=Riprova") and p.is_visible("text=Continua senza aggiornare"))
        p.screenshot(path=str(SHOTS / "08-update-error.png"))
        p.click("text=Continua senza aggiornare"); time.sleep(0.8)
        check("F3 'Continua senza aggiornare' returns to the app", p.query_selector("[data-testid=update-screen]") is None and p.is_visible("[data-testid=nav-live]"))
        p.close(); s.stop(); gh.close()

        # ---------------------------------------------------------------- G: layout at phone/tablet width
        d = root / "A"; s = Server(d, None); p = page(390, 800); p.goto(s.url); p.wait_for_selector("[data-testid=active-sim]")
        over = p.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        check("G1 no horizontal scroll at phone width", not over)
        p.screenshot(path=str(SHOTS / "09-home-phone.png"), full_page=True)
        p.close(); s.stop()
        br.close()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed; screenshots in {SHOTS}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
