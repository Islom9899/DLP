"""Global scale, px() helper, and all named constants."""
from __future__ import annotations

_SCALE: float = 1.0


def px(value: float) -> int:
    """Scale pixels from a 1920x1080 design baseline."""
    return max(1, int(round(value * _SCALE)))


BASES = ["A", "T", "C", "G"]
TOTAL_SEQUENCES = 20
EXPOSURE_MIN = 0
EXPOSURE_MAX = 10000
LED_MIN = 0
LED_MAX = 100

DLP_TIME_MARKER = "DLP"
INFINITE_TIME_MARKER = "∞"
PHOSPHORAMIDITE_GROUP_ACTION_TEXT = "Phosphoramidite(A,T,C,G)"
PATTERN_ACTION_TEXT = "Pattern base (A,T,C,G)"
INCUBATION_ACTION_TEXT = "Incubation"
DRAIN_ACTION_TEXT = "drain"
