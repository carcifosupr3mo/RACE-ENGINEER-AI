# PyInstaller spec. Run from the repo root:  pyinstaller packaging/race_engineer.spec --noconfirm
# Builds `race-engineer-cli` (console) and, when PySide6 is installed, `RaceEngineerAI` (windowed desktop app).
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

root = Path(SPECPATH).parent
pkg = root / "backend" / "race_engineer"
datas = [(str(pkg / "api" / "static"), "race_engineer/api/static")]
if (pkg / "api" / "webdist").is_dir():
    datas.append((str(pkg / "api" / "webdist"), "race_engineer/api/webdist"))
hidden = collect_submodules("uvicorn") + collect_submodules("race_engineer") + ["duckdb", "scipy.signal", "scipy.special._cdflib", "keyring.backends.Windows", "keyring.backends.fail"]
excludes = ["tkinter", "matplotlib", "pytest"]
have_qt = importlib.util.find_spec("PySide6") is not None

def analysis(entry, extra_hidden=()):
    return Analysis([str(root / "scripts" / entry)], pathex=[str(root / "backend")], datas=datas,
                    hiddenimports=hidden + list(extra_hidden), excludes=excludes)

a_cli = analysis("run_cli.py")
pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="race-engineer-cli", console=True, icon=str(root / "packaging" / "icon.ico"))
parts = [exe_cli, a_cli.binaries, a_cli.datas]
if have_qt:
    a_gui = analysis("run_desktop.py", collect_submodules("PySide6.QtWebEngineWidgets"))
    pyz_gui = PYZ(a_gui.pure)
    exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="RaceEngineerAI", console=False, icon=str(root / "packaging" / "icon.ico"))
    parts += [exe_gui, a_gui.binaries, a_gui.datas]
coll = COLLECT(*parts, name="RaceEngineerAI")
