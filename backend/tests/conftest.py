import pytest
from pathlib import Path

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.storage.catalog import Catalog
from race_engineer.synthetic.game import SyntheticGame


@pytest.fixture
def catalog(tmp_path):
    c = Catalog(tmp_path / "catalog.sqlite")
    yield c
    c.close()


def make_engine(game, tmp_path, catalog, record=True, **kw):
    return AcquisitionEngine(lambda: game.backend, catalog=catalog, data_root=tmp_path, record=record,
                             process_probe=lambda: True, open_retry_s=0.0, **kw)


def run_game(game, engine, max_steps=10**7):
    n = 0
    while game.step() and n < max_steps:
        engine.poll_once()
        n += 1
    return n
