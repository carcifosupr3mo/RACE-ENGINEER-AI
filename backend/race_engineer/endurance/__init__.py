"""24h-ready endurance layer: local detection + race memory + stale-safe optional AI."""
from .detector import Event, EventDetector, Thresholds
from .memory import RaceMemory
from .pipeline import EndurancePipeline, local_text, ungrounded_numbers

__all__ = ["Event", "EventDetector", "Thresholds", "RaceMemory", "EndurancePipeline", "local_text", "ungrounded_numbers"]
