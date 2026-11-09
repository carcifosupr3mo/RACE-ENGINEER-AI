"""PyInstaller entry point for the console executable (diagnose / serve / record ...)."""
from race_engineer.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
