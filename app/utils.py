"""Utility functions and command generator."""
from __future__ import annotations

import math
import os
import re
import sys
from typing import Optional


def resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource (works for PyInstaller and dev)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, relative)

from app.constants import (
    DRAIN_ACTION_TEXT,
    DLP_TIME_MARKER,
    INCUBATION_ACTION_TEXT,
    PATTERN_ACTION_TEXT,
    PHOSPHORAMIDITE_GROUP_ACTION_TEXT,
)
from app.models import StepItem


def format_reagent_action(slot_no: int, name: str) -> str:
    """Format a reagent action string with slot and display name."""
    return f"Reagent {slot_no:02d} - {name.strip()}"


def parse_reagent_slot(action: str) -> Optional[int]:
    """Extract reagent slot from action text."""
    match = re.search(r"reagent\s*0*(\d{1,2})", action or "", flags=re.IGNORECASE)
    if not match:
        return None
    slot = int(match.group(1))
    if 1 <= slot <= 12:
        return slot
    return None


def is_phosphoramidite_group_action(action: str) -> bool:
    """Return True for the grouped A/T/C/G phosphoramidite protocol action."""
    return (action or "").strip().lower() == PHOSPHORAMIDITE_GROUP_ACTION_TEXT.lower()


def is_pattern_action(action: str) -> bool:
    return "pattern base" in (action or "").lower()


def is_drain_action(action: str) -> bool:
    return "drain" in (action or "").lower()


def is_incubation_action(action: str) -> bool:
    return "incubation" in (action or "").lower()


class CommandGenerator:
    """Convert protocol steps into simulated Arduino command strings."""

    _TIME_RE = re.compile(r"^\s*(\d+)\s*(ms|s|m)?\s*$", flags=re.IGNORECASE)

    @staticmethod
    def parse_time_to_seconds(value: str, dlp_exposure_ms: int = 0) -> Optional[int]:
        """
        Parse protocol time text into integer seconds.

        Returns None for infinity (hold state) or invalid values.
        """
        text = (value or "").strip()
        if not text:
            return None

        lowered = text.lower()
        if lowered in {"∞", "inf", "infinite"}:
            return None
        if lowered == DLP_TIME_MARKER.lower():
            return max(1, math.ceil(max(0, dlp_exposure_ms) / 1000.0))

        match = CommandGenerator._TIME_RE.match(lowered)
        if not match:
            return None

        amount = int(match.group(1))
        unit = (match.group(2) or "s").lower()

        if unit == "ms":
            return max(1, math.ceil(amount / 1000.0))
        if unit == "m":
            return amount * 60
        return amount

    @staticmethod
    def parse_time_to_milliseconds(value: str, dlp_exposure_ms: int = 0) -> Optional[int]:
        """Parse protocol time text into milliseconds."""
        text = (value or "").strip()
        if not text:
            return None

        lowered = text.lower()
        if lowered in {"∞", "inf", "infinite"}:
            return None
        if lowered == DLP_TIME_MARKER.lower():
            return max(0, dlp_exposure_ms)

        match = CommandGenerator._TIME_RE.match(lowered)
        if not match:
            return None

        amount = int(match.group(1))
        unit = (match.group(2) or "s").lower()

        if unit == "ms":
            return amount
        if unit == "m":
            return amount * 60 * 1000
        return amount * 1000

    @staticmethod
    def generate(
        step: StepItem,
        dlp_exposure_ms: int,
        phosphoramidite_slot_no: Optional[int] = None,
    ) -> str:
        """Generate an Arduino-style command string for a step."""
        action = step.action or ""

        if is_pattern_action(action):
            return "DLP_EXPOSURE"

        seconds = CommandGenerator.parse_time_to_seconds(step.time_sec, dlp_exposure_ms)
        if seconds is None:
            if is_incubation_action(action):
                return "wINF"
            seconds = 0

        if is_phosphoramidite_group_action(action):
            slot_no = phosphoramidite_slot_no if phosphoramidite_slot_no in {1, 2, 3, 4} else 1
            return f"Rv{slot_no};w1;P1on;w{seconds};P1off;"

        slot_no = parse_reagent_slot(action)
        if slot_no is not None:
            return f"Rv{slot_no};w1;P1on;w{seconds};P1off;"

        if is_drain_action(action):
            return f"P2on;w{seconds};P2off;"

        if is_incubation_action(action):
            return f"w{seconds}"

        return f"UNKNOWN({action});w{seconds};"
