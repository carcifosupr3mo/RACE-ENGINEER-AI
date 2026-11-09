"""Acquisition engine: connection state machine, sample dedup, loss accounting, recording."""
from __future__ import annotations

import collections
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..lmu.decode import decode_context, decode_sample
from ..lmu.diagnostics import ConnState
from ..lmu.discovery import is_lmu_process_running
from ..lmu.reader import Backend, MappingNotFound, SharedMemoryReader, Snapshot
from ..lmu import layout as L
from ..model.provenance import Provenance
from ..model.sample import Sample, SessionContext
from ..storage.catalog import Catalog
from ..storage.recorder import SessionRecorder
from ..synthetic.track import SYNTH_PREFIX


def rss_mb() -> float | None:
    try:
        if sys.platform == "win32":  # pragma: no cover
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                   "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                   "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            pmc = PMC(); pmc.cb = ctypes.sizeof(pmc)
            ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            return pmc.WorkingSetSize / 1e6
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except Exception:
        return None
    return None


@dataclass
class Stats:
    samples_received: int = 0
    samples_lost: int = 0
    gap_events: int = 0
    polls: int = 0
    torn_or_invalid: int = 0
    reconnects: int = 0
    session_restarts: int = 0
    started_wall: float | None = None
    last_sample_wall: float | None = None
    errors: collections.deque = field(default_factory=lambda: collections.deque(maxlen=20))


class AcquisitionEngine:
    def __init__(self, opener: Callable[[], Backend], *, catalog: Catalog | None = None,
                 data_root: Path | None = None, record: bool = True, stall_s: float = 2.0,
                 open_retry_s: float = 1.0, process_check_s: float = 2.0,
                 process_probe: Callable[[], bool | None] = is_lmu_process_running,
                 clock: Callable[[], float] = time.monotonic):
        self.opener, self.catalog, self.record = opener, catalog, record and catalog is not None
        self.data_root = Path(data_root) if data_root else None
        self.stall_s, self.open_retry_s, self.process_check_s = stall_s, open_retry_s, process_check_s
        self.process_probe, self.clock = process_probe, clock
        self.state = ConnState.NOT_DETECTED
        self.stats = Stats()
        self.reader: SharedMemoryReader | None = None
        self.mapping_size: int | None = None
        self.mapping_error: str | None = None
        self.latest: Sample | None = None
        self.ctx: SessionContext | None = None
        self.synthetic = False
        self.recorder: SessionRecorder | None = None
        self.session_id: str | None = None
        self._rate: collections.deque[float] = collections.deque(maxlen=400)
        self._last_et: float | None = None
        self._last_open_try = -1e9
        self._last_proc_check = -1e9
        self._proc: bool | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._was_acquiring = False

    # ----------------------------------------------------------------- lifecycle
    def start(self, poll_hz: float = 250.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.stats.started_wall = self.stats.started_wall or time.time()

        def loop():
            period = 1.0 / poll_hz
            while not self._stop.is_set():
                t0 = time.perf_counter()
                self.poll_once()
                dt = time.perf_counter() - t0
                self._stop.wait(max(0.0, period - dt))
        self._thread = threading.Thread(target=loop, name="acquisition", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        self._end_session(complete=False)
        if self.reader:
            self.reader.close()
            self.reader = None

    # ----------------------------------------------------------------- core
    def _err(self, msg: str) -> None:
        self.stats.errors.append({"t": time.time(), "msg": msg})

    def _try_open(self, now: float) -> bool:
        if now - self._last_open_try < self.open_retry_s:
            return False
        self._last_open_try = now
        if now - self._last_proc_check >= self.process_check_s:
            self._proc = self.process_probe()
            self._last_proc_check = now
        try:
            be = self.opener()
        except MappingNotFound as e:
            self.mapping_error = str(e)
            self.mapping_size = None
            self.state = ConnState.GAME_RUNNING if self._proc else ConnState.NOT_DETECTED
            return False
        except Exception as e:
            self.mapping_error = f"{type(e).__name__}: {e}"
            self._err(self.mapping_error)
            self.state = ConnState.ERROR
            return False
        self.reader = SharedMemoryReader(be)
        self.mapping_size, self.mapping_error = be.size, None
        self.synthetic = bool(getattr(be, "synthetic", False))
        if self.stats.polls and self.stats.samples_received:
            self.stats.reconnects += 1
        if not self.reader.size_ok:
            self.mapping_error = f"mapping smaller than expected layout ({be.size} < {L.MAPPING_SIZE})"
            self._err(self.mapping_error)
            self.reader.close(); self.reader = None
            self.state = ConnState.ERROR
            return False
        self.state = ConnState.SHM_CONNECTED
        return True

    def poll_once(self) -> bool:
        """One polling iteration. Returns True if a new telemetry sample was accepted."""
        now = self.clock()
        self.stats.polls += 1
        if self.reader is None and not self._try_open(now):
            self._maybe_end(now)
            return False
        assert self.reader is not None
        try:
            snap = self.reader.read_snapshot()
        except Exception as e:  # mapping vanished (game closed) or unreadable -> reconnect path
            self._err(f"read failed: {type(e).__name__}: {e}")
            self.reader.close(); self.reader = None
            self._end_session(complete=False)
            self._last_et = None          # an outage is a connection event, not lost samples
            self.state = ConnState.NOT_DETECTED
            self._last_open_try = -1e9
            return False
        return self._ingest(snap, now)

    def _ingest(self, snap: Snapshot, now: float) -> bool:
        info, telem = snap.info, snap.telem
        if not snap.player_has_vehicle or telem is None:
            if self._was_acquiring and info.mGamePhase == 8:
                self.state = ConnState.SESSION_ENDED
                self._end_session(complete=True)
            elif self.state != ConnState.SESSION_ENDED:
                self.state = ConnState.WAITING_SESSION
            return False
        et = float(telem.mElapsedTime)
        if not (et == et) or et < 0:
            self.stats.torn_or_invalid += 1
            return False
        ctx = decode_context(snap.generic, info, snap.veh, telem)
        is_synth = self.synthetic or ctx.track_name.startswith(SYNTH_PREFIX.strip())
        # new telemetry frame?
        if self._last_et is not None and et == self._last_et:
            if now - (self.stats.last_sample_wall or now) > self.stall_s and self.state == ConnState.ACQUIRING:
                self.state = ConnState.SESSION_ENDED if info.mGamePhase == 8 else ConnState.SHM_CONNECTED
                if info.mGamePhase == 8:
                    self._end_session(complete=True)
            return False
        # session identity change / game session restart (elapsed time went backwards)
        restarted = self._last_et is not None and et < self._last_et - 1.0
        need_recorder = self.record and self.recorder is None   # e.g. after a reconnection
        if self.ctx is None or ctx.key() != self.ctx.key() or restarted or need_recorder:
            if restarted:
                self.stats.session_restarts += 1
            self._end_session(complete=True)
            self._begin_session(ctx, is_synth)
            self._last_et = None
        self.ctx = ctx
        # loss accounting from the game's own delta time (heuristic, see docs/TELEMETRY-FORMAT.md)
        if self._last_et is not None:
            gap, dt = et - self._last_et, float(telem.mDeltaTime)
            if dt > 0 and gap > 1.5 * dt:
                lost = int(round(gap / dt)) - 1
                if lost > 0:
                    self.stats.samples_lost += lost
                    self.stats.gap_events += 1
        self._last_et = et
        sample = decode_sample(info, snap.veh, telem, Provenance.SYNTHETIC if is_synth else Provenance.LMU_SHM)
        with self._lock:
            self.latest = sample
        self.stats.samples_received += 1
        self.stats.last_sample_wall = now
        self._rate.append(now)
        if self.recorder:
            self.recorder.add(sample)
        self.state = ConnState.ACQUIRING
        self._was_acquiring = True
        return True

    def _maybe_end(self, now: float) -> None:
        if self.recorder and self.state in (ConnState.NOT_DETECTED, ConnState.GAME_RUNNING):
            self._end_session(complete=False)

    # ----------------------------------------------------------------- sessions
    def _begin_session(self, ctx: SessionContext, synthetic: bool) -> None:
        self.stats.started_wall = self.stats.started_wall or time.time()
        if not self.record or self.data_root is None:
            return
        folder = self.data_root / ("synthetic" if synthetic else "sessions")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{time.strftime('%Y%m%dT%H%M%S')}_{int(time.time() * 1000) % 100000}.duckdb"
        sid = self.catalog.create_session(source="synthetic" if synthetic else "lmu_shm", is_synthetic=synthetic,
                                          data_path=str(path), ctx=ctx)  # type: ignore[union-attr]
        self.session_id = sid
        self._session_base = (self.stats.samples_received, self.stats.samples_lost)
        self.recorder = SessionRecorder(path, sid)

    def _end_session(self, complete: bool) -> None:
        if self.recorder is None:
            return
        rec, sid = self.recorder, self.session_id
        self.recorder = None
        rec.close()
        base_r, base_l = getattr(self, "_session_base", (0, 0))
        self.catalog.finish_session(sid, self.stats.samples_received - base_r,  # type: ignore[union-attr,arg-type]
                                    self.stats.samples_lost - base_l, complete)
        if rec.error:
            self._err("recorder: " + rec.error)

    # ----------------------------------------------------------------- reporting
    def effective_hz(self) -> float:
        r = self._rate
        if len(r) < 2:
            return 0.0
        span = r[-1] - r[0]
        return (len(r) - 1) / span if span > 0 else 0.0

    def diagnostics(self) -> dict:
        s = self.stats
        return {
            "state": self.state.value, "synthetic": self.synthetic,
            "mapping": {"size": self.mapping_size, "expected_size": L.MAPPING_SIZE, "error": self.mapping_error},
            "samples_received": s.samples_received, "samples_lost": s.samples_lost, "gap_events": s.gap_events,
            "effective_hz": round(self.effective_hz(), 2),
            "duration_s": round(time.time() - s.started_wall, 1) if s.started_wall else 0.0,
            "rss_mb": rss_mb(), "reconnects": s.reconnects, "session_restarts": s.session_restarts,
            "recording": self.recorder is not None, "session_id": self.session_id,
            "recorder_written": self.recorder.written if self.recorder else None,
            "errors": list(s.errors),
        }
