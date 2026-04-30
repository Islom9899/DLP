"""Dataclass models for the Gene Synthesizer application."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StepItem:
    """Single protocol step."""

    step_no: int
    action: str
    time_sec: str
    command: str = ""  # empty = auto-generate; non-empty = user override


def _default_pattern_base_times() -> Dict[str, int]:
    return {"A": 3500, "T": 3500, "C": 3500, "G": 3500}


@dataclass
class RecipeData:
    """Recipe data with three synthesis stages."""

    name: str
    memo: str = ""
    sequence_count: int = 20
    pre_processing: List[StepItem] = field(default_factory=list)
    cyclic_reaction: List[StepItem] = field(default_factory=list)
    post_processing: List[StepItem] = field(default_factory=list)
    pattern_base_times: Dict[str, int] = field(default_factory=_default_pattern_base_times)


@dataclass
class ReagentSlot:
    """Reagent slot metadata."""

    slot_no: int
    name: str
    color: str
    volume: Optional[str] = None
