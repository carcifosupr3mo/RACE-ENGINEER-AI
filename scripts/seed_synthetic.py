"""Record finished SYNTHETIC sessions into the data dir (UI demos / e2e).

Usage: RACE_ENGINEER_DATA=<dir> python scripts/seed_synthetic.py constant early_brake
"""
import sys

from race_engineer.acquisition.engine import AcquisitionEngine
from race_engineer.storage.catalog import Catalog
from race_engineer.storage.paths import data_dir
from race_engineer.synthetic.game import SyntheticGame

root = data_dir()
cat = Catalog(root / "catalog.sqlite")
for sc in sys.argv[1:] or ["constant"]:
    g = SyntheticGame(sc, laps=4)
    e = AcquisitionEngine(lambda: g.backend, catalog=cat, data_root=root, process_probe=lambda: True, open_retry_s=0)
    while g.step():
        e.poll_once()
    e.stop()
print(len(cat.list_sessions()), "sessions in", root)
