from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .channels import CHANNEL_BY_NAME, COMPUTED_FIELDS
from .provenance import Provenance


@dataclass(slots=True)
class SessionContext:
    """Slowly-changing identification of the running session (strings from LMU)."""
    track_name: str = ""
    vehicle_name: str = ""
    vehicle_class: str = ""
    driver_name: str = ""
    session_code: int = -1
    session_type: str = "unknown"
    game_version: int = 0
    track_length_m: float = 0.0
    max_laps: int = 0

    def key(self) -> tuple:
        return (self.track_name, self.vehicle_name, self.session_code)


@dataclass(slots=True)
class Sample:
    """One normalized telemetry sample. ``values`` maps channel name -> value or None (unavailable)."""
    wall_time: float
    source: Provenance
    values: dict[str, Any]
    unavailable: frozenset[str] = frozenset()

    def __getitem__(self, k: str) -> Any:
        return self.values.get(k)

    def provenance_of(self, channel: str) -> Provenance:
        if channel in self.unavailable or self.values.get(channel) is None:
            return Provenance.UNAVAILABLE
        if self.source is Provenance.SYNTHETIC:
            return Provenance.SYNTHETIC
        if channel in COMPUTED_FIELDS:
            return Provenance.COMPUTED
        return self.source

    def to_json(self) -> dict[str, Any]:
        return {"wall_time": self.wall_time, "source": self.source.value, "values": self.values,
                "provenance": {k: self.provenance_of(k).value for k in CHANNEL_BY_NAME}}


SESSION_TYPES = [(0, 0, "test"), (1, 4, "practice"), (5, 8, "qualifying"), (9, 9, "warmup"), (10, 13, "race")]


def session_type_name(code: int) -> str:
    for lo, hi, name in SESSION_TYPES:
        if lo <= code <= hi:
            return name
    return "unknown"
