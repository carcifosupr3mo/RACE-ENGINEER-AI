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

# Version resource (Windows only): what Explorer shows under Properties > Details, and what a signature dialog names.
import sys
sys.path.insert(0, str(root / "backend"))
from race_engineer import __version__

def version_info(description, filename):
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo
    nums = tuple(int(x) for x in (__version__.split(".") + ["0"] * 4)[:4])
    strings = [("CompanyName", "Race Engineer AI"), ("FileDescription", description), ("FileVersion", __version__), ("InternalName", filename),
               ("OriginalFilename", filename), ("ProductName", "Race Engineer AI"), ("ProductVersion", __version__)]
    return VSVersionInfo(ffi=FixedFileInfo(filevers=nums, prodvers=nums),
                         kids=[StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])])

def analysis(entry, extra_hidden=()):
    return Analysis([str(root / "scripts" / entry)], pathex=[str(root / "backend")], datas=datas,
                    hiddenimports=hidden + list(extra_hidden), excludes=excludes)

a_cli = analysis("run_cli.py")
pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="race-engineer-cli", console=True, icon=str(root / "packaging" / "icon.ico"),
              version=version_info("Race Engineer AI - strumenti da riga di comando", "race-engineer-cli.exe"))
parts = [exe_cli, a_cli.binaries, a_cli.datas]
if have_qt:
    a_gui = analysis("run_desktop.py", collect_submodules("PySide6.QtWebEngineWidgets"))
    pyz_gui = PYZ(a_gui.pure)
    exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="RaceEngineerAI", console=False, icon=str(root / "packaging" / "icon.ico"),
                  version=version_info("Race Engineer AI", "RaceEngineerAI.exe"))
    parts += [exe_gui, a_gui.binaries, a_gui.datas]
coll = COLLECT(*parts, name="RaceEngineerAI")

# The updater is a SEPARATE, tiny, stdlib-only single-file program: the app copies it to a temp folder and runs it while the app is
# closed, because a running program cannot overwrite its own files on Windows. scripts/build.py copies it next to RaceEngineerAI.exe.
a_upd = Analysis([str(root / "scripts" / "run_updater.py")], pathex=[str(root / "backend")], hiddenimports=["race_engineer.updater.apply"],
                 excludes=excludes + ["numpy", "scipy", "duckdb", "fastapi", "uvicorn", "PySide6", "httpx", "keyring"])
pyz_upd = PYZ(a_upd.pure)
exe_upd = EXE(pyz_upd, a_upd.scripts, a_upd.binaries, a_upd.datas, [], name="RaceEngineerUpdater", console=False,
              icon=str(root / "packaging" / "icon.ico"), version=version_info("Race Engineer AI - programma di aggiornamento", "RaceEngineerUpdater.exe"))
