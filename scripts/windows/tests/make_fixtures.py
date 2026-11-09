"""Builds SYNTHETIC fixtures for Test-Procedura.ps1: <root>/Le Mans Ultimate/{UserData/Telemetry/x.duckdb, UserData/player/Settings/t.svm} and a fake LMU_Data file."""
import sys
from pathlib import Path

from race_engineer.synthetic.game import SyntheticGame
from race_engineer.synthetic.lmu_duckdb_fixture import build

root = Path(sys.argv[1])
game = root / "Le Mans Ultimate"
(game / "UserData" / "Telemetry").mkdir(parents=True, exist_ok=True)
(game / "UserData" / "player" / "Settings").mkdir(parents=True, exist_ok=True)
build(game / "UserData" / "Telemetry" / "synthetic_session.duckdb", "constant", laps=1)
(game / "UserData" / "player" / "Settings" / "synthetic.svm").write_text("[GENERAL]\nNotes=synthetic\n[FRONTWING]\nFWSetting=3//N/A\n", encoding="utf-8")
g = SyntheticGame("constant", laps=2)
for _ in range(300):
    g.step()
(root / "fake_lmu_data.bin").write_bytes(bytes(g.buf))
print("fixtures ok")
