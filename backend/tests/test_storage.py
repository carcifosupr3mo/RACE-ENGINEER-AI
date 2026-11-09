import os
import signal
import subprocess
import sys
import textwrap
import time

import duckdb

from race_engineer.model.sample import SessionContext
from race_engineer.storage.catalog import Catalog, MIGRATIONS
from race_engineer.storage.recorder import SessionRecorder
from race_engineer.synthetic.game import SyntheticGame
from race_engineer.lmu.reader import SharedMemoryReader
from race_engineer.lmu.decode import decode_sample
from race_engineer.model.provenance import Provenance


def samples(n):
    g = SyntheticGame("constant", laps=1)
    r = SharedMemoryReader(g.backend)
    out = []
    for _ in range(n):
        g.step(); s = r.read_snapshot()
        out.append(decode_sample(s.info, s.veh, s.telem, Provenance.SYNTHETIC))
    return out


def test_migrations_are_idempotent_and_versioned(tmp_path):
    p = tmp_path / "c.sqlite"
    c = Catalog(p); v = c.schema_version(); c.close()
    c = Catalog(p)
    assert v == c.schema_version() == MIGRATIONS[-1][0]
    assert c.integrity_ok()


def test_crashed_recording_is_recovered_as_incomplete_never_deleted(tmp_path):
    p = tmp_path / "c.sqlite"
    c = Catalog(p)
    sid = c.create_session(source="lmu_shm", is_synthetic=False, data_path="x.duckdb", ctx=SessionContext(track_name="T"))
    c.close()                                  # simulates a crash: still 'recording'
    c = Catalog(p)
    rows = c.list_sessions()
    assert rows[0]["id"] == sid and rows[0]["status"] == "incomplete"


def test_backup_is_a_valid_database(tmp_path, catalog):
    catalog.create_session(source="lmu_shm", is_synthetic=False, data_path="x", ctx=SessionContext())
    b = catalog.backup(tmp_path / "backup.sqlite")
    c2 = Catalog(b)
    assert len(c2.list_sessions()) == 1 and c2.integrity_ok()


def test_recorder_roundtrip_values_and_nulls(tmp_path):
    ss = samples(50)
    ss[3].values["sector"] = None
    rec = SessionRecorder(tmp_path / "s.duckdb", "sid", flush_s=0.1, checkpoint_s=0.2)
    for s in ss:
        rec.add(s)
    rec.close()
    assert rec.error is None and rec.written == 50 and rec.checkpoints >= 1
    con = duckdb.connect(str(tmp_path / "s.duckdb"), read_only=True)
    assert con.execute("select count(*) from samples").fetchone()[0] == 50
    assert con.execute("select count(*) from samples where sector is null").fetchone()[0] == 1
    got = con.execute("select speed_kmh, tyre_fl_pressure_kpa from samples order by wall_time limit 1").fetchone()
    assert got[0] == ss[0]["speed_kmh"] and got[1] == ss[0]["tyre_fl_pressure_kpa"]


def test_data_survives_unexpected_process_kill(tmp_path):
    """Checkpointed data must be readable after SIGKILL (no graceful close)."""
    db = tmp_path / "k.duckdb"
    script = textwrap.dedent(f"""
        import os, signal, time, sys
        sys.path.insert(0, {os.getcwd()!r})
        from tests.test_storage import samples
        from race_engineer.storage.recorder import SessionRecorder
        rec = SessionRecorder({str(db)!r}, "sid", flush_s=0.1, checkpoint_s=0.2)
        for s in samples(400): rec.add(s)
        time.sleep(1.5)
        os.kill(os.getpid(), signal.SIGKILL)
    """)
    p = subprocess.run([sys.executable, "-c", script], cwd=os.getcwd(), timeout=60)
    assert p.returncode == -signal.SIGKILL
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("select count(*) from samples").fetchone()[0] == 400


def test_recorder_add_never_blocks_when_queue_full(tmp_path):
    rec = SessionRecorder(tmp_path / "f.duckdb", "sid", max_queue=5, flush_s=5)
    ss = samples(1)[0]
    t0 = time.perf_counter()
    for _ in range(200):
        rec.add(ss)
    assert time.perf_counter() - t0 < 0.5 and rec.dropped_overflow > 0
    rec.close()
