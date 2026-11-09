"""Data provenance: every value must say where it comes from."""
from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    LMU_SHM = "lmu_shm"            # read directly from LMU shared memory (unit conversions only)
    DUCKDB_IMPORT = "duckdb_import"  # imported from an LMU-written DuckDB telemetry file
    COMPUTED = "computed"          # derived by this software from other values
    MANUAL = "manual"              # configured by the user
    UNAVAILABLE = "unavailable"    # not provided (channel absent / not verified)
    SYNTHETIC = "synthetic"        # generated test data - NEVER evidence of LMU integration
