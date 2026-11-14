"""Talking to GitHub: list releases, pick the latest STABLE one, download its package. Standard library only.

Provenance rules (enforced on the first request AND on every redirect hop):
* https only, host must be on the allow-list (GitHub's own domains);
* the package and its checksum file must be assets of a release returned by the repository's official releases API
  and their download address must live under ``/<repo>/releases/download/``.
The checksum file protects against a corrupted or truncated download. It cannot protect against someone who can publish releases
on the repository: that is what code signing is for (docs/CODE-SIGNING.md).
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .versions import fmt, parse_loose, parse_stable

REPO = "carcifosupr3mo/RACE-ENGINEER-AI"
API = "https://api.github.com"
PACKAGE_NAME = {"win32": "RaceEngineerAI-win32.zip"}
SUMS_NAME = "SHA256SUMS.txt"
USER_AGENT = "RaceEngineerAI-updater"


class UpdateError(Exception):
    """Carries a message ALREADY written for the end user (plain Italian) plus a short machine code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Policy:
    schemes: tuple[str, ...] = ("https",)
    hosts: tuple[str, ...] = ("api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
    repo: str = REPO

    def check(self, url: str, *, asset: bool = False) -> None:
        u = urllib.parse.urlparse(url)
        if u.scheme not in self.schemes or (u.hostname or "") not in self.hosts:
            raise UpdateError("untrusted_source", "L'indirizzo di download non proviene da GitHub: per sicurezza non lo uso.")
        if asset and u.hostname == "github.com" and not u.path.startswith(f"/{self.repo}/releases/download/"):
            raise UpdateError("untrusted_source", "Il file non appartiene alle release ufficiali del progetto: per sicurezza non lo uso.")


@dataclass
class Release:
    tag: str
    version: tuple[int, int, int]
    notes: str
    page: str
    assets: dict[str, dict] = field(default_factory=dict)      # name -> {"url", "size"}

    @property
    def version_str(self) -> str:
        return fmt(self.version)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: Policy):
        self.policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.policy.check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(policy: Policy):
    return urllib.request.build_opener(_SafeRedirect(policy))


def _open(url: str, policy: Policy, timeout: float, headers: dict | None = None, *, asset: bool = False):
    policy.check(url, asset=asset)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json", **(headers or {})})
    return _opener(policy).open(req, timeout=timeout)


def network_error(e: BaseException) -> UpdateError:
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (403, 429):
            return UpdateError("rate_limited", "GitHub ha limitato le richieste per ora. Riprova più tardi.")
        return UpdateError("http", f"GitHub ha risposto con un errore ({e.code}). Riprova più tardi.")
    return UpdateError("offline", "Nessuna connessione a Internet: l'app funziona normalmente, gli aggiornamenti si controllano più tardi.")


def fetch_releases(policy: Policy, api_base: str = API, timeout: float = 8.0) -> list[dict]:
    try:
        with _open(f"{api_base}/repos/{policy.repo}/releases?per_page=30", policy, timeout) as r:
            data = json.loads(r.read(4_000_000).decode("utf-8"))
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise network_error(e) from e
    except ValueError as e:
        raise UpdateError("bad_reply", "La risposta di GitHub non è comprensibile. Riprova più tardi.") from e
    if not isinstance(data, list):
        raise UpdateError("bad_reply", "La risposta di GitHub non è comprensibile. Riprova più tardi.")
    return data


def latest_stable(raw: list[dict]) -> Release | None:
    """Highest version among releases that are neither drafts nor pre-releases AND whose tag is a plain MAJOR.MINOR.PATCH."""
    best: Release | None = None
    for r in raw:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        v = parse_stable(r.get("tag_name"))
        if v is None or (best is not None and v <= best.version):
            continue
        assets = {a["name"]: {"url": a.get("browser_download_url", ""), "size": int(a.get("size") or 0)}
                  for a in r.get("assets", []) if isinstance(a, dict) and a.get("name")}
        best = Release(tag=r["tag_name"], version=v, notes=(r.get("body") or "").strip()[:2000], page=r.get("html_url") or "", assets=assets)
    return best


def min_update_from(notes: str) -> tuple[int, int, int] | None:
    """A release can say 'min-update-from: 0.7.0' in its notes: older installs must install it by hand (installer)."""
    m = re.search(r"min-update-from:\s*v?(\d+\.\d+\.\d+)", notes, re.I)
    return parse_loose(m[1]) if m else None


def parse_sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m[2].strip()] = m[1].lower()
    return out


def read_small(url: str, policy: Policy, timeout: float = 15.0, limit: int = 1_000_000) -> str:
    try:
        with _open(url, policy, timeout, {"Accept": "application/octet-stream"}, asset=True) as r:
            return r.read(limit).decode("utf-8", "replace")
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise network_error(e) from e


def stream(url: str, policy: Policy, start: int = 0, timeout: float = 20.0, chunk: int = 256 * 1024) -> Iterator[bytes]:
    """Yield the file in chunks; ``start`` resumes after an interruption (HTTP Range). Raises UpdateError('interrupted') on network loss."""
    headers = {"Accept": "application/octet-stream"}
    if start:
        headers["Range"] = f"bytes={start}-"
    try:
        r = _open(url, policy, timeout, headers, asset=True)
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise network_error(e) from e
    with r:
        if start and getattr(r, "status", 200) != 206:
            raise UpdateError("no_resume", "Il server non permette di riprendere il download.")
        try:
            while True:
                b = r.read(chunk)
                if not b:
                    return
                yield b
        except (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException) as e:
            raise UpdateError("interrupted", "La connessione si è interrotta durante il download.") from e
