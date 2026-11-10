"""Progressive personal reference per (track, vehicle): the driver's best valid laps, kept and refined across sessions.

* The *anchor* is the fastest valid lap; it defines the time axis for the live delta and the map geometry.
* More valid laps => higher reliability (they also give the per-corner *targets*: the best zone time ever driven).
* Synthetic laps live in a separate store and can never become the reference of a real session.
* Only measured data is stored (distance-aligned channels incl. position); nothing is generated or smoothed into a "perfect lap".
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .align import AlignedLap
from .corners import Corner, apply_profile, detect_corners
from .driving import driving_metrics

MAX_LAPS = 8
KEEP_RATIO = 1.07           # laps slower than 107 % of the best are not kept as reference material
CH = ("speed_kmh", "throttle", "brake", "steering", "rpm", "gear", "pos_x_m", "pos_z_m")


@dataclass
class RefLap:
    number: int
    time_s: float
    aligned: AlignedLap
    session_id: str | None = None
    added_at: float = field(default_factory=time.time)

    @property
    def label(self) -> str:
        return f"giro {self.number}"


class PersonalReference:
    def __init__(self, track: str, vehicle: str, synthetic: bool, store_dir: Path | None = None, profile: list[dict] | None = None):
        self.track, self.vehicle, self.synthetic = track, vehicle, synthetic
        self.store_dir = Path(store_dir) if store_dir else None
        self.profile = profile
        self.laps: list[RefLap] = []
        self.version = 0
        self._corners: tuple | None = None
        self._targets: tuple | None = None
        self._lock = threading.RLock()
        self.loaded_from_disk = 0
        self.load()

    # ----------------------------------------------------------------- identity / storage
    def _path(self) -> Path | None:
        if not self.store_dir:
            return None
        h = hashlib.sha1(f"{self.track}|{self.vehicle}|{int(self.synthetic)}".encode()).hexdigest()[:16]
        return self.store_dir / f"{'synthetic_' if self.synthetic else ''}ref_{h}.npz"

    def save(self) -> None:
        p = self._path()
        if p is None or not self.laps:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        arrays, meta = {}, []
        for i, l in enumerate(self.laps):
            a = l.aligned
            arrays[f"grid{i}"] = a.grid.astype(np.float32)
            arrays[f"t{i}"] = a.t.astype(np.float32)
            for k, v in a.ch.items():
                arrays[f"{k}{i}"] = v.astype(np.float32)
            meta.append({"number": l.number, "time_s": l.time_s, "session_id": l.session_id, "added_at": l.added_at, "quality": a.quality,
                         "channels": list(a.ch)})
        arrays["meta"] = np.array(json.dumps({"track": self.track, "vehicle": self.vehicle, "synthetic": self.synthetic, "laps": meta}))
        tmp = p.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(p)

    def load(self) -> None:
        p = self._path()
        if p is None or not p.is_file():
            return
        try:
            z = np.load(p, allow_pickle=False)
            meta = json.loads(str(z["meta"]))
            for i, m in enumerate(meta["laps"]):
                ch = {k: z[f"{k}{i}"].astype(float) for k in m["channels"]}
                al = AlignedLap(m["number"], z[f"grid{i}"].astype(float), z[f"t{i}"].astype(float), ch, m["quality"])
                self.laps.append(RefLap(m["number"], m["time_s"], al, m.get("session_id"), m.get("added_at", 0.0)))
            self.laps.sort(key=lambda l: l.time_s)
            self.loaded_from_disk = len(self.laps)
            self.version += 1
        except Exception:        # a corrupt store must never stop the engineer: start learning again (the file is left untouched)
            self.laps = []
            self.loaded_from_disk = 0

    # ----------------------------------------------------------------- content
    @property
    def anchor(self) -> RefLap | None:
        return self.laps[0] if self.laps else None

    def add(self, aligned: AlignedLap, time_s: float, session_id: str | None = None) -> dict:
        """Offer a valid, aligned lap. Returns what changed (the version is bumped only when the reference really changes)."""
        with self._lock:
            if not aligned.quality.get("ok") or not time_s or time_s <= 0:
                return {"accepted": False, "reason": "lap not usable as reference", "new_anchor": False}
            if not all(k in aligned.ch for k in ("speed_kmh", "throttle", "brake")):
                return {"accepted": False, "reason": "missing channels", "new_anchor": False}
            best = self.laps[0].time_s if self.laps else None
            if best is not None and time_s > best * KEEP_RATIO:
                return {"accepted": False, "reason": "too slow to refine the reference", "new_anchor": False}
            old_anchor = self.anchor
            self.laps = [l for l in self.laps if not (l.session_id == session_id and l.number == aligned.number)]
            self.laps.append(RefLap(aligned.number, float(time_s), aligned, session_id))
            self.laps.sort(key=lambda l: l.time_s)
            del self.laps[MAX_LAPS:]
            new_anchor = self.anchor is not old_anchor and self.anchor.session_id == session_id and self.anchor.number == aligned.number
            self.version += 1
            self._corners = self._targets = None
            self.save()
            return {"accepted": True, "reason": "added", "new_anchor": bool(new_anchor), "n_laps": len(self.laps)}

    def corners(self) -> list[Corner]:
        with self._lock:
            if self.anchor is None:
                return []
            if self._corners is None or self._corners[0] != self.version:
                self._corners = (self.version, apply_profile(detect_corners(self.anchor.aligned), self.profile))
            return self._corners[1]

    def reliability(self) -> dict:
        n = len(self.laps)
        if n == 0:
            return {"level": "nessuno", "score": 0.0, "n_laps": 0, "spread_s": None, "reasons": ["nessun giro valido"], "learning": True}
        if n == 1:
            return {"level": "apprendimento", "score": 0.0, "n_laps": 1, "spread_s": None, "reasons": ["1 solo giro valido: servono almeno 2 per confrontare"],
                    "learning": True}
        ts = [l.time_s for l in self.laps[:5]]
        spread = float(np.std(ts)) if len(ts) >= 3 else None
        score = min(1.0, 0.25 * (n - 1))
        reasons = [f"{n} giri validi nel riferimento"]
        if spread is not None:
            cv = spread / ts[0]
            score *= 1.0 - min(0.5, cv * 10)
            reasons.append(f"dispersione dei migliori giri {spread:.3f} s")
        if self.corners() and all(c.provisional for c in self.corners()):
            score *= 0.9
            reasons.append("curve con numerazione provvisoria")
        lvl = "alta" if score >= 0.7 else "media" if score >= 0.4 else "bassa"
        return {"level": lvl, "score": round(float(score), 3), "n_laps": n, "spread_s": None if spread is None else round(spread, 3), "reasons": reasons,
                "learning": False}

    def targets(self) -> list[dict]:
        """Per corner: the best zone time over the kept laps (entry+mid+exit) and the measurements of that pass."""
        with self._lock:
            if self._targets is not None and self._targets[0] == self.version:
                return self._targets[1]
            out = []
            for c in self.corners():
                best = None
                anchor_zone = None
                for l in self.laps:
                    m = driving_metrics(l.aligned, c)
                    if any(m.seg_t.get(p) is None for p in ("entry", "mid", "exit")):
                        continue
                    z = sum(m.seg_t.values())
                    if l is self.anchor:
                        anchor_zone = z
                    if best is None or z < best[0]:
                        best = (z, l, m)
                if best is None:
                    continue
                z, l, m = best
                out.append({"corner": c.id, "best_lap": l.number, "best_session_id": l.session_id, "best_zone_s": round(z, 3),
                            "anchor_zone_s": None if anchor_zone is None else round(anchor_zone, 3),
                            "gain_vs_anchor_s": None if anchor_zone is None else round(anchor_zone - z, 3),
                            "brake_start_m": m.base.brake_start_m, "min_speed_kmh": m.base.min_speed_kmh, "exit_speed_kmh": m.base.exit_speed_kmh})
            self._targets = (self.version, out)
            return out

    def to_json(self) -> dict:
        a = self.anchor
        return {"track": self.track, "vehicle": self.vehicle, "synthetic": self.synthetic, "version": self.version,
                "anchor": None if a is None else {"lap": a.number, "time_s": round(a.time_s, 3), "session_id": a.session_id},
                "laps": [{"lap": l.number, "time_s": round(l.time_s, 3), "session_id": l.session_id} for l in self.laps],
                "reliability": self.reliability(), "loaded_from_disk": self.loaded_from_disk,
                "targets": self.targets(), "provenance": "synthetic" if self.synthetic else "computed"}
