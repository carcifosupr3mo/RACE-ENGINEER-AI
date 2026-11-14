"""A local stand-in for GitHub (releases API + asset downloads) so the updater is tested with real HTTP, real files, real hashing."""
from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from race_engineer.updater.source import Policy

REPO = "carcifosupr3mo/RACE-ENGINEER-AI"


def make_zip(files: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


def good_package(marker: str = "new") -> bytes:
    return make_zip({"RaceEngineerAI.exe": f"#!/bin/sh\nexit 0\n# {marker}\n".encode(), "RaceEngineerUpdater.exe": b"updater", "_internal/lib.dll": __import__("os").urandom(20000), "build_info.json": b"{}"})


class FakeGithub:
    def __init__(self, releases: list[dict] | None = None, package: bytes | None = None, *, sums: str | None = None, drop_after: int | None = None,
                 drop_times: int = 1, status: int = 200, tamper: bool = False, slow: float = 0.0):
        self.package = package if package is not None else good_package()
        self.sha = hashlib.sha256(self.package).hexdigest()
        self.sums = sums if sums is not None else f"{self.sha}  RaceEngineerAI-win32.zip\n"
        self.drop_after, self.drops_left, self.status, self.tamper, self.slow = drop_after, drop_times, status, tamper, slow
        self.requests: list[tuple[str, str | None]] = []
        self.releases = releases
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append((self.path, self.headers.get("Range")))
                if outer.status != 200 and self.path.startswith("/repos"):
                    self.send_response(outer.status); self.end_headers(); return
                if self.path.startswith(f"/repos/{REPO}/releases"):
                    return self._send(json.dumps(outer.releases if outer.releases is not None else outer.default_releases()).encode(), "application/json")
                if self.path.endswith("SHA256SUMS.txt"):
                    return self._send(outer.sums.encode(), "text/plain")
                if self.path.endswith("RaceEngineerAI-win32.zip"):
                    data = outer.package
                    if outer.tamper:
                        data = data[:100] + b"X" + data[101:]
                    start = 0
                    rng = self.headers.get("Range")
                    if rng:
                        start = int(rng.split("=")[1].rstrip("-"))
                        self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                    else:
                        self.send_response(200)
                    body = data[start:]
                    self.send_header("Content-Length", str(len(body))); self.end_headers()
                    if outer.drop_after is not None and outer.drops_left > 0:
                        outer.drops_left -= 1
                        self.wfile.write(body[:outer.drop_after]); self.wfile.flush()
                        self.connection.close()
                        return
                    if outer.slow:                               # throttled so a browser can watch the real progress bar move
                        import time
                        for i in range(0, len(body), 65536):
                            self.wfile.write(body[i:i + 65536]); self.wfile.flush(); time.sleep(outer.slow)
                        return
                    self.wfile.write(body); return
                self.send_response(404); self.end_headers()

            def _send(self, b: bytes, ct: str):
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def default_releases(self, tag="v0.7.0", notes="Novità: prova", **kw) -> list[dict]:
        return [release(self.base, tag, notes, len(self.package), **kw)]

    @property
    def policy(self) -> Policy:
        return Policy(schemes=("http",), hosts=("127.0.0.1",), repo=REPO)

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


def release(base: str, tag: str, notes: str = "", size: int = 1000, *, prerelease=False, draft=False, assets=True) -> dict:
    url = f"{base}/{REPO}/releases/download/{tag}"
    a = [{"name": "RaceEngineerAI-win32.zip", "browser_download_url": f"{url}/RaceEngineerAI-win32.zip", "size": size},
         {"name": "SHA256SUMS.txt", "browser_download_url": f"{url}/SHA256SUMS.txt", "size": 100}] if assets else []
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": notes, "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "assets": a}
