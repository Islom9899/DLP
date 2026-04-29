"""Recipe serialization, deserialization, and default factory functions."""
from __future__ import annotations

from typing import Dict, List, Tuple

from app.constants import (
    DRAIN_ACTION_TEXT,
    DLP_TIME_MARKER,
    INCUBATION_ACTION_TEXT,
    INFINITE_TIME_MARKER,
    PATTERN_ACTION_TEXT,
    PHOSPHORAMIDITE_GROUP_ACTION_TEXT,
    TOTAL_SEQUENCES,
)
from app.models import RecipeData, ReagentSlot, StepItem
from app.utils import format_reagent_action


def default_reagent_slots() -> Dict[int, ReagentSlot]:
    """Build default reagent slot configuration."""
    return {
        1: ReagentSlot(1, "Phosphoramidite (A)", "#2f77bc"),
        2: ReagentSlot(2, "Phosphoramidite (T)", "#c54f4f"),
        3: ReagentSlot(3, "Phosphoramidite (C)", "#3f9b67"),
        4: ReagentSlot(4, "Phosphoramidite (G)", "#7f56c1"),
        5: ReagentSlot(5, "Activator", "#1f7cbc"),
        6: ReagentSlot(6, "Oxidizer", "#7c57c4"),
        7: ReagentSlot(7, "Capping A", "#4a9f71"),
        8: ReagentSlot(8, "Capping B", "#7c57c4"),
        9: ReagentSlot(9, "Deblock", "#1a8a9b"),
        10: ReagentSlot(10, "Wash 1", "#667a92"),
        11: ReagentSlot(11, "Wash 2", "#667a92"),
        12: ReagentSlot(12, "Wash 3", "#667a92"),
    }


def default_recipe(slots: Dict[int, ReagentSlot]) -> RecipeData:
    """Build default recipe from current reagent names."""
    return RecipeData(
        name="Default Recipe",
        memo="",
        sequence_count=TOTAL_SEQUENCES,
        pre_processing=[
            StepItem(1, PHOSPHORAMIDITE_GROUP_ACTION_TEXT, "60s"),
            StepItem(2, INCUBATION_ACTION_TEXT, "900s"),
        ],
        cyclic_reaction=[
            StepItem(1, PHOSPHORAMIDITE_GROUP_ACTION_TEXT, "60s"),
            StepItem(2, format_reagent_action(5, slots[5].name), "60s"),
            StepItem(3, DRAIN_ACTION_TEXT, "30s"),
            StepItem(4, format_reagent_action(6, slots[6].name), "45s"),
            StepItem(5, PATTERN_ACTION_TEXT, DLP_TIME_MARKER),
            StepItem(6, DRAIN_ACTION_TEXT, "30s"),
            StepItem(7, format_reagent_action(9, slots[9].name), "45s"),
            StepItem(8, format_reagent_action(10, slots[10].name), "30s"),
        ],
        post_processing=[
            StepItem(1, PHOSPHORAMIDITE_GROUP_ACTION_TEXT, "60s"),
            StepItem(2, INCUBATION_ACTION_TEXT, INFINITE_TIME_MARKER),
        ],
    )


def recipe_to_dict(recipe: RecipeData, slots: Dict[int, ReagentSlot]) -> dict:
    """Serialize recipe and reagent slots to JSON-compatible dict."""
    return {
        "name": recipe.name,
        "memo": recipe.memo,
        "sequence_count": recipe.sequence_count,
        "reagents": [
            {
                "slot_no": slot.slot_no,
                "name": slot.name,
                "color": slot.color,
                "volume": slot.volume,
            }
            for _, slot in sorted(slots.items())
        ],
        "pre_processing": [
            {"step_no": s.step_no, "action": s.action, "time_sec": s.time_sec, "command": s.command}
            for s in recipe.pre_processing
        ],
        "cyclic_reaction": [
            {"step_no": s.step_no, "action": s.action, "time_sec": s.time_sec, "command": s.command}
            for s in recipe.cyclic_reaction
        ],
        "post_processing": [
            {"step_no": s.step_no, "action": s.action, "time_sec": s.time_sec, "command": s.command}
            for s in recipe.post_processing
        ],
        "pattern_base_times": recipe.pattern_base_times,
    }


def recipe_from_dict(payload: dict) -> Tuple[RecipeData, Dict[int, ReagentSlot]]:
    """Deserialize recipe and reagent slots from JSON payload."""
    slots = default_reagent_slots()
    for entry in payload.get("reagents", []):
        try:
            slot_no = int(entry.get("slot_no"))
        except (TypeError, ValueError):
            continue
        if 1 <= slot_no <= 12:
            slots[slot_no] = ReagentSlot(
                slot_no=slot_no,
                name=str(entry.get("name", slots[slot_no].name)),
                color=str(entry.get("color", slots[slot_no].color)),
                volume=entry.get("volume"),
            )

    def _read_steps(key: str) -> List[StepItem]:
        raw_steps = payload.get(key, [])
        steps: List[StepItem] = []
        for idx, entry in enumerate(raw_steps, start=1):
            action = str(entry.get("action", "")).strip()
            if not action:
                action = PHOSPHORAMIDITE_GROUP_ACTION_TEXT
            time_text = str(entry.get("time_sec", "60s")).strip() or "60s"
            steps.append(StepItem(idx, action, time_text, str(entry.get("command", ""))))
        return steps

    def _read_sequence_count(data: dict) -> int:
        try:
            count = int(data.get("sequence_count", TOTAL_SEQUENCES))
        except (TypeError, ValueError):
            return TOTAL_SEQUENCES
        return max(1, count)

    _default_times = {"A": 3500, "T": 3500, "C": 3500, "G": 3500}
    raw_times = payload.get("pattern_base_times") or {}
    pattern_base_times = {
        base: max(1, int(raw_times.get(base, _default_times[base])))
        for base in ["A", "T", "C", "G"]
    }

    recipe = RecipeData(
        name=str(payload.get("name", "Loaded Recipe")),
        memo=str(payload.get("memo", "")),
        sequence_count=_read_sequence_count(payload),
        pre_processing=_read_steps("pre_processing"),
        cyclic_reaction=_read_steps("cyclic_reaction"),
        post_processing=_read_steps("post_processing"),
        pattern_base_times=pattern_base_times,
    )
    return recipe, slots
