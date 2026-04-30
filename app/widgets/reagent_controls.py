"""Reagent and protocol widgets: ReagentCard, PhosphoramiditeGroupCard, SpecialActionCard, ProtocolTable."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.app_settings import (
    DRAIN_ACTION_TEXT,
    DLP_TIME_MARKER,
    EXPOSURE_MAX,
    EXPOSURE_MIN,
    INCUBATION_ACTION_TEXT,
    PATTERN_ACTION_TEXT,
    PHOSPHORAMIDITE_GROUP_ACTION_TEXT,
    px,
)
from app.data_models import StepItem
from app.command_helpers import (
    CommandGenerator,
    format_reagent_action,
    is_pattern_action,
    parse_reagent_slot,
)


class ReagentCard(QFrame):
    """Clickable reagent card with optional editable name field."""

    clicked = Signal(int)
    name_changed = Signal(int, str)
    color_changed = Signal(int, str)

    def __init__(
        self,
        slot_no: int,
        name: str,
        color: str,
        editable: bool,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.slot_no = slot_no
        self._editable = editable
        self._enabled_for_target = False
        self._selected = False
        self._color = color

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(12), px(10), px(12), px(10))
        layout.setSpacing(px(6))

        top = QHBoxLayout()
        top.setSpacing(px(6))

        slot_label = QLabel(str(slot_no))
        slot_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        slot_label.setStyleSheet(
            f"font-size:{px(26)}px; font-weight:900; color:#0d1c2a; border:none;"
        )
        dot = QLabel()
        dot.setFixedSize(px(13), px(13))
        dot.setCursor(Qt.PointingHandCursor)
        dot.setToolTip("Change color")
        dot.mousePressEvent = self._on_color_dot_clicked
        self._color_dot = dot
        self._apply_color_style()

        top.addWidget(slot_label)
        top.addStretch(1)
        top.addWidget(dot)
        layout.addLayout(top)

        if editable:
            self.name_widget = QLineEdit(name)
            self.name_widget.setStyleSheet(
                f"""
                QLineEdit {{
                    min-height:{px(30)}px;
                    background:#ddeaf5;
                    border:1px solid #7aaabb;
                    border-radius:{px(6)}px;
                    padding:0 {px(8)}px;
                    font-size:{px(16)}px;
                    font-weight:800;
                    color:#1a2838;
                }}
                """
            )
            self.name_widget.textChanged.connect(
                lambda text: self.name_changed.emit(self.slot_no, text.strip() or f"Slot {self.slot_no:02d}")
            )
            layout.addWidget(self.name_widget)
        else:
            self.name_widget = QLabel(name)
            self.name_widget.setWordWrap(True)
            self.name_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.name_widget.setMinimumHeight(px(30))
            self.name_widget.setStyleSheet(
                f"""
                QLabel {{
                    font-size:{px(15)}px;
                    color:{color};
                    font-weight:900;
                    border:none;
                    padding:0 {px(4)}px;
                }}
                """
            )
            layout.addWidget(self.name_widget)

        self._apply_state_style()

    def mousePressEvent(self, event) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.slot_no)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton and not self._editable:
            from PySide6.QtWidgets import QInputDialog
            current = self.get_name()
            new_name, ok = QInputDialog.getText(
                self, "Rename Reagent", "Reagent name:", text=current
            )
            if ok:
                name = new_name.strip() or current
                self.set_name(name)
                self.name_changed.emit(self.slot_no, name)
        super().mouseDoubleClickEvent(event)

    def get_name(self) -> str:
        if isinstance(self.name_widget, QLineEdit):
            text = self.name_widget.text().strip()
            return text or f"Slot {self.slot_no:02d}"
        return self.name_widget.text().strip()

    def set_name(self, name: str) -> None:
        if isinstance(self.name_widget, QLineEdit):
            self.name_widget.setText(name)
        else:
            self.name_widget.setText(name)
            self._apply_name_style()

    def set_color(self, color: str) -> None:
        if not QColor(color).isValid():
            return
        self._color = QColor(color).name()
        self._apply_color_style()
        self._apply_name_style()

    def set_interactive(self, enabled: bool) -> None:
        self._enabled_for_target = enabled
        self._apply_state_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_state_style()

    def _apply_state_style(self) -> None:
        if self._selected:
            border = "#3878b5"
            bg = "#e8f3fc"
            width = px(2)
        elif self._enabled_for_target:
            border = "#7aaabb"
            bg = "#ffffff"
            width = px(1)
        else:
            border = "#c8d8e4"
            bg = "#ffffff"
            width = px(1)
        self.setStyleSheet(
            f"""
            QFrame {{
                background:{bg};
                border:{width}px solid {border};
                border-radius:{px(10)}px;
            }}
            QLabel {{ border:none; background:transparent; }}
            QLineEdit {{
                background:#f0f6fa;
                border:1px solid #c0d4e0;
                border-radius:{px(5)}px;
                padding:0 {px(6)}px;
                font-size:{px(16)}px;
                font-weight:800;
                color:#1a2838;
                min-height:{px(24)}px;
            }}
            """
        )
        self._apply_color_style()
        self._apply_name_style()

    def _apply_color_style(self) -> None:
        self._color_dot.setStyleSheet(
            f"background:{self._color}; border:none; border-radius:{px(6)}px;"
        )

    def _apply_name_style(self) -> None:
        if isinstance(self.name_widget, QLineEdit):
            return
        self.name_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size:{px(16)}px;
                color:{self._color};
                font-weight:900;
                border:none;
                padding:0 {px(4)}px;
            }}
            """
        )

    def _choose_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Choose reagent color")
        if not chosen.isValid():
            return
        self.set_color(chosen.name())
        self.color_changed.emit(self.slot_no, self._color)

    def _on_color_dot_clicked(self, event) -> None:
        event.accept()
        self._choose_color()


class PhosphoramiditeGroupCard(QFrame):
    """Grouped card for slots 1-4 (A/T/C/G phosphoramidites)."""

    reagent_clicked = Signal(int)
    color_changed = Signal(int, str)

    _BASES: list[tuple[int, str, str]] = [
        (1, "A", "#2f77bc"),
        (2, "T", "#c54f4f"),
        (3, "C", "#3f9b67"),
        (4, "G", "#7f56c1"),
    ]

    def __init__(
        self,
        names: Dict[int, str],
        colors: Optional[Dict[int, str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._enabled_for_target = False
        self._selected_slot: Optional[int] = None
        self._names: Dict[int, str] = dict(names)
        self._colors: Dict[int, str] = {slot_no: color for slot_no, _, color in self._BASES}
        if colors:
            for slot_no, color in colors.items():
                if slot_no in self._colors and QColor(color).isValid():
                    self._colors[slot_no] = QColor(color).name()
        self._name_labels: Dict[int, QLabel] = {}
        self._num_labels: Dict[int, QLabel] = {}
        self._base_labels: Dict[int, QLabel] = {}
        self.setObjectName("phosphoramiditeGroup")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(px(78))
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(px(10), px(10), px(10), px(10))
        outer.setSpacing(px(4))

        slots = QHBoxLayout()
        slots.setSpacing(px(3))
        slots.setAlignment(Qt.AlignCenter)

        for slot_no, base, _color in self._BASES:
            slot_wrap = QWidget()
            slot_wrap.setFixedWidth(px(30))
            slot_wrap.setCursor(Qt.PointingHandCursor)
            slot_wrap.setStyleSheet("background:transparent; border:none;")
            slot_wrap.setToolTip(self._names.get(slot_no, ""))
            slot_wrap.mousePressEvent = (
                lambda _ev: self.reagent_clicked.emit(1)
            )

            slot_layout = QVBoxLayout(slot_wrap)
            slot_layout.setContentsMargins(0, 0, 0, 0)
            slot_layout.setSpacing(px(2))

            num_lbl = QLabel(str(slot_no))
            num_lbl.setAlignment(Qt.AlignCenter)
            num_lbl.setFixedWidth(px(30))
            num_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._num_labels[slot_no] = num_lbl

            base_tag = QLabel(base)
            base_tag.setAlignment(Qt.AlignCenter)
            base_tag.setFixedWidth(px(24))
            base_tag.setCursor(Qt.PointingHandCursor)
            base_tag.setToolTip(f"Change {base} color")
            base_tag.mousePressEvent = lambda event, s=slot_no: self._on_base_color_clicked(event, s)
            self._base_labels[slot_no] = base_tag

            name_lbl = QLabel(self._names.get(slot_no, ""))
            name_lbl.setVisible(False)
            name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._name_labels[slot_no] = name_lbl

            slot_layout.addWidget(num_lbl, 0, Qt.AlignHCenter)
            slot_layout.addWidget(base_tag, 0, Qt.AlignHCenter)
            slot_layout.addWidget(name_lbl)
            slots.addWidget(slot_wrap)

        outer.addLayout(slots)

        group_label = QLabel("Phosphoramidite")
        group_label.setAlignment(Qt.AlignCenter)
        group_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        group_label.setStyleSheet(
            f"font-size:{px(16)}px; font-weight:900; color:#1a2838; border:none;"
        )
        outer.addWidget(group_label)

        self._apply_card_style()

    def mousePressEvent(self, event) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self.reagent_clicked.emit(1)
        super().mousePressEvent(event)

    def set_interactive(self, enabled: bool) -> None:
        self._enabled_for_target = enabled
        self._apply_card_style()

    def set_selected_slot(self, slot_no: Optional[int]) -> None:
        self._selected_slot = slot_no
        self._apply_card_style()

    def set_name(self, slot_no: int, name: str) -> None:
        self._names[slot_no] = name
        if slot_no in self._name_labels:
            self._name_labels[slot_no].setText(name)

    def set_color(self, slot_no: int, color: str) -> None:
        if slot_no not in self._colors or not QColor(color).isValid():
            return
        self._colors[slot_no] = QColor(color).name()
        self._apply_card_style()

    def _apply_card_style(self) -> None:
        selected = self._selected_slot in {1, 2, 3, 4}
        border = "#3878b5" if selected else ("#7aaabb" if self._enabled_for_target else "#c8d8e4")
        bg = "#e8f3fc" if selected else "#ffffff"
        width = px(2) if selected else px(1)
        self.setStyleSheet(
            f"QFrame#phosphoramiditeGroup {{ background:{bg}; border:{width}px solid {border};"
            f"  border-radius:{px(10)}px; }}"
        )
        self._refresh_slot_styles()

    def _refresh_slot_styles(self) -> None:
        for slot_no, base, _color in self._BASES:
            color = self._colors[slot_no]
            self._num_labels[slot_no].setStyleSheet(
                f"font-size:{px(24)}px; font-weight:900; color:#0d1c2a; border:none;"
            )
            self._base_labels[slot_no].setStyleSheet(
                f"background:{color}; color:white; border-radius:{px(4)}px;"
                f"font-size:{px(13)}px; font-weight:900; border:none;"
                f"padding:{px(1)}px {px(4)}px;"
            )

    def _choose_color(self, slot_no: int) -> None:
        current = QColor(self._colors.get(slot_no, "#2f77bc"))
        chosen = QColorDialog.getColor(current, self, "Choose reagent color")
        if not chosen.isValid():
            return
        self.set_color(slot_no, chosen.name())
        self.color_changed.emit(slot_no, self._colors[slot_no])

    def _on_base_color_clicked(self, event, slot_no: int) -> None:
        event.accept()
        self._choose_color(slot_no)


class SpecialActionCard(QFrame):
    """Clickable card for protocol special actions (Incubation, drain, Pattern base)."""

    clicked = Signal(str)

    def __init__(self, action_text: str, color: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.action_text = action_text
        self._enabled_for_target = False
        self._selected = False
        self._color = color
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(10), px(8), px(10), px(8))

        label = QLabel(action_text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"font-size:{px(17)}px; font-weight:900; color:#17324b; border:none;"
        )
        layout.addWidget(label)

        self._apply_state_style()

    def mousePressEvent(self, event) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.action_text)
        super().mousePressEvent(event)

    def set_interactive(self, enabled: bool) -> None:
        self._enabled_for_target = enabled
        self._apply_state_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_state_style()

    def _apply_state_style(self) -> None:
        if self._selected:
            border = "#3878b5"
            width = px(2)
            bg = "#ebf4fb"
        elif self._enabled_for_target:
            border = "#7aaabb"
            width = px(1)
            bg = "#ddeaf5"
        else:
            border = "#9cb8c8"
            width = px(1)
            bg = "#e7f0f7"
        self.setStyleSheet(
            f"""
            QFrame {{
                background:{bg};
                border:{width}px solid {border};
                border-radius:{px(10)}px;
            }}
            """
        )


class PatternBaseCard(QFrame):
    """Card for Pattern base action with individual per-base exposure time inputs."""

    clicked = Signal(str)
    times_changed = Signal(object)  # Dict[str, int] milliseconds per base

    _BASES: list[tuple[str, str]] = [
        ("A", "#2f77bc"),
        ("T", "#c54f4f"),
        ("C", "#3f9b67"),
        ("G", "#7f56c1"),
    ]

    def __init__(
        self,
        base_times_ms: Optional[Dict[str, int]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._enabled_for_target = False
        self._selected = False
        self._spinboxes: Dict[str, QDoubleSpinBox] = {}
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(10), px(6), px(10), px(8))
        layout.setSpacing(px(4))

        title = QLabel("Pattern base (A,T,C,G)")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title.setStyleSheet(
            f"font-size:{px(14)}px; font-weight:900; color:#17324b; border:none;"
        )
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(px(4))
        grid.setContentsMargins(0, 0, 0, 0)

        _spinbox_style = (
            f"QDoubleSpinBox {{"
            f"  background:#f0f6fa; border:1px solid #b8cfdf;"
            f"  border-radius:{px(4)}px; padding:0 {px(2)}px;"
            f"  font-size:{px(12)}px; font-weight:700; color:#1a2838;"
            f"  min-height:{px(22)}px;"
            f"}}"
            f"QDoubleSpinBox:focus {{ border:1px solid #2878c8; background:#ffffff; }}"
        )

        for idx, (base, color) in enumerate(self._BASES):
            row_idx, col = divmod(idx, 2)

            cell = QWidget()
            cell.setStyleSheet("background:transparent; border:none;")
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(px(3))

            tag = QLabel(base)
            tag.setFixedWidth(px(16))
            tag.setAlignment(Qt.AlignCenter)
            tag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            tag.setStyleSheet(
                f"color:{color}; font-size:{px(14)}px; font-weight:900;"
                f"border:none; background:transparent;"
            )

            default_ms = (base_times_ms or {}).get(base, 3500)
            spinbox = QDoubleSpinBox()
            spinbox.setRange(0.1, 60.0)
            spinbox.setSingleStep(0.5)
            spinbox.setDecimals(1)
            spinbox.setValue(max(0.1, default_ms / 1000.0))
            spinbox.setFixedWidth(px(60))
            spinbox.setStyleSheet(_spinbox_style)
            spinbox.valueChanged.connect(self._on_time_changed)
            self._spinboxes[base] = spinbox

            unit = QLabel("s")
            unit.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            unit.setStyleSheet(
                f"color:#3a5068; font-size:{px(13)}px; font-weight:700;"
                f"border:none; background:transparent;"
            )

            cell_layout.addWidget(tag)
            cell_layout.addWidget(spinbox)
            cell_layout.addWidget(unit)
            grid.addWidget(cell, row_idx, col)

        layout.addLayout(grid)
        self._apply_state_style()

    def mousePressEvent(self, event) -> None:  # noqa: D401
        if event.button() == Qt.LeftButton:
            self.clicked.emit(PATTERN_ACTION_TEXT)
        super().mousePressEvent(event)

    def get_base_times_ms(self) -> Dict[str, int]:
        return {base: max(1, int(round(spin.value() * 1000))) for base, spin in self._spinboxes.items()}

    def set_base_times_ms(self, times: Dict[str, int]) -> None:
        for base, spin in self._spinboxes.items():
            if base in times:
                spin.blockSignals(True)
                spin.setValue(max(0.1, times[base] / 1000.0))
                spin.blockSignals(False)

    def set_interactive(self, enabled: bool) -> None:
        self._enabled_for_target = enabled
        self._apply_state_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_state_style()

    def _on_time_changed(self) -> None:
        self.times_changed.emit(self.get_base_times_ms())

    def _apply_state_style(self) -> None:
        if self._selected:
            border = "#3878b5"
            width = px(2)
            bg = "#ebf4fb"
        elif self._enabled_for_target:
            border = "#7aaabb"
            width = px(1)
            bg = "#ddeaf5"
        else:
            border = "#9cb8c8"
            width = px(1)
            bg = "#e7f0f7"
        self.setStyleSheet(
            f"""
            QFrame {{
                background:{bg};
                border:{width}px solid {border};
                border-radius:{px(10)}px;
            }}
            """
        )


class StepEditDialog(QDialog):
    """Dialog for editing a single protocol step's Time and Command fields."""

    def __init__(
        self,
        step: StepItem,
        auto_command: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Step {step.step_no}")
        self.setMinimumWidth(px(480))
        self._auto_command = auto_command

        _field = (
            f"QLineEdit {{"
            f"min-height:{px(32)}px; background:#f8fbfe; border:1px solid #b8cfdf;"
            f"border-radius:{px(6)}px; padding:0 {px(8)}px;"
            f"font-size:{px(13)}px; font-weight:700; color:#1a2a38;}}"
            f"QLineEdit:focus {{border:2px solid #2878c8; background:#ffffff;}}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(px(12))
        layout.setContentsMargins(px(20), px(16), px(20), px(16))

        info = QLabel(f"Step {step.step_no}:  {step.action}")
        info.setStyleSheet(f"font-size:{px(15)}px; font-weight:800; color:#1e2a34;")
        layout.addWidget(info)

        time_row = QHBoxLayout()
        time_lbl = QLabel("Time:")
        time_lbl.setFixedWidth(px(80))
        time_lbl.setStyleSheet(f"font-size:{px(13)}px; font-weight:700; color:#1a2a38;")
        self._time_edit = QLineEdit(step.time_sec)
        self._time_edit.setStyleSheet(_field)
        time_row.addWidget(time_lbl)
        time_row.addWidget(self._time_edit, 1)
        layout.addLayout(time_row)

        cmd_row = QHBoxLayout()
        cmd_lbl = QLabel("Command:")
        cmd_lbl.setFixedWidth(px(80))
        cmd_lbl.setStyleSheet(f"font-size:{px(13)}px; font-weight:700; color:#1a2a38;")
        self._cmd_edit = QLineEdit(step.command if step.command else auto_command)
        self._cmd_edit.setStyleSheet(_field)
        reset_btn = QPushButton("↺")
        reset_btn.setFixedSize(px(34), px(32))
        reset_btn.setToolTip("Reset to auto-generated command")
        reset_btn.setStyleSheet(
            f"QPushButton {{background:#eff6ff; border:1px solid #93c5fd;"
            f"border-radius:{px(6)}px; font-size:{px(16)}px; color:#1e40af;}}"
            f"QPushButton:hover {{background:#dbeafe;}}"
        )
        reset_btn.clicked.connect(self._reset_command)
        cmd_row.addWidget(cmd_lbl)
        cmd_row.addWidget(self._cmd_edit, 1)
        cmd_row.addWidget(reset_btn)
        layout.addLayout(cmd_row)

        hint = QLabel(
            "Command auto-generated from Action + Time. "
            "Edit to override, or press ↺ to restore auto."
        )
        hint.setStyleSheet(
            f"font-size:{px(11)}px; color:#607080; font-style:italic;"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _reset_command(self) -> None:
        self._cmd_edit.setText(self._auto_command)

    def get_time(self) -> str:
        return self._time_edit.text().strip()

    def get_command(self) -> str:
        text = self._cmd_edit.text().strip()
        return "" if text == self._auto_command else text


class ProtocolTable(QTableWidget):
    """Protocol editor table with row selection, inline time editing, and edit/delete controls."""

    selection_state_changed = Signal(bool)
    selected_step_changed = Signal(object)
    steps_changed = Signal()
    dlp_time_changed_ms = Signal(int)

    # Column indices
    _COL_STEP = 0
    _COL_ACTION = 1
    _COL_COMMAND = 2
    _COL_TIME = 3
    _COL_DELETE = 4

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(0, 5, parent)
        self._steps: List[StepItem] = []
        self._reagent_names: Dict[int, str] = {
            1: "Phosphoramidite (A)",
            2: "Phosphoramidite (T)",
            3: "Phosphoramidite (C)",
            4: "Phosphoramidite (G)",
            5: "Activator",
            6: "Oxidizer",
            7: "Capping A",
            8: "Capping B",
            9: "Deblock",
            10: "Wash 1",
            11: "Wash 2",
            12: "Wash 3",
        }
        self._dlp_exposure_ms = 3500
        self._pattern_base_times: Dict[str, int] = {"A": 3500, "T": 3500, "C": 3500, "G": 3500}
        self._updating = False
        self._delete_icon = self._create_delete_icon()

        self.setHorizontalHeaderLabels(["Step #", "Action", "Command", "Time(s)", "Delete"])
        self.horizontalHeader().setSectionResizeMode(self._COL_STEP, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self._COL_ACTION, QHeaderView.Interactive)
        self.setColumnWidth(self._COL_ACTION, px(210))
        self.horizontalHeader().setSectionResizeMode(self._COL_COMMAND, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(self._COL_TIME, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(self._COL_DELETE, QHeaderView.Fixed)
        self.setColumnWidth(self._COL_DELETE, px(62))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(px(40))
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.setAlternatingRowColors(True)
        self.setStyleSheet(
            f"""
            QTableWidget {{
                background:#ddeaf5;
                alternate-background-color:#c0d8e8;
                border:1px solid #7aaabb;
                border-radius:{px(8)}px;
                gridline-color:#8aacbc;
                selection-background-color:#cde0f0;
                selection-color:#0e1e2f;
                font-size:{px(15)}px;
            }}
            QHeaderView::section {{
                background:#a8c8d8;
                color:#1a2a38;
                border:none;
                border-bottom:1px solid #7aaabb;
                font-weight:700;
                font-size:{px(15)}px;
                padding:{px(6)}px;
            }}
            """
        )

        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemChanged.connect(self._on_item_changed)
        self.cellClicked.connect(self._on_cell_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_dlp_exposure_ms(self, value: int) -> None:
        self._dlp_exposure_ms = int(max(EXPOSURE_MIN, min(EXPOSURE_MAX, value)))
        self._refresh_dlp_time_items()

    def set_pattern_base_times(self, times: Dict[str, int]) -> None:
        self._pattern_base_times = dict(times)
        self._updating = True
        for row, step in enumerate(self._steps):
            if is_pattern_action(step.action) and step.time_sec.strip().upper() == DLP_TIME_MARKER:
                time_item = self.item(row, self._COL_TIME)
                if time_item is not None:
                    time_item.setText(self._pattern_time_display_text())
        self._updating = False

    def set_reagent_names(self, names: Dict[int, str]) -> None:
        for slot_no, name in names.items():
            if 1 <= slot_no <= 12:
                self._reagent_names[slot_no] = name

        changed = False
        for step in self._steps:
            slot_no = parse_reagent_slot(step.action)
            if slot_no is not None:
                if slot_no in {1, 2, 3, 4}:
                    new_action = PHOSPHORAMIDITE_GROUP_ACTION_TEXT
                else:
                    new_action = format_reagent_action(slot_no, self._reagent_names[slot_no])
                if step.action != new_action:
                    step.action = new_action
                    changed = True

        if changed:
            self._rebuild_table()
            self.steps_changed.emit()

    def set_steps(self, items: List[StepItem]) -> None:
        steps: List[StepItem] = []
        for idx, item in enumerate(items):
            action = item.action
            slot_no = parse_reagent_slot(action)
            if slot_no in {1, 2, 3, 4}:
                action = PHOSPHORAMIDITE_GROUP_ACTION_TEXT
            steps.append(StepItem(idx + 1, action, item.time_sec, item.command))
        self._steps = steps
        self._rebuild_table()

    def get_steps(self) -> List[StepItem]:
        return [StepItem(step.step_no, step.action, step.time_sec, step.command) for step in self._steps]

    def add_step(self, item: Optional[StepItem] = None) -> None:
        if item is None:
            item = StepItem(len(self._steps) + 1, PHOSPHORAMIDITE_GROUP_ACTION_TEXT, "60s")
        self._steps.append(StepItem(len(self._steps) + 1, item.action, item.time_sec, item.command))
        self._rebuild_table()
        self.steps_changed.emit()

    def remove_selected_step(self) -> None:
        row = self.currentRow()
        if row < 0 or row >= len(self._steps):
            return
        del self._steps[row]
        self._renumber_steps()
        self._rebuild_table()
        self.steps_changed.emit()

    def apply_reagent_to_selected(self, slot_no: int) -> bool:
        row = self.currentRow()
        if row < 0 or row >= len(self._steps):
            return False

        step = self._steps[row]
        if slot_no in {1, 2, 3, 4}:
            step.action = PHOSPHORAMIDITE_GROUP_ACTION_TEXT
        else:
            step.action = format_reagent_action(slot_no, self._reagent_names.get(slot_no, f"Slot {slot_no:02d}"))
        if step.time_sec.strip().upper() == DLP_TIME_MARKER:
            step.time_sec = "60s"
        step.command = ""  # reset override when action changes
        self._refresh_row(row)
        self.steps_changed.emit()
        self.selected_step_changed.emit(StepItem(step.step_no, step.action, step.time_sec, step.command))
        return True

    def apply_special_action(self, action_text: str) -> bool:
        row = self.currentRow()
        if row < 0 or row >= len(self._steps):
            return False

        step = self._steps[row]
        old_time = step.time_sec
        step.action = action_text
        if is_pattern_action(action_text):
            step.time_sec = DLP_TIME_MARKER
        elif old_time.strip().upper() == DLP_TIME_MARKER:
            step.time_sec = "60s"

        step.command = ""  # reset override when action changes
        self._refresh_row(row)
        self.steps_changed.emit()
        self.selected_step_changed.emit(StepItem(step.step_no, step.action, step.time_sec, step.command))
        return True

    def _renumber_steps(self) -> None:
        for idx, step in enumerate(self._steps, start=1):
            step.step_no = idx

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == self._COL_TIME:
            item = self.item(row, column)
            if item is not None:
                if 0 <= row < len(self._steps) and item.text().strip().upper() == DLP_TIME_MARKER:
                    item.setText(self._time_display_text(self._steps[row].time_sec))
                self.editItem(item)

    def _on_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if not (0 <= row < len(self._steps)):
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        edit_action = menu.addAction("✏️  Edit step command...")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is edit_action:
            self._open_step_edit_dialog(row)

    def _open_step_edit_dialog(self, row: int) -> None:
        step = self._steps[row]
        auto_cmd = self._compute_command_text(step)
        dialog = StepEditDialog(step, auto_cmd, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        new_time = dialog.get_time() or step.time_sec
        new_cmd = dialog.get_command()
        changed = new_time != step.time_sec or new_cmd != step.command
        if changed:
            step.time_sec = new_time
            step.command = new_cmd
            self._refresh_row(row)
            self.steps_changed.emit()
            self.selected_step_changed.emit(
                StepItem(step.step_no, step.action, step.time_sec, step.command)
            )

    def _on_selection_changed(self) -> None:
        has_selection = self.currentRow() >= 0
        self.selection_state_changed.emit(has_selection)
        if has_selection and self.currentRow() < len(self._steps):
            step = self._steps[self.currentRow()]
            self.selected_step_changed.emit(StepItem(step.step_no, step.action, step.time_sec, step.command))
        else:
            self.selected_step_changed.emit(None)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = item.row()
        col = item.column()

        if col == self._COL_COMMAND and 0 <= row < len(self._steps):
            self._steps[row].command = item.text().strip()
            self._updating = True
            self._style_command_item(item, bool(self._steps[row].command))
            self._updating = False
            self.steps_changed.emit()
            return

        if col != self._COL_TIME or not (0 <= row < len(self._steps)):
            return

        step = self._steps[row]
        old_time = step.time_sec
        new_time = item.text().strip()
        if not new_time:
            new_time = old_time

        if is_pattern_action(step.action):
            if new_time.upper() == DLP_TIME_MARKER:
                step.time_sec = DLP_TIME_MARKER
            else:
                step.time_sec = new_time
                if old_time.strip().upper() == DLP_TIME_MARKER:
                    ms = CommandGenerator.parse_time_to_milliseconds(step.time_sec, self._dlp_exposure_ms)
                    if ms is not None:
                        self.dlp_time_changed_ms.emit(ms)
        else:
            if new_time.upper() == DLP_TIME_MARKER:
                new_time = old_time
            step.time_sec = new_time

        self._updating = True
        item.setText(self._time_display_text(step.time_sec))
        self._style_time_item(item, step.time_sec)
        if not step.command:
            cmd_item = self.item(row, self._COL_COMMAND)
            if cmd_item is not None:
                cmd_item.setText(self._compute_command_text(step))
        self._updating = False

        self.steps_changed.emit()
        self.selected_step_changed.emit(StepItem(step.step_no, step.action, step.time_sec, step.command))

    def _compute_command_text(self, step: StepItem) -> str:
        return CommandGenerator.generate(step, self._dlp_exposure_ms)

    def _style_command_item(self, item: QTableWidgetItem, is_custom: bool) -> None:
        font = item.font()
        font.setBold(is_custom)
        item.setFont(font)
        item.setForeground(QColor("#7c3caa") if is_custom else QColor("#0e4a1a"))

    def _rebuild_table(self) -> None:
        self._updating = True
        self.setRowCount(0)
        self._renumber_steps()

        for row, step in enumerate(self._steps):
            self.insertRow(row)

            step_item = QTableWidgetItem(str(step.step_no))
            step_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            step_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, self._COL_STEP, step_item)

            action_item = QTableWidgetItem(step.action)
            action_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.setItem(row, self._COL_ACTION, action_item)

            cmd_text = step.command if step.command else self._compute_command_text(step)
            cmd_item = QTableWidgetItem(cmd_text)
            cmd_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            self._style_command_item(cmd_item, bool(step.command))
            self.setItem(row, self._COL_COMMAND, cmd_item)

            if is_pattern_action(step.action) and step.time_sec.strip().upper() == DLP_TIME_MARKER:
                time_item = QTableWidgetItem(self._pattern_time_display_text())
                time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                time_item.setTextAlignment(Qt.AlignCenter)
                time_item.setForeground(QColor("#2f77bc"))
                font = time_item.font()
                font.setBold(True)
                time_item.setFont(font)
                self.setItem(row, self._COL_TIME, time_item)
                self.setRowHeight(row, px(52))
            else:
                time_item = QTableWidgetItem(self._time_display_text(step.time_sec))
                time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                time_item.setTextAlignment(Qt.AlignCenter)
                self._style_time_item(time_item, step.time_sec)
                self.setItem(row, self._COL_TIME, time_item)

            self.setCellWidget(row, self._COL_DELETE, self._build_delete_widget(row))

        self._updating = False

    def _refresh_row(self, row: int) -> None:
        if not (0 <= row < len(self._steps)):
            return

        step = self._steps[row]
        self._updating = True
        self.item(row, self._COL_STEP).setText(str(step.step_no))
        self.item(row, self._COL_STEP).setTextAlignment(Qt.AlignCenter)
        self.item(row, self._COL_ACTION).setText(step.action)
        cmd_text = step.command if step.command else self._compute_command_text(step)
        self.item(row, self._COL_COMMAND).setText(cmd_text)
        self._style_command_item(self.item(row, self._COL_COMMAND), bool(step.command))
        if is_pattern_action(step.action) and step.time_sec.strip().upper() == DLP_TIME_MARKER:
            t_item = self.item(row, self._COL_TIME)
            t_item.setText(self._pattern_time_display_text())
            t_item.setTextAlignment(Qt.AlignCenter)
            t_item.setForeground(QColor("#2f77bc"))
            font = t_item.font()
            font.setBold(True)
            t_item.setFont(font)
            self.setRowHeight(row, px(52))
        else:
            self.item(row, self._COL_TIME).setText(self._time_display_text(step.time_sec))
            self.item(row, self._COL_TIME).setTextAlignment(Qt.AlignCenter)
            self._style_time_item(self.item(row, self._COL_TIME), step.time_sec)
        self._updating = False

    def _pattern_time_display_text(self) -> str:
        def _fmt(base: str) -> str:
            return f"{self._pattern_base_times.get(base, 3500) / 1000:.1f}s"
        return f"A: {_fmt('A')}   T: {_fmt('T')}\nC: {_fmt('C')}   G: {_fmt('G')}"

    def _time_display_text(self, text: str) -> str:
        if text.strip().upper() == DLP_TIME_MARKER:
            return "-"
        t = text.strip()
        if t.lower().endswith("s") and t[:-1].isdigit():
            return t[:-1]
        return t

    def _refresh_dlp_time_items(self) -> None:
        if not self._steps:
            return
        self._updating = True
        for row, step in enumerate(self._steps):
            if step.time_sec.strip().upper() == DLP_TIME_MARKER:
                time_item = self.item(row, self._COL_TIME)
                if time_item is not None:
                    time_item.setText(self._time_display_text(step.time_sec))
                    time_item.setTextAlignment(Qt.AlignCenter)
                    self._style_time_item(time_item, step.time_sec)
                if not step.command:
                    cmd_item = self.item(row, self._COL_COMMAND)
                    if cmd_item is not None:
                        cmd_item.setText(self._compute_command_text(step))
        self._updating = False

    def _style_time_item(self, item: QTableWidgetItem, text: str) -> None:
        if text.strip().upper() == DLP_TIME_MARKER:
            item.setForeground(QColor("#2f77bc"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        else:
            item.setForeground(QColor("#1c3448"))
            font = item.font()
            font.setBold(False)
            item.setFont(font)

    def _create_delete_icon(self) -> QIcon:
        icon_size = px(18)
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(
            QPen(
                QColor("#ffffff"),
                max(1, px(2)),
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.setBrush(Qt.NoBrush)

        body = QRectF(icon_size * 0.30, icon_size * 0.38, icon_size * 0.40, icon_size * 0.44)
        painter.drawRoundedRect(body, px(2), px(2))
        painter.drawLine(
            int(icon_size * 0.25),
            int(icon_size * 0.34),
            int(icon_size * 0.75),
            int(icon_size * 0.34),
        )
        painter.drawLine(
            int(icon_size * 0.43),
            int(icon_size * 0.24),
            int(icon_size * 0.57),
            int(icon_size * 0.24),
        )
        painter.drawLine(
            int(icon_size * 0.44),
            int(icon_size * 0.50),
            int(icon_size * 0.44),
            int(icon_size * 0.72),
        )
        painter.drawLine(
            int(icon_size * 0.56),
            int(icon_size * 0.50),
            int(icon_size * 0.56),
            int(icon_size * 0.72),
        )
        painter.end()

        return QIcon(pixmap)

    def _build_delete_widget(self, row: int) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(px(2), px(2), px(2), px(2))
        layout.setAlignment(Qt.AlignCenter)

        delete_btn = QPushButton()
        delete_btn.setFixedSize(px(30), px(26))
        delete_btn.setText("")
        delete_btn.setToolTip("Delete step")
        delete_btn.setAccessibleName("Delete step")
        delete_btn.setIcon(self._delete_icon)
        delete_btn.setIconSize(QSize(px(16), px(16)))
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setStyleSheet(
            f"""
            QPushButton {{
                background:#bd2740;
                border:1px solid #8f1d32;
                border-radius:{px(5)}px;
                padding:0;
            }}
            QPushButton:hover {{
                background:#a91f37;
                border-color:#76172a;
            }}
            QPushButton:pressed {{
                background:#8f1a30;
                padding-top:{px(1)}px;
            }}
            """
        )
        delete_btn.clicked.connect(lambda _checked=False, r=row: self._delete_row_at(r))

        layout.addWidget(delete_btn)
        return wrap

    def _delete_row_at(self, row: int) -> None:
        if not (0 <= row < len(self._steps)):
            return
        del self._steps[row]
        self._renumber_steps()
        self._rebuild_table()
        self.steps_changed.emit()
