"""Sahifa 2: Recipe setup dialog with reagent cards and protocol tables."""
from __future__ import annotations

import copy
import json
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    DRAIN_ACTION_TEXT,
    EXPOSURE_MAX,
    EXPOSURE_MIN,
    INCUBATION_ACTION_TEXT,
    PATTERN_ACTION_TEXT,
    PHOSPHORAMIDITE_GROUP_ACTION_TEXT,
    TOTAL_SEQUENCES,
    px,
)
from app.models import RecipeData, ReagentSlot, StepItem
from app.recipe_io import recipe_from_dict, recipe_to_dict
from app.utils import is_phosphoramidite_group_action, parse_reagent_slot
from app.widgets.primitives import Panel
from app.widgets.reagent_widgets import (
    PatternBaseCard,
    PhosphoramiditeGroupCard,
    ProtocolTable,
    ReagentCard,
    SpecialActionCard,
)

# ── Button styles for Recipe Management ───────────────────────────────────────
_BTN_BASE = (
    f"min-height:{px(36)}px; padding:0 {px(14)}px;"
    f"border-radius:{px(8)}px; font-size:{px(14)}px; font-weight:700;"
    f"background:#ffffff;"
)
_LOAD_BTN_STYLE = _BTN_BASE + "border:2px solid #d4900a; color:#a06808;"
_SAVE_BTN_STYLE = _BTN_BASE + "border:2px solid #2878c8; color:#1a5090;"
_NEW_BTN_STYLE  = _BTN_BASE + "border:2px solid #259025; color:#1a6018;"


class RecipeSetupDialog(QDialog):
    """Recipe setup dialog with reagent cards and protocol tables."""

    dlp_exposure_changed = Signal(int)

    def __init__(
        self,
        recipe: RecipeData,
        reagent_slots: Dict[int, ReagentSlot],
        dlp_exposure_ms: int = 3500,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Reagent & Synthesis Protocol Setup")
        self.setWindowState(Qt.WindowMaximized)

        self.recipe = copy.deepcopy(recipe)
        self.reagent_slots: Dict[int, ReagentSlot] = {
            slot_no: copy.deepcopy(slot) for slot_no, slot in reagent_slots.items()
        }
        self.dlp_exposure_ms = int(max(EXPOSURE_MIN, min(EXPOSURE_MAX, dlp_exposure_ms)))

        self.active_table: Optional[ProtocolTable] = None
        self._tables: List[ProtocolTable] = []
        self.phospho_group: Optional[PhosphoramiditeGroupCard] = None
        self.reagent_cards: Dict[int, ReagentCard] = {}
        self.special_cards: Dict[str, SpecialActionCard] = {}
        self.pattern_base_card: Optional[PatternBaseCard] = None
        self._copied_step: Optional[StepItem] = None
        self._recipe_dirty = False
        self._recipe_status_label: Optional[QLabel] = None
        self._recipe_dirty_badge: Optional[QLabel] = None
        self._recipe_name_edit: Optional[QLineEdit] = None
        self._syncing_recipe_metadata = False

        self._build_ui()
        self._sync_recipe_metadata_to_ui()
        self._sync_recipe_to_tables()
        for table in self._tables:
            table.set_pattern_base_times(self.recipe.pattern_base_times)
        self._set_action_cards_enabled(False)
        self._refresh_recipe_management_status()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{ background:#dce5ed; }}
            QLabel  {{ color:#101820; }}
            QPushButton {{
                min-height:{px(32)}px;
                border-radius:{px(6)}px;
                border:1px solid #b0c8d8;
                background:#eaf2f8;
                padding:0 {px(12)}px;
                font-size:{px(14)}px;
                font-weight:700;
                color:#1a3858;
            }}
            QPushButton:hover {{ background:#d8eaf6; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(px(20), px(16), px(20), px(14))
        root.setSpacing(px(12))

        # ── Window title ───────────────────────────────────────────────────────
        title = QLabel("Reagent & Synthesis Protocol Setup")
        title.setStyleSheet(
            f"font-size:{px(22)}px; font-weight:800; color:#1e2a34;"
        )
        root.addWidget(title)

        # ── Two-column body ────────────────────────────────────────────────────
        content = QHBoxLayout()
        content.setSpacing(px(14))
        root.addLayout(content, 1)

        # Left column (2/5)
        left_col = QVBoxLayout()
        left_col.setSpacing(px(12))
        content.addLayout(left_col, 2)
        self._build_reagent_panel(left_col)
        self._build_manage_panel(left_col)

        # Right column (3/5)
        right_panel = Panel("Synthesis Protocols")
        content.addWidget(right_panel, 3)

        self.pre_table = self._build_stage_table(
            right_panel.root, "Stage 1. Pre-processing", "pre"
        )
        self.cycle_table = self._build_stage_table(
            right_panel.root,
            "Stage 2. Cyclic reaction (depends on sequences and patterns)",
            "cycle",
        )
        self.post_table = self._build_stage_table(
            right_panel.root, "Stage 3. Post-processing", "post"
        )

        self._tables = [self.pre_table, self.cycle_table, self.post_table]
        self._apply_reagent_names_to_tables()

        # ── Footer ─────────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        apply_btn  = QPushButton("Apply && Close")
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._apply_and_accept)
        footer.addWidget(cancel_btn)
        footer.addWidget(apply_btn)
        root.addLayout(footer)

    def _build_reagent_panel(self, parent: QVBoxLayout) -> None:
        reagent_panel = Panel("12 Reagent Configuration")
        grid = QGridLayout()
        grid.setSpacing(px(8))
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Slot group 1-4 uses one card, same grid footprint as the other reagent cards.
        names_1_4 = {s: self.reagent_slots[s].name for s in range(1, 5)}
        colors_1_4 = {s: self.reagent_slots[s].color for s in range(1, 5)}
        self.phospho_group = PhosphoramiditeGroupCard(names_1_4, colors_1_4)
        self.phospho_group.reagent_clicked.connect(self._on_reagent_clicked)
        self.phospho_group.color_changed.connect(self._on_reagent_color_changed)
        grid.addWidget(self.phospho_group, 0, 0)

        for idx, slot_no in enumerate(range(5, 13)):
            slot = self.reagent_slots[slot_no]
            card = ReagentCard(slot_no, slot.name, slot.color, editable=False)
            card.clicked.connect(self._on_reagent_clicked)
            card.color_changed.connect(self._on_reagent_color_changed)
            card.name_changed.connect(self._on_reagent_name_changed)
            self.reagent_cards[slot_no] = card
            cell_index = idx + 1
            grid.addWidget(card, cell_index // 3, cell_index % 3)

        incubation_card = SpecialActionCard(INCUBATION_ACTION_TEXT, "#4a9f71")
        incubation_card.clicked.connect(self._on_special_action_clicked)
        self.special_cards[INCUBATION_ACTION_TEXT] = incubation_card
        grid.addWidget(incubation_card, 3, 0)

        drain_card = SpecialActionCard(DRAIN_ACTION_TEXT, "#667a92")
        drain_card.clicked.connect(self._on_special_action_clicked)
        self.special_cards[DRAIN_ACTION_TEXT] = drain_card
        grid.addWidget(drain_card, 3, 1)

        self.pattern_base_card = PatternBaseCard(
            base_times_ms=self.recipe.pattern_base_times
        )
        self.pattern_base_card.clicked.connect(self._on_special_action_clicked)
        self.pattern_base_card.times_changed.connect(self._on_pattern_times_changed)
        grid.addWidget(self.pattern_base_card, 3, 2)

        for row_idx in range(4):
            grid.setRowStretch(row_idx, 1)

        reagent_panel.root.addLayout(grid)
        parent.addWidget(reagent_panel, 1)

    def _build_manage_panel(self, parent: QVBoxLayout) -> None:
        manage_panel = Panel("Recipe Management")

        field_style = f"""
            QLineEdit {{
                min-height:{px(32)}px;
                background:#f8fbfe;
                border:1px solid #b8cfdf;
                border-radius:{px(6)}px;
                padding:0 {px(8)}px;
                font-size:{px(14)}px;
                font-weight:700;
                color:#1a2a38;
            }}
            QLineEdit:focus {{
                border:2px solid #2878c8;
                background:#ffffff;
            }}
        """

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(px(8))
        meta_grid.setVerticalSpacing(px(7))
        meta_grid.setColumnStretch(1, 1)

        name_lbl = QLabel("Recipe name")
        name_lbl.setStyleSheet(
            f"font-size:{px(13)}px; font-weight:800; color:#33485a; border:none;"
        )

        self._recipe_name_edit = QLineEdit()
        self._recipe_name_edit.setPlaceholderText("Recipe name")
        self._recipe_name_edit.setStyleSheet(field_style)
        self._recipe_name_edit.textChanged.connect(self._on_recipe_metadata_changed)

        meta_grid.addWidget(name_lbl, 0, 0)
        meta_grid.addWidget(self._recipe_name_edit, 0, 1)
        manage_panel.root.addLayout(meta_grid)

        status_row = QHBoxLayout()
        status_row.setSpacing(px(8))

        self._recipe_status_label = QLabel()
        self._recipe_status_label.setStyleSheet(
            f"font-size:{px(13)}px; font-weight:700; color:#41566a; border:none;"
        )

        self._recipe_dirty_badge = QLabel("Unsaved changes")
        self._recipe_dirty_badge.setAlignment(Qt.AlignCenter)
        self._recipe_dirty_badge.setStyleSheet(
            f"""
            QLabel {{
                min-height:{px(22)}px;
                padding:0 {px(9)}px;
                border-radius:{px(11)}px;
                border:1px solid #d4900a;
                background:#fff6df;
                color:#915f00;
                font-size:{px(12)}px;
                font-weight:800;
            }}
            """
        )

        status_row.addWidget(self._recipe_status_label, 1)
        status_row.addWidget(self._recipe_dirty_badge)
        manage_panel.root.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(px(10))

        load_btn = QPushButton("📂 Load Recipe")
        save_btn = QPushButton("💾 Save Recipe")
        new_btn  = QPushButton("➕ New Recipe")

        load_btn.setStyleSheet(_LOAD_BTN_STYLE)
        save_btn.setStyleSheet(_SAVE_BTN_STYLE)
        new_btn.setStyleSheet(_NEW_BTN_STYLE)

        load_btn.clicked.connect(self._load_recipe)
        save_btn.clicked.connect(self._save_recipe)
        new_btn.clicked.connect(self._new_recipe)

        btn_row.addWidget(load_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(new_btn)
        manage_panel.root.addLayout(btn_row)
        parent.addWidget(manage_panel)

    def _build_stage_table(
        self, parent_layout: QVBoxLayout, title: str, stage_key: str
    ) -> ProtocolTable:
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size:{px(14)}px; font-weight:800; color:#1e2a34;"
        )
        parent_layout.addWidget(title_lbl)

        table = ProtocolTable()
        table.set_dlp_exposure_ms(self.dlp_exposure_ms)
        table.selection_state_changed.connect(
            lambda has, t=table: self._on_table_selection_changed(t, has)
        )
        table.steps_changed.connect(self._on_table_steps_changed)
        table.selected_step_changed.connect(self._on_table_selected_step_changed)
        table.dlp_time_changed_ms.connect(self._on_table_dlp_time_changed)

        if stage_key == "cycle":
            table.setMinimumHeight(px(220))
            table_stretch = 3
        else:
            table.setMinimumHeight(px(115))
            table.setMaximumHeight(px(170))
            table_stretch = 1

        parent_layout.addWidget(table, table_stretch)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(px(6))
        add_btn = QPushButton("Add step")
        add_btn.clicked.connect(
            lambda _=False, t=table, s=stage_key: self._add_step(t, s)
        )
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        parent_layout.addLayout(btn_row)
        return table

    # ── Data sync ──────────────────────────────────────────────────────────────
    def _sync_recipe_to_tables(self) -> None:
        self.pre_table.set_steps(self.recipe.pre_processing)
        self.cycle_table.set_steps(self.recipe.cyclic_reaction)
        self.post_table.set_steps(self.recipe.post_processing)

    def _sync_recipe_from_tables(self) -> None:
        self.recipe.pre_processing  = self.pre_table.get_steps()
        self.recipe.cyclic_reaction = self.cycle_table.get_steps()
        self.recipe.post_processing = self.post_table.get_steps()

    def _sync_recipe_metadata_to_ui(self) -> None:
        if self._recipe_name_edit is None:
            return
        self._syncing_recipe_metadata = True
        self._recipe_name_edit.setText((self.recipe.name or "").strip())
        self._syncing_recipe_metadata = False
        self._refresh_recipe_management_status()

    def _sync_recipe_metadata_from_ui(self) -> None:
        if self._recipe_name_edit is None:
            return
        self.recipe.name = self._recipe_name_edit.text().strip() or "Untitled Recipe"
        self.recipe.sequence_count = TOTAL_SEQUENCES
        self.recipe.memo = ""

    def _on_recipe_metadata_changed(self) -> None:
        if self._syncing_recipe_metadata:
            return
        self._sync_recipe_metadata_from_ui()
        self._set_recipe_dirty(True)

    def _set_recipe_dirty(self, dirty: bool = True) -> None:
        self._recipe_dirty = dirty
        self._refresh_recipe_management_status()

    def _refresh_recipe_management_status(self) -> None:
        if self._recipe_status_label is None or self._recipe_dirty_badge is None:
            return
        name = (self.recipe.name or "").strip() or "Untitled Recipe"
        self._recipe_status_label.setText(f"Current: {name}")
        self._recipe_dirty_badge.setVisible(self._recipe_dirty)

    def _confirm_discard_unsaved_changes(self, title: str) -> bool:
        if not self._recipe_dirty:
            return True
        answer = QMessageBox.question(
            self,
            title,
            "You have unsaved recipe changes. Continue without saving them?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    # ── Step actions ───────────────────────────────────────────────────────────
    def _add_step(self, table: ProtocolTable, stage: str) -> None:
        default_action = PHOSPHORAMIDITE_GROUP_ACTION_TEXT
        new_step = StepItem(table.rowCount() + 1, default_action, "60s")
        table.add_step(new_step)
        self._copied_step = StepItem(new_step.step_no, new_step.action, new_step.time_sec)
        self._sync_recipe_from_tables()
        self._set_recipe_dirty(True)
        if stage == "cycle" and table.rowCount() == 1:
            table.apply_special_action(PATTERN_ACTION_TEXT)

    def _paste_step(self, table: ProtocolTable, _stage: str) -> None:
        if self._copied_step is None:
            QMessageBox.information(
                self, "Paste step", "Clipboard bo'sh — avval qadam nusxa oling."
            )
            return
        pasted = StepItem(
            table.rowCount() + 1,
            self._copied_step.action,
            self._copied_step.time_sec,
        )
        table.add_step(pasted)
        self._sync_recipe_from_tables()
        self._set_recipe_dirty(True)

    # ── Signal handlers ────────────────────────────────────────────────────────
    def _on_table_steps_changed(self) -> None:
        self._sync_recipe_from_tables()
        self._set_recipe_dirty(True)

    def _on_reagent_clicked(self, slot_no: int) -> None:
        if self.active_table is None:
            return
        if self.active_table.apply_reagent_to_selected(slot_no):
            self._highlight_selected_card(slot_no=slot_no, special_action=None)
            self._sync_recipe_from_tables()
            self._set_recipe_dirty(True)

    def _on_reagent_color_changed(self, slot_no: int, color: str) -> None:
        if slot_no not in self.reagent_slots:
            return
        self.reagent_slots[slot_no].color = color
        if slot_no in {1, 2, 3, 4} and self.phospho_group:
            self.phospho_group.set_color(slot_no, color)
        elif slot_no in self.reagent_cards:
            self.reagent_cards[slot_no].set_color(color)
        self._set_recipe_dirty(True)

    def _on_reagent_name_changed(self, slot_no: int, name: str) -> None:
        if slot_no not in self.reagent_slots:
            return
        self.reagent_slots[slot_no].name = name
        self._apply_reagent_names_to_tables()
        self._set_recipe_dirty(True)

    def _on_special_action_clicked(self, action_text: str) -> None:
        if self.active_table is None:
            return
        if self.active_table.apply_special_action(action_text):
            self._highlight_selected_card(slot_no=None, special_action=action_text)
            self._sync_recipe_from_tables()
            self._set_recipe_dirty(True)

    def _on_table_selection_changed(self, table: ProtocolTable, has_selection: bool) -> None:
        if has_selection:
            self.active_table = table
            for other in self._tables:
                if other is table:
                    continue
                other.blockSignals(True)
                other.clearSelection()
                other.blockSignals(False)
            self._set_action_cards_enabled(True)
        else:
            if all(t.currentRow() < 0 for t in self._tables):
                self.active_table = None
                self._set_action_cards_enabled(False)
                self._highlight_selected_card(slot_no=None, special_action=None)

    def _on_table_selected_step_changed(self, step: Optional[StepItem]) -> None:
        if step is None:
            return
        if is_phosphoramidite_group_action(step.action):
            self._highlight_selected_card(slot_no=1, special_action=None)
            return
        slot_no = parse_reagent_slot(step.action)
        if slot_no is not None:
            self._highlight_selected_card(slot_no=slot_no, special_action=None)
            return
        if step.action in self.special_cards:
            self._highlight_selected_card(slot_no=None, special_action=step.action)
        else:
            self._highlight_selected_card(slot_no=None, special_action=None)

    def _on_pattern_times_changed(self, times: dict) -> None:
        self.recipe.pattern_base_times = dict(times)
        for table in self._tables:
            table.set_pattern_base_times(times)
        self._set_recipe_dirty(True)

    def _on_table_dlp_time_changed(self, milliseconds: int) -> None:
        ms = int(max(EXPOSURE_MIN, min(EXPOSURE_MAX, milliseconds)))
        self.dlp_exposure_ms = ms
        for table in self._tables:
            table.set_dlp_exposure_ms(ms)
        self.dlp_exposure_changed.emit(ms)

    def _set_action_cards_enabled(self, enabled: bool) -> None:
        if self.phospho_group:
            self.phospho_group.set_interactive(enabled)
        for card in self.reagent_cards.values():
            card.set_interactive(enabled)
        for card in self.special_cards.values():
            card.set_interactive(enabled)
        if self.pattern_base_card:
            self.pattern_base_card.set_interactive(enabled)

    def _highlight_selected_card(
        self, slot_no: Optional[int], special_action: Optional[str]
    ) -> None:
        if self.phospho_group:
            self.phospho_group.set_selected_slot(
                slot_no if slot_no in {1, 2, 3, 4} else None
            )
        for card_slot, card in self.reagent_cards.items():
            card.set_selected(slot_no == card_slot)
        for action_name, card in self.special_cards.items():
            card.set_selected(special_action == action_name)
        if self.pattern_base_card:
            self.pattern_base_card.set_selected(special_action == PATTERN_ACTION_TEXT)

    def _apply_reagent_names_to_tables(self) -> None:
        mapping = {slot_no: slot.name for slot_no, slot in self.reagent_slots.items()}
        for table in [self.pre_table, self.cycle_table, self.post_table]:
            table.set_reagent_names(mapping)
            table.set_dlp_exposure_ms(self.dlp_exposure_ms)

    # ── Recipe I/O ─────────────────────────────────────────────────────────────
    def _load_recipe(self) -> None:
        if not self._confirm_discard_unsaved_changes("Load Recipe"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", "", "Recipe files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            loaded_recipe, loaded_slots = recipe_from_dict(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load Error", f"Failed to load recipe:\n{exc}")
            return

        self.recipe        = loaded_recipe
        self.reagent_slots = loaded_slots
        for slot_no in range(1, 5):
            if self.phospho_group:
                self.phospho_group.set_name(slot_no, self.reagent_slots[slot_no].name)
                self.phospho_group.set_color(slot_no, self.reagent_slots[slot_no].color)
        for slot_no in range(5, 13):
            self.reagent_cards[slot_no].set_name(self.reagent_slots[slot_no].name)
            self.reagent_cards[slot_no].set_color(self.reagent_slots[slot_no].color)
        self._apply_reagent_names_to_tables()
        self._sync_recipe_metadata_to_ui()
        self._sync_recipe_to_tables()
        self._sync_recipe_from_tables()
        if self.pattern_base_card:
            self.pattern_base_card.set_base_times_ms(self.recipe.pattern_base_times)
        self._set_recipe_dirty(False)

    def _save_recipe(self) -> None:
        self._sync_recipe_metadata_from_ui()
        self._sync_recipe_from_tables()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Recipe",
            f"{self.recipe.name or 'recipe'}.json",
            "Recipe files (*.json);;All Files (*)",
        )
        if not path:
            return
        payload = recipe_to_dict(self.recipe, self.reagent_slots)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Save Error", f"Failed to save recipe:\n{exc}")
            return
        self._set_recipe_dirty(False)
        QMessageBox.information(self, "Saved", f"Recipe saved:\n{path}")

    def _new_recipe(self) -> None:
        if not self._confirm_discard_unsaved_changes("New Recipe"):
            return
        answer = QMessageBox.question(
            self,
            "New Recipe",
            "Create a new blank recipe?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.recipe = RecipeData(
            name="New Recipe",
            memo="",
            sequence_count=TOTAL_SEQUENCES,
            pre_processing=[], cyclic_reaction=[], post_processing=[],
        )
        self._sync_recipe_metadata_to_ui()
        self._sync_recipe_to_tables()
        self._sync_recipe_from_tables()
        if self.pattern_base_card:
            self.pattern_base_card.set_base_times_ms(self.recipe.pattern_base_times)
        self._set_recipe_dirty(False)

    def _apply_and_accept(self) -> None:
        self._sync_recipe_metadata_from_ui()
        self._sync_recipe_from_tables()
        self.accept()

    # ── Public accessors ───────────────────────────────────────────────────────
    def get_recipe(self) -> RecipeData:
        self._sync_recipe_metadata_from_ui()
        self._sync_recipe_from_tables()
        return copy.deepcopy(self.recipe)

    def get_reagent_slots(self) -> Dict[int, ReagentSlot]:
        return {slot_no: copy.deepcopy(slot) for slot_no, slot in self.reagent_slots.items()}
