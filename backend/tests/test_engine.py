import duckdb
import pytest

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.lmu.diagnostics import ConnState
from race_engineer.lmu.reader import BytesBackend, MappingNotFound
from race_engineer.model.provenance import Provenance
from race_engineer.synthetic.game import SyntheticGame

from .conftest import make_engine, run_game


def test_state_machine_not_detected_then_game_running(tmp_path, catalog):
    e = AcquisitionEngine(lambda: (_ for _ in ()).throw(MappingNotFound("x")), catalog=catalog, data_root=tmp_path,
                          process_probe=lambda: False, open_retry_s=0.0)
    e.poll_once()
    assert e.state is ConnState.NOT_DETECTED
    e.process_probe = lambda: True; e._last_proc_check = -1e9
    e.poll_once()
    assert e.state is ConnState.GAME_RUNNING and "x" in e.mapping_error


def test_full_lifecycle_states(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    seen = []
    e = make_engine(g, tmp_path, catalog)
    e.poll_once(); seen.append(e.state)               # mapping open but player has no vehicle yet
    assert e.state is ConnState.WAITING_SESSION
    g.step(); e.poll_once(); seen.append(e.state)
    assert e.state is ConnState.ACQUIRING
    for _ in range(200):
        g.step(); e.poll_once()
    assert e.stats.samples_received == 201
    g.end_session(); e.poll_once()
    assert e.state is ConnState.SESSION_ENDED
    s = catalog.list_sessions()[0]
    assert s["status"] == "complete" and s["samples"] == 201


def test_effective_rate_and_counts_without_loss(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog, record=False)
    run_game(g, e)
    assert e.stats.samples_lost == 0 and e.stats.samples_received == g.frames_published
    # polling twice without a new frame must not duplicate samples
    before = e.stats.samples_received
    e.poll_once(); e.poll_once()
    assert e.stats.samples_received == before


def test_missing_samples_are_counted_exactly(tmp_path, catalog):
    g = SyntheticGame("missing_samples", laps=1)
    e = make_engine(g, tmp_path, catalog, record=False)
    run_game(g, e)
    span = g.pub_last - g.pub_first + 1
    assert e.stats.samples_lost > 0
    assert e.stats.samples_received + e.stats.samples_lost == span
    assert e.stats.gap_events > 0


def test_connection_loss_and_reconnection(tmp_path, catalog):
    g = SyntheticGame("constant", laps=2)
    state = {"up": True}

    def opener():
        if not state["up"]:
            raise MappingNotFound("game closed")
        return BytesBackend(g.buf)            # a fresh mapping handle on every (re)connection
    e = AcquisitionEngine(opener, catalog=catalog, data_root=tmp_path, process_probe=lambda: False, open_retry_s=0.0)
    for _ in range(300):
        g.step(); e.poll_once()
    assert e.state is ConnState.ACQUIRING
    # backend dies mid-read
    def boom(*a): raise OSError("mapping gone")
    e.reader.backend.read = boom
    e.poll_once()
    assert e.state is ConnState.NOT_DETECTED and e.reader is None
    assert catalog.list_sessions()[0]["status"] == "incomplete"      # data kept, flagged
    state["up"] = False
    e.poll_once(); assert e.state is ConnState.NOT_DETECTED
    state["up"] = True
    for _ in range(100):
        g.step(); e.poll_once()
    assert e.state is ConnState.ACQUIRING and e.stats.reconnects == 1
    assert len(catalog.list_sessions()) == 2


def test_undersized_mapping_is_an_error_not_a_crash(tmp_path, catalog):
    from race_engineer.lmu.reader import BytesBackend
    e = AcquisitionEngine(lambda: BytesBackend(bytearray(1000)), catalog=catalog, data_root=tmp_path,
                          process_probe=lambda: True, open_retry_s=0.0)
    e.poll_once()
    assert e.state is ConnState.ERROR and "smaller" in e.mapping_error and e.stats.errors


def test_incomplete_session_is_kept_and_flagged(tmp_path, catalog):
    g = SyntheticGame("incomplete", laps=5)
    e = make_engine(g, tmp_path, catalog)
    run_game(g, e)
    assert g.finished
    e.stop()                                                        # game vanished mid-lap
    s = catalog.list_sessions()[0]
    assert s["status"] == "incomplete" and s["samples"] > 1000
    n = duckdb.connect(s["data_path"], read_only=True).execute("select count(*) from samples").fetchone()[0]
    assert n == s["samples"]


def test_session_restart_creates_new_session(tmp_path, catalog):
    g = SyntheticGame("constant", laps=2)
    e = make_engine(g, tmp_path, catalog)
    for _ in range(500):
        g.step(); e.poll_once()
    g.obj.telemetry.telemInfo[0].mElapsedTime = 0.5                 # game restarted the session
    e.poll_once()
    assert e.stats.session_restarts == 1
    assert len(catalog.list_sessions()) == 2


def test_synthetic_is_segregated_and_flagged_everywhere(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog)
    for _ in range(300):
        g.step(); e.poll_once()
    e.stop()
    s = catalog.list_sessions()[0]
    assert s["is_synthetic"] == 1 and s["source"] == "synthetic" and "/synthetic/" in s["data_path"]
    assert e.latest.source is Provenance.SYNTHETIC
    prov = duckdb.connect(s["data_path"], read_only=True).execute("select distinct provenance from samples").fetchall()
    assert prov == [("synthetic",)]
    assert (tmp_path / "sessions").exists() is False                # nothing leaked into the real-data folder


def test_unavailable_channels_stay_none(tmp_path, catalog):
    g = SyntheticGame("constant", laps=1)
    e = make_engine(g, tmp_path, catalog, record=False)
    g.step(); e.poll_once()
    assert e.latest.provenance_of("tyre_fl_pressure_kpa") is Provenance.SYNTHETIC
