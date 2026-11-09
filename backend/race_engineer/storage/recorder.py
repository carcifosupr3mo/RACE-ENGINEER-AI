"""Buffered telemetry writer: memory buffer -> background thread -> DuckDB, with periodic checkpoints."""
from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
from pathlib import Path

import duckdb

from ..model.channels import CHANNELS
from ..model.provenance import Provenance
from ..model.sample import Sample

_COLS = ["session_id", "wall_time", "provenance"] + [c.name for c in CHANNELS]
_DDL = ("CREATE TABLE IF NOT EXISTS samples (session_id VARCHAR, wall_time DOUBLE, provenance VARCHAR, "
        + ", ".join(f'"{c.name}" {c.dtype}' for c in CHANNELS) + ")")
_JSON_COLS = "{" + ", ".join(
    [f"'{n}': '{t}'" for n, t in [("session_id", "VARCHAR"), ("wall_time", "DOUBLE"), ("provenance", "VARCHAR")]]
    + [f"'{c.name}': '{c.dtype}'" for c in CHANNELS]) + "}"


class SessionRecorder:
    """One DuckDB file per session. ``add()`` is O(1) and never blocks the acquisition thread."""

    def __init__(self, path: Path | str, session_id: str, flush_s: float = 1.0, checkpoint_s: float = 5.0,
                 max_queue: int = 200_000):
        self.path = Path(path)
        self.session_id = session_id
        self.flush_s, self.checkpoint_s = flush_s, checkpoint_s
        self._q: queue.Queue[Sample | None] = queue.Queue(max_queue)
        self.written = 0
        self.dropped_overflow = 0
        self.error: str | None = None
        self.checkpoints = 0
        self._t = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._t.start()

    def add(self, s: Sample) -> None:
        try:
            self._q.put_nowait(s)
        except queue.Full:
            self.dropped_overflow += 1

    @staticmethod
    def _row(sid: str, s: Sample) -> dict:
        d = {"session_id": sid, "wall_time": s.wall_time, "provenance": s.source.value}
        d.update(s.values)
        return d

    def _flush(self, con, batch: list[dict]) -> None:
        """Bulk insert through NDJSON + read_json: ~40x faster than executemany in DuckDB."""
        fd, tmp = tempfile.mkstemp(suffix=".ndjson", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(json.dumps(r) for r in batch) + "\n")
            con.execute(f"INSERT INTO samples SELECT * FROM read_json('{tmp}', format='newline_delimited', "
                        f"columns={_JSON_COLS})")
        finally:
            os.unlink(tmp)

    def _run(self) -> None:
        try:
            con = duckdb.connect(str(self.path))
            con.execute(_DDL)
            batch: list[dict] = []
            last_flush = last_ck = time.monotonic()
            stop = False
            while not stop:
                try:
                    item = self._q.get(timeout=self.flush_s / 2)
                    if item is None:
                        stop = True
                    else:
                        batch.append(self._row(self.session_id, item))
                except queue.Empty:
                    pass
                now = time.monotonic()
                if batch and (stop or now - last_flush >= self.flush_s or len(batch) >= 2000):
                    self._flush(con, batch)
                    self.written += len(batch)
                    batch.clear()
                    last_flush = now
                if now - last_ck >= self.checkpoint_s or stop:
                    con.execute("CHECKPOINT")
                    self.checkpoints += 1
                    last_ck = now
            con.close()
        except Exception as e:  # surfaced in diagnostics, never kills acquisition
            self.error = f"{type(e).__name__}: {e}"

    def close(self, timeout: float = 10.0) -> None:
        self._q.put(None)
        self._t.join(timeout)

    @staticmethod
    def synthetic_flag(s: Sample) -> bool:
        return s.source is Provenance.SYNTHETIC
