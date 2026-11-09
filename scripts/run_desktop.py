"""PyInstaller / launcher entry point for the desktop app."""
from race_engineer.desktop.main import run

if __name__ == "__main__":
    raise SystemExit(run())
