"""Sahifa 3: Main 3-pane Gene Synthesizer controller window."""
from __future__ import annotations

import math
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.qt_environment import configure_qt_environment

configure_qt_environment()

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    BASES,
    DLP_TIME_MARKER,
    INFINITE_TIME_MARKER,
    LED_MAX,
    LED_MIN,
    TOTAL_SEQUENCES,
    px,
)
from app.models import RecipeData, ReagentSlot, StepItem
from app.recipe_io import default_reagent_slots, default_recipe
from app.utils import (
    CommandGenerator,
    is_incubation_action,
    is_pattern_action,
    is_phosphoramidite_group_action,
)
from app.widgets.base_widgets import BaseChip, BigBaseCircle, CircleProgress
from app.widgets.primitives import ControlButton, EventLine, MiniMetricBox, Panel
from app.widgets.sequence_row import SequenceRow
from pages.dlp_dialog import DlpDialog
from pages.recipe_dialog import RecipeSetupDialog


class MainWindow(QMainWindow):
    """Main 3-pane Gene Synthesizer controller window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gene Synthesizer")
        self.resize(1320, 820)
        self.setStyleSheet(
            """
            QMainWindow { background:#dce5ed; }
            QLabel { color:#222; }
            QPushButton:disabled {
                background:#ccd8e4;
                color:#7090a8;
                border:1px solid #aabccc;
            }
            """
        )

        self.reagent_slots = default_reagent_slots()
        self.recipe = default_recipe(self.reagent_slots)
        self.pattern_folder_path = ""

        self.is_running = False
        self.hold_infinite = False
        self.current_stage = "idle"
        self.current_step_index = 0
        self.sequence_index = 1
        self.base_index = 0
        self.current_sequence = 1
        self.current_base = BASES[0]
        self.completed_bases = 0

        self.event_log_lines: List[str] = []
        self.log_dirty = False

        self.sequence_rows: Dict[int, SequenceRow] = {}
        self.base_chips: Dict[str, BaseChip] = {}
        self.dlp_controls: List[QWidget] = []

        self.step_timer = QTimer(self)
        self.step_timer.setSingleShot(True)
        self.step_timer.timeout.connect(self._on_step_timeout)

        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(1000)
        self.metrics_timer.timeout.connect(self._update_time_metrics)

        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(80)
        self.progress_timer.timeout.connect(self._update_big_base_progress)

        self._blink_state = True
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(300)
        self.blink_timer.timeout.connect(self._on_blink_tick)

        self.run_started_monotonic = 0.0
        self.elapsed_seconds = 0
        self.current_step_duration_ms = 0

        self._build_ui()
        self._reset_visual_state()
        self._seed_sequence_overview_preview()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(px(18), px(18), px(18), px(18))
        root.setSpacing(px(14))

        root.addLayout(self._build_top_bar())

        body = QHBoxLayout()
        body.setSpacing(px(12))
        root.addLayout(body, 1)

        left_panel = self._build_sequence_overview_panel()
        body.addWidget(left_panel, 2)

        center_col = QVBoxLayout()
        center_col.setSpacing(px(12))
        center_col.addWidget(self._build_current_synthesis_panel(), 1)
        seq_data = self._build_sequence_data_panel()
        seq_data.setMinimumHeight(px(320))
        center_col.addWidget(seq_data, 1)
        body.addLayout(center_col, 3)

        right_col = QVBoxLayout()
        right_col.setSpacing(px(12))
        right_col.addWidget(self._build_dlp_settings_panel(), 1)
        right_col.addWidget(self._build_event_log_panel(), 1)
        body.addLayout(right_col, 3)

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(px(18))

        title = QLabel("GENE SYNTHESIZER")
        title.setStyleSheet(f"font-size:{px(30)}px; font-weight:900; color:#1848a0;")
        row.addWidget(title)
        row.addStretch(1)

        self.percent_circle = CircleProgress(0)
        row.addWidget(self.percent_circle)

        self.progress_text = QLabel("READY")
        self.progress_text.setStyleSheet(f"font-size:{px(16)}px; font-weight:700; color:#24272a;")
        row.addWidget(self.progress_text)
        row.addStretch(1)

        self.dlp_test_btn = ControlButton("🔬 DLP Test")
        self.dlp_test_btn.clicked.connect(self.open_dlp_dialog)
        row.addWidget(self.dlp_test_btn)

        self.start_btn = ControlButton("▶ START", primary=True)
        self.pause_btn = ControlButton("⏸ PAUSE")
        self.stop_btn = ControlButton("■ STOP")
        self.start_btn.clicked.connect(self.start_process)
        self.pause_btn.clicked.connect(self.pause_process)
        self.stop_btn.clicked.connect(self.stop_process)
        row.addWidget(self.start_btn)
        row.addWidget(self.pause_btn)
        row.addWidget(self.stop_btn)
        return row

    def _build_sequence_overview_panel(self) -> Panel:
        panel = Panel("SEQUENCE OVERVIEW - 20mer")
        panel.setObjectName("sequenceOverviewPanel")
        panel.root.setContentsMargins(px(18), px(16), px(18), px(16))
        panel.root.setSpacing(px(12))

        grid = QGridLayout()
        grid.setHorizontalSpacing(px(15))
        grid.setVerticalSpacing(px(6))
        row_height = px(46)

        for idx in range(10):
            left_seq = idx + 1
            right_seq = idx + 11

            left_row = SequenceRow(left_seq, active=(left_seq == self.sequence_index))
            right_row = SequenceRow(right_seq, active=(right_seq == self.sequence_index))
            left_row.setMinimumHeight(row_height)
            right_row.setMinimumHeight(row_height)
            self.sequence_rows[left_seq] = left_row
            self.sequence_rows[right_seq] = right_row

            grid.addWidget(left_row, idx, 0)
            grid.addWidget(right_row, idx, 1)
            grid.setRowStretch(idx, 1)

        panel.root.addLayout(grid, 1)
        return panel

    def _build_current_synthesis_panel(self) -> Panel:
        panel = Panel("CURRENT SYNTHESIS - POSITION 1")
        panel.setObjectName("currentSynthesisPanel")
        panel.setMinimumHeight(px(320))
        panel.setStyleSheet(
            f"""
            QFrame#currentSynthesisPanel {{
                background:#ffffff;
                border:1px solid #e2e8ef;
                border-radius:{px(6)}px;
            }}
            QFrame#currentSynthesisPanel QLabel {{
                background:transparent;
                border:none;
            }}
            """
        )
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(px(16))
        shadow.setOffset(0, px(2))
        shadow.setColor(QColor(16, 32, 48, 38))
        panel.setGraphicsEffect(shadow)
        panel.title_label.setStyleSheet(
            f"font-size:{px(14)}px; font-weight:900; color:#20242a; border:none;"
        )
        panel.root.setContentsMargins(px(16), px(14), px(16), px(14))
        panel.root.setSpacing(px(8))
        self.current_synthesis_panel = panel
        center = QVBoxLayout()
        center.setSpacing(px(14))
        center.setAlignment(Qt.AlignHCenter)

        self.big_base_circle = BigBaseCircle(self.current_base)
        center.addWidget(self.big_base_circle, alignment=Qt.AlignHCenter)

        chips = QHBoxLayout()
        chips.setSpacing(px(6))
        for base in BASES:
            chip = BaseChip(base, selected=(base == self.current_base))
            chip.clicked.connect(lambda _checked=False, b=base: self._on_base_chip_clicked(b))
            self.base_chips[base] = chip
            chips.addWidget(chip)
        center.addLayout(chips)

        self.stage_label = QLabel("Stage 1: Ready")
        self.stage_label.setAlignment(Qt.AlignCenter)
        self.stage_label.setWordWrap(False)
        self.stage_label.setMinimumWidth(px(360))
        self.stage_label.setMinimumHeight(px(24))
        self.stage_label.setStyleSheet(f"font-size:{px(16)}px; font-weight:900; color:#1975a5;")
        center.addWidget(self.stage_label, alignment=Qt.AlignHCenter)

        self.pattern_label = QLabel("Pattern folder not loaded")
        self.pattern_label.setAlignment(Qt.AlignCenter)
        self.pattern_label.setMinimumHeight(px(20))
        self.pattern_label.setStyleSheet(f"font-size:{px(13)}px; color:#6b7d8b; font-style:italic;")
        center.addWidget(self.pattern_label, alignment=Qt.AlignHCenter)

        panel.root.addStretch(1)
        panel.root.addLayout(center)
        panel.root.addStretch(1)
        return panel

    def _build_sequence_data_panel(self) -> Panel:
        panel = Panel("Synthesis Protocol & Process Status")

        self.recipe_setup_btn = QPushButton("☷ Reagent Synthesis Protocol Setup")
        self.recipe_setup_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(40)}px;
                border:1px solid #93c5fd;
                border-radius:{px(8)}px;
                background:#eff6ff;
                color:#1e40af;
                font-size:{px(14)}px;
                font-weight:700;
                text-align:left;
                padding-left:{px(16)}px;
            }}
            QPushButton:hover {{ background:#dbeafe; }}
            """
        )
        self.recipe_setup_btn.clicked.connect(self.open_recipe_setup_dialog)
        panel.root.addWidget(self.recipe_setup_btn)

        metrics = QHBoxLayout()
        self.elapsed_box = MiniMetricBox("⏱ PROCESS TIME", "00:00:00", "Elapsed")
        self.remaining_box = MiniMetricBox("⏳ REMAINING TIME", "00:00:00", "Estimated")
        metrics.addWidget(self.elapsed_box)
        metrics.addWidget(self.remaining_box)
        panel.root.addLayout(metrics)

        folder_title = QLabel("Sequence Data(Masks)")
        folder_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        folder_title.setStyleSheet(
            f"font-size:{px(16)}px; font-weight:800; color:#1a2a38; border:none; background:transparent;"
        )
        panel.root.addWidget(folder_title)

        folder_row = QHBoxLayout()
        self.load_pattern_btn = QPushButton("📁 Load Pattern Folder")
        self.load_pattern_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(36)}px;
                padding:0 {px(14)}px;
                border-radius:{px(8)}px;
                border:1px solid #93c5fd;
                background:#eff6ff;
                color:#1e40af;
                font-size:{px(13)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#dbeafe; }}
            """
        )
        self.load_pattern_btn.clicked.connect(self.pick_pattern_folder)
        self.pattern_folder_edit = QLineEdit()
        self.pattern_folder_edit.setReadOnly(True)
        self.pattern_folder_edit.setPlaceholderText("Select folder containing process masks")
        self.pattern_folder_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background:#f8fafc;
                border:1px solid #cbd5e1;
                border-radius:{px(8)}px;
                min-height:{px(36)}px;
                padding:0 {px(10)}px;
                color:#1e293b;
            }}
            """
        )
        folder_row.addWidget(self.load_pattern_btn)
        folder_row.addWidget(self.pattern_folder_edit, 1)
        panel.root.addLayout(folder_row)
        panel.root.addStretch(1)

        return panel

    def _build_dlp_settings_panel(self) -> Panel:
        panel = Panel("DLP OPTICAL SYSTEM SETTINGS")
        panel.setMinimumHeight(px(320))

        panel.root.addStretch(1)
        led_block, self.led_slider, self.led_value_label = self._build_slider_block(
            "LED POWER",
            "percent",
            LED_MIN,
            LED_MAX,
            85,
            lambda _: None,
        )
        panel.root.addLayout(led_block)
        panel.root.addStretch(1)

        return panel

    def _build_slider_block(
        self,
        title: str,
        unit: str,
        minimum: int,
        maximum: int,
        initial: int,
        callback,
        display_seconds: bool = False,
        editable_max: bool = False,
    ) -> Tuple[QVBoxLayout, QSlider, QLabel]:
        block = QVBoxLayout()
        block.setSpacing(px(6))

        def _fmt(ms_value: int) -> str:
            if display_seconds:
                return f"{ms_value / 1000:.1f}"
            return str(ms_value)

        top = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size:{px(14)}px; font-weight:800; color:#2a2d30;")
        value_lbl = QLabel(_fmt(initial))
        value_lbl.setStyleSheet(f"font-size:{px(34)}px; font-weight:900; color:#0a4888;")
        unit_lbl = QLabel(unit)
        unit_lbl.setStyleSheet(f"font-size:{px(12)}px; color:#2a3848;")

        unit_wrap = QVBoxLayout()
        unit_wrap.addWidget(value_lbl, alignment=Qt.AlignRight)
        unit_wrap.addWidget(unit_lbl, alignment=Qt.AlignRight)
        top.addWidget(title_lbl)
        top.addStretch(1)
        top.addLayout(unit_wrap)
        block.addLayout(top)

        middle = QHBoxLayout()
        minus_btn = QPushButton("−")
        plus_btn = QPushButton("+")
        minus_btn.setFixedSize(px(34), px(34))
        plus_btn.setFixedSize(px(34), px(34))
        minus_btn.setStyleSheet(
            f"""
            QPushButton {{
                background:#eff6ff;
                color:#1e40af;
                border:1px solid #93c5fd;
                border-radius:{px(8)}px;
                font-size:{px(18)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#dbeafe; }}
            """
        )
        plus_btn.setStyleSheet(
            f"""
            QPushButton {{
                background:#eff6ff;
                color:#1e40af;
                border:1px solid #93c5fd;
                border-radius:{px(8)}px;
                font-size:{px(18)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#dbeafe; }}
            """
        )

        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(initial)
        slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                height:{px(6)}px;
                background:#cbd5e1;
                border-radius:{px(3)}px;
            }}
            QSlider::sub-page:horizontal {{
                background:#3b82f6;
                border-radius:{px(3)}px;
            }}
            QSlider::handle:horizontal {{
                width:{px(18)}px;
                height:{px(18)}px;
                margin:-{px(6)}px 0;
                background:#ffffff;
                border:2px solid #3b82f6;
                border-radius:{px(9)}px;
            }}
            """
        )
        slider.valueChanged.connect(lambda value: value_lbl.setText(_fmt(value)))
        slider.valueChanged.connect(callback)

        step = 100 if display_seconds else max(1, (maximum - minimum) // 100)
        minus_btn.clicked.connect(lambda: slider.setValue(max(slider.minimum(), slider.value() - step)))
        plus_btn.clicked.connect(lambda: slider.setValue(min(slider.maximum(), slider.value() + step)))

        middle.addWidget(minus_btn)
        middle.addWidget(slider, 1)
        middle.addWidget(plus_btn)
        block.addLayout(middle)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(px(2), px(2), px(2), 0)
        min_display = f"{minimum / 1000:.1f}" if display_seconds else str(minimum)
        max_display = f"{maximum / 1000:.1f}" if display_seconds else str(maximum)

        _range_lbl_style = (
            f"font-size:{px(13)}px; font-weight:700; color:#4a6070;"
        )
        min_lbl = QLabel(min_display)
        min_lbl.setStyleSheet(_range_lbl_style)
        bottom.addWidget(min_lbl)
        bottom.addStretch(1)

        if editable_max:
            max_edit = QLineEdit(max_display)
            max_edit.setFixedWidth(px(60))
            max_edit.setAlignment(Qt.AlignRight)
            max_edit.setToolTip("Click to change the upper limit")
            max_edit.setStyleSheet(
                f"""
                QLineEdit {{
                    font-size:{px(13)}px;
                    font-weight:700;
                    color:#1e40af;
                    background:#eff6ff;
                    border:1px solid #93c5fd;
                    border-radius:{px(4)}px;
                    padding:0 {px(6)}px;
                    min-height:{px(22)}px;
                }}
                """
            )

            def _apply_new_max() -> None:
                try:
                    new_sec = float(max_edit.text())
                    new_max_ms = max(int(slider.minimum()) + 1, int(new_sec * 1000))
                except ValueError:
                    max_edit.setText(f"{slider.maximum() / 1000:.1f}")
                    return
                slider.setMaximum(new_max_ms)
                max_edit.setText(f"{new_max_ms / 1000:.1f}")
                if slider.value() > new_max_ms:
                    slider.setValue(new_max_ms)

            max_edit.editingFinished.connect(_apply_new_max)
            bottom.addWidget(max_edit)
        else:
            max_lbl = QLabel(max_display)
            max_lbl.setStyleSheet(_range_lbl_style)
            bottom.addWidget(max_lbl)

        block.addLayout(bottom)

        self.dlp_controls.extend([slider, minus_btn, plus_btn])
        return block, slider, value_lbl

    def _build_event_log_panel(self) -> Panel:
        panel = Panel("EVENT LOG & ALERTS")
        panel.setMinimumHeight(px(320))

        save_log_btn = QPushButton("Save Log Data")
        save_log_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(26)}px;
                padding:0 {px(10)}px;
                border-radius:{px(6)}px;
                border:1px solid #3b82f6;
                background:#eff6ff;
                color:#1e40af;
                font-size:{px(12)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#dbeafe; }}
            """
        )
        save_log_btn.clicked.connect(lambda: self._prompt_save_log(warn_if_empty=True))
        panel.title_row.addWidget(save_log_btn)

        self.event_log_scroll = QScrollArea()
        self.event_log_scroll.setWidgetResizable(True)
        self.event_log_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        self.event_log_content = QWidget()
        self.event_log_layout = QVBoxLayout(self.event_log_content)
        self.event_log_layout.setContentsMargins(0, 0, 0, 0)
        self.event_log_layout.setSpacing(px(8))
        self.event_log_layout.setAlignment(Qt.AlignTop)

        self.event_log_scroll.setWidget(self.event_log_content)
        panel.root.addWidget(self.event_log_scroll, 1)
        return panel

    def _reset_visual_state(self) -> None:
        self._update_sequence_active_row()
        self._update_current_base_display(BASES[0])
        self.current_synthesis_panel.set_title("CURRENT SYNTHESIS - POSITION 1")
        self.stage_label.setText("Stage 1: Ready")
        self.percent_circle.set_percent(0)
        self.progress_text.setText("READY")
        self.elapsed_box.set_value("00:00:00")
        self.remaining_box.set_value("00:00:00")
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)

    def _seed_sequence_overview_preview(self) -> None:
        if not self.sequence_rows:
            return
        for row in self.sequence_rows.values():
            row.reset()
        for seq_no, row in self.sequence_rows.items():
            row.set_active(seq_no == self.sequence_index)

    def _update_current_base_display(self, base: str) -> None:
        self.current_base = base
        self.big_base_circle.set_base(base)
        self.big_base_circle.set_active(self.is_running or self.hold_infinite, self._blink_state)
        for key, chip in self.base_chips.items():
            chip.set_selected(key == base)
        self._update_pattern_label()

    def _update_pattern_label(self) -> None:
        if not self.pattern_folder_path:
            self.pattern_label.setText("Pattern folder not loaded")
            return
        self.pattern_label.setText(f"Pattern: Pos{self.current_sequence}_{self.current_base}.png")

    def _on_base_chip_clicked(self, base: str) -> None:
        if self.is_running:
            return
        self.base_index = BASES.index(base)
        self._update_current_base_display(base)

    def _set_dlp_controls_enabled(self, enabled: bool) -> None:
        for widget in self.dlp_controls:
            widget.setEnabled(enabled)

    def _update_sequence_active_row(self) -> None:
        active_seq = self.sequence_index if 1 <= self.sequence_index <= TOTAL_SEQUENCES else -1
        for seq_no, row in self.sequence_rows.items():
            row.set_active(seq_no == active_seq)

    def _update_current_dot(self, blink_on: bool = True) -> None:
        self.big_base_circle.set_active(self.is_running or self.hold_infinite, blink_on)
        self._update_big_base_progress()
        for seq_no, row in self.sequence_rows.items():
            if seq_no == self.sequence_index and self.is_running:
                row.set_current_base(self.base_index, blink_on)
            else:
                row.clear_current_base()

    def _on_blink_tick(self) -> None:
        self._blink_state = not self._blink_state
        self._update_current_dot(self._blink_state)

    def _update_big_base_progress(self) -> None:
        if not (self.is_running or self.hold_infinite):
            self.big_base_circle.set_progress(0)
            return

        if self.hold_infinite:
            self.big_base_circle.set_progress(100)
            return

        if self.current_step_duration_ms <= 0 or not self.step_timer.isActive():
            self.big_base_circle.set_progress(100 if self.is_running else 0)
            return

        remaining_ms = max(0, self.step_timer.remainingTime())
        elapsed_ms = max(0, self.current_step_duration_ms - remaining_ms)
        percent = int((elapsed_ms / self.current_step_duration_ms) * 100)
        self.big_base_circle.set_progress(percent)

    def _clear_event_log_ui(self) -> None:
        while self.event_log_layout.count():
            item = self.event_log_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_event_line(self, command_text: str) -> None:
        time_text = datetime.now().strftime("%H:%M:%S")
        line = EventLine(time_text, command_text)
        self.event_log_layout.addWidget(line)
        self.event_log_lines.append(f"[{time_text}] {command_text}")
        self.log_dirty = True
        QTimer.singleShot(
            0,
            lambda: self.event_log_scroll.verticalScrollBar().setValue(
                self.event_log_scroll.verticalScrollBar().maximum()
            ),
        )

    def _prompt_save_log(self, warn_if_empty: bool = False) -> None:
        if not self.event_log_lines:
            if warn_if_empty:
                QMessageBox.information(self, "Save Log", "No log entries to save.")
            return
        default_name = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Log Data", default_name, "Text files (*.txt);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(self.event_log_lines) + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "Save Log", f"Failed to save log:\n{exc}")
            return
        self.log_dirty = False

    def pick_pattern_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Pattern Folder")
        if not path:
            return
        self.pattern_folder_path = path
        self.pattern_folder_edit.setText(path)
        self._update_pattern_label()
        self._log_pattern_folder_status()

    def _expected_pattern_names(self) -> List[str]:
        return [
            f"Pos{sequence_no}_{base}.png"
            for sequence_no in range(1, TOTAL_SEQUENCES + 1)
            for base in BASES
        ]

    def _missing_pattern_names(self) -> List[str]:
        if not self.pattern_folder_path:
            return []
        return [
            name
            for name in self._expected_pattern_names()
            if not os.path.exists(os.path.join(self.pattern_folder_path, name))
        ]

    def _log_pattern_folder_status(self) -> None:
        if not self.pattern_folder_path:
            self.add_event_line("ALERT Pattern folder is not selected")
            return

        expected_count = TOTAL_SEQUENCES * len(BASES)
        missing = self._missing_pattern_names()
        found_count = expected_count - len(missing)
        self.add_event_line(f"Pattern folder check: {found_count}/{expected_count} files found")
        if missing:
            preview = ", ".join(missing[:8])
            suffix = f" ... +{len(missing) - 8} more" if len(missing) > 8 else ""
            self.add_event_line(f"ALERT Missing pattern files: {preview}{suffix}")

    def open_dlp_dialog(self) -> None:
        dialog = DlpDialog(self)
        dialog.exec()

    def open_recipe_setup_dialog(self) -> None:
        if self.is_running:
            QMessageBox.information(
                self,
                "Process Running",
                "Recipe editing is disabled while synthesis is running.",
            )
            return

        dialog = RecipeSetupDialog(
            recipe=self.recipe,
            reagent_slots=self.reagent_slots,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.recipe = dialog.get_recipe()
            self.reagent_slots = dialog.get_reagent_slots()
            self.add_event_line(f"Recipe applied: {self.recipe.name}")

    def _reset_for_new_run(self) -> None:
        self._clear_event_log_ui()
        self.event_log_lines.clear()
        self.log_dirty = False

        for row in self.sequence_rows.values():
            row.reset()

        self.current_stage = "pre"
        self.current_step_index = 0
        self.sequence_index = 1
        self.base_index = 0
        self.current_sequence = 1
        self.current_base = BASES[0]
        self.completed_bases = 0
        self.hold_infinite = False
        self.elapsed_seconds = 0
        self.run_started_monotonic = 0.0
        self.current_step_duration_ms = 0

        self.percent_circle.set_percent(0)
        self.big_base_circle.set_progress(0)
        self.elapsed_box.set_value("00:00:00")
        self.remaining_box.set_value("00:00:00")
        self.stage_label.setText("Stage 1: Starting")
        self._update_current_base_display(BASES[0])
        self._update_sequence_active_row()

    def start_process(self) -> None:
        if not self.pattern_folder_path:
            self.add_event_line("ALERT Pattern folder is not selected. Load pattern folder before Start.")
            self.progress_text.setText("PATTERN FOLDER REQUIRED")
            return

        self._reset_for_new_run()

        missing = self._missing_pattern_names()
        if missing:
            preview = ", ".join(missing[:8])
            suffix = f" ... +{len(missing) - 8} more" if len(missing) > 8 else ""
            self.add_event_line(f"ALERT Missing pattern files before start: {preview}{suffix}")

        self.is_running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.recipe_setup_btn.setEnabled(False)
        self._set_dlp_controls_enabled(False)

        self.run_started_monotonic = time.monotonic()
        self.metrics_timer.start()
        self.progress_timer.start()
        self._blink_state = True
        self.blink_timer.start()
        self.add_event_line(">>> SYNTHESIS STARTED")
        self._update_progress_text_running()
        self._execute_next_step()

    def pause_process(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        self.hold_infinite = False
        self.step_timer.stop()
        self.metrics_timer.stop()
        self.progress_timer.stop()
        self.blink_timer.stop()
        self.big_base_circle.set_active(False)
        self.big_base_circle.set_progress(0)
        self.current_step_duration_ms = 0
        self.elapsed_seconds = int(max(0.0, time.monotonic() - self.run_started_monotonic))

        for row in self.sequence_rows.values():
            row.clear_current_base()

        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.recipe_setup_btn.setEnabled(True)
        self._set_dlp_controls_enabled(True)
        self.progress_text.setText(
            f"PAUSED - Position {min(self.sequence_index, TOTAL_SEQUENCES)}/{TOTAL_SEQUENCES}"
        )
        self.add_event_line(">>> PAUSED")

    def stop_process(self) -> None:
        if not (self.is_running or self.hold_infinite or self.step_timer.isActive() or self.log_dirty):
            return

        self.is_running = False
        self.hold_infinite = False
        self.step_timer.stop()
        self.metrics_timer.stop()
        self.progress_timer.stop()
        self.blink_timer.stop()
        self.big_base_circle.set_active(False)
        self.big_base_circle.set_progress(0)
        self.current_step_duration_ms = 0

        for row in self.sequence_rows.values():
            row.clear_current_base()

        if self.run_started_monotonic > 0:
            self.elapsed_seconds = int(max(0.0, time.monotonic() - self.run_started_monotonic))
        self.elapsed_box.set_value(self._format_hms(self.elapsed_seconds))

        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.recipe_setup_btn.setEnabled(True)
        self._set_dlp_controls_enabled(True)
        self.progress_text.setText("STOPPED")

        self.add_event_line(">>> STOPPED")
        self._prompt_save_log()

    def _finish_process(self) -> None:
        self.is_running = False
        self.hold_infinite = False
        self.step_timer.stop()
        self.metrics_timer.stop()
        self.progress_timer.stop()
        self.blink_timer.stop()
        self.big_base_circle.set_active(False)
        self.big_base_circle.set_progress(100)
        self.current_step_duration_ms = 0

        for row in self.sequence_rows.values():
            row.clear_current_base()

        if self.run_started_monotonic > 0:
            self.elapsed_seconds = int(max(0.0, time.monotonic() - self.run_started_monotonic))
        self.elapsed_box.set_value(self._format_hms(self.elapsed_seconds))

        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.recipe_setup_btn.setEnabled(True)
        self._set_dlp_controls_enabled(True)
        self.current_synthesis_panel.set_title("CURRENT SYNTHESIS - COMPLETED")
        self.stage_label.setText("Synthesis completed")
        self.pattern_label.setText("Pattern: complete")
        self.remaining_box.set_value("00:00:00")
        self.percent_circle.set_percent(100)
        self.progress_text.setText("SYNTHESIS COMPLETED")

        self.add_event_line(">>> SYNTHESIS COMPLETED")
        self._prompt_save_log()

    def _update_progress_text_running(self) -> None:
        self.progress_text.setText(
            f"SYNTHESIS IN PROGRESS - Position {min(self.sequence_index, TOTAL_SEQUENCES)}/{TOTAL_SEQUENCES}"
        )

    def _resolve_step_duration_seconds(self, step: StepItem, base: Optional[str] = None) -> Optional[int]:
        if is_pattern_action(step.action) and step.time_sec.strip().upper() == DLP_TIME_MARKER:
            effective_base = base if base is not None else self.current_base
            base_ms = self.recipe.pattern_base_times.get(effective_base, 3500)
            return max(1, math.ceil(base_ms / 1000.0))

        seconds = CommandGenerator.parse_time_to_seconds(step.time_sec, 0)
        if seconds is None:
            if is_incubation_action(step.action):
                return None
            return 0
        return max(0, seconds)

    def _execute_next_step(self) -> None:
        while self.is_running:
            if self.current_stage == "pre":
                steps = self.recipe.pre_processing
                if self.current_step_index >= len(steps):
                    self.current_stage = "cycle"
                    self.current_step_index = 0
                    continue
                step = steps[self.current_step_index]
                self._execute_step(step, stage_no=1)
                return

            if self.current_stage == "cycle":
                if self.sequence_index > TOTAL_SEQUENCES:
                    self.current_stage = "post"
                    self.current_step_index = 0
                    continue

                cycle_steps = self.recipe.cyclic_reaction
                if self.current_step_index >= len(cycle_steps):
                    self._complete_cycle_base()
                    self.current_step_index = 0
                    continue

                step = cycle_steps[self.current_step_index]
                self._execute_step(step, stage_no=2)
                return

            if self.current_stage == "post":
                steps = self.recipe.post_processing
                if self.current_step_index >= len(steps):
                    self._finish_process()
                    return
                step = steps[self.current_step_index]
                self._execute_step(step, stage_no=3)
                return

            return

    def _execute_step(self, step: StepItem, stage_no: int) -> None:
        if stage_no == 2:
            self.current_sequence = self.sequence_index
            self.current_base = BASES[self.base_index]
            self._update_sequence_active_row()
            self._update_current_dot(self._blink_state)
            self.current_synthesis_panel.set_title(
                f"CURRENT SYNTHESIS - POSITION {self.current_sequence}"
            )
        elif stage_no == 1:
            self.current_synthesis_panel.set_title("CURRENT SYNTHESIS - PRE-PROCESSING")
        elif stage_no == 3:
            self.current_synthesis_panel.set_title("CURRENT SYNTHESIS - POST-PROCESSING")

        self._update_current_base_display(self.current_base)

        action_label = step.action
        if stage_no == 2 and is_pattern_action(step.action):
            action_label = f"Pattern Base {self.current_base}"
        elif is_phosphoramidite_group_action(step.action):
            action_label = f"Phosphoramidite {self.current_base}"
        self.stage_label.setText(f"Stage {stage_no}: Step {step.step_no}, {action_label}")
        self._update_pattern_label()

        if stage_no == 2 and is_pattern_action(step.action):
            pattern_name = f"Pos{self.current_sequence}_{self.current_base}.png"
            if self.pattern_folder_path:
                file_path = os.path.join(self.pattern_folder_path, pattern_name)
                if not os.path.exists(file_path):
                    self.add_event_line(f"ALERT Missing pattern file: {pattern_name}")

        phosphoramidite_slot_no = (
            self.base_index + 1 if is_phosphoramidite_group_action(step.action) else None
        )
        command = CommandGenerator.generate(
            step,
            self.recipe.pattern_base_times.get(self.current_base, 3500),
            phosphoramidite_slot_no=phosphoramidite_slot_no,
        )
        self.add_event_line(command)

        duration_seconds = self._resolve_step_duration_seconds(step)
        if duration_seconds is None:
            self.hold_infinite = True
            self.current_step_duration_ms = 0
            self.big_base_circle.set_active(True, self._blink_state)
            self.big_base_circle.set_progress(100)
            self.progress_text.setText("SYNTHESIS HOLD - Infinite Incubation (press STOP)")
            self.remaining_box.set_value(INFINITE_TIME_MARKER)
            return

        self.hold_infinite = False
        self.current_step_duration_ms = max(1, int(duration_seconds * 1000))
        self.big_base_circle.set_active(self.is_running, self._blink_state)
        self.big_base_circle.set_progress(0)
        self.step_timer.start(self.current_step_duration_ms)
        self._update_big_base_progress()
        self._update_progress_text_running()
        self._update_time_metrics()

    def _on_step_timeout(self) -> None:
        if not self.is_running or self.hold_infinite:
            return
        self.current_step_index += 1
        self._execute_next_step()

    def _complete_cycle_base(self) -> None:
        row = self.sequence_rows.get(self.sequence_index)
        if row is not None:
            row.clear_current_base()
            row.set_base_complete(self.base_index, True)
            if self.base_index == len(BASES) - 1:
                row.set_fully_completed(True)

        self.completed_bases += 1
        total_bases = TOTAL_SEQUENCES * len(BASES)
        percent = int((self.completed_bases / total_bases) * 100)
        self.percent_circle.set_percent(percent)

        if self.base_index < len(BASES) - 1:
            self.base_index += 1
        else:
            self.base_index = 0
            self.sequence_index += 1

        self.current_sequence = min(self.sequence_index, TOTAL_SEQUENCES)
        self.current_base = BASES[self.base_index]
        self._update_sequence_active_row()
        self._update_current_base_display(self.current_base)

    def _current_step_for_estimate(self) -> Optional[StepItem]:
        if self.current_stage == "pre":
            steps = self.recipe.pre_processing
        elif self.current_stage == "cycle":
            steps = self.recipe.cyclic_reaction
        elif self.current_stage == "post":
            steps = self.recipe.post_processing
        else:
            return None

        if 0 <= self.current_step_index < len(steps):
            return steps[self.current_step_index]
        return None

    def _estimate_remaining_seconds(self) -> Optional[int]:
        if self.hold_infinite:
            return None
        if self.current_stage == "idle":
            return 0

        current_step = self._current_step_for_estimate()
        if current_step is None:
            return 0

        current_duration = self._resolve_step_duration_seconds(current_step)
        if current_duration is None:
            return None

        if self.step_timer.isActive():
            total = max(0, math.ceil(self.step_timer.remainingTime() / 1000.0))
        else:
            total = current_duration

        stage = self.current_stage
        step_idx = self.current_step_index + 1
        seq_idx = self.sequence_index
        base_idx = self.base_index

        while True:
            if stage == "pre":
                steps = self.recipe.pre_processing
                if step_idx >= len(steps):
                    stage = "cycle"
                    step_idx = 0
                    continue
                for step in steps[step_idx:]:
                    duration = self._resolve_step_duration_seconds(step)
                    if duration is None:
                        return None
                    total += duration
                stage = "cycle"
                step_idx = 0
                continue

            if stage == "cycle":
                if seq_idx > TOTAL_SEQUENCES:
                    stage = "post"
                    step_idx = 0
                    continue

                cycle_steps = self.recipe.cyclic_reaction
                if not cycle_steps:
                    if base_idx < len(BASES) - 1:
                        base_idx += 1
                    else:
                        base_idx = 0
                        seq_idx += 1
                    continue

                if step_idx < len(cycle_steps):
                    for step in cycle_steps[step_idx:]:
                        duration = self._resolve_step_duration_seconds(step, BASES[base_idx])
                        if duration is None:
                            return None
                        total += duration

                if base_idx < len(BASES) - 1:
                    base_idx += 1
                else:
                    base_idx = 0
                    seq_idx += 1
                step_idx = 0
                continue

            if stage == "post":
                steps = self.recipe.post_processing
                if step_idx >= len(steps):
                    break
                for step in steps[step_idx:]:
                    duration = self._resolve_step_duration_seconds(step)
                    if duration is None:
                        return None
                    total += duration
                break

            break

        return max(0, int(total))

    def _format_hms(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        hh = seconds // 3600
        mm = (seconds % 3600) // 60
        ss = seconds % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def _update_time_metrics(self) -> None:
        if self.run_started_monotonic > 0 and (self.is_running or self.hold_infinite):
            self.elapsed_seconds = int(max(0.0, time.monotonic() - self.run_started_monotonic))

        self.elapsed_box.set_value(self._format_hms(self.elapsed_seconds))
        remaining = self._estimate_remaining_seconds()
        if remaining is None:
            self.remaining_box.set_value(INFINITE_TIME_MARKER)
        else:
            self.remaining_box.set_value(self._format_hms(remaining))
        self._update_big_base_progress()

    def closeEvent(self, event) -> None:  # noqa: D401
        self.is_running = False
        self.hold_infinite = False
        self.step_timer.stop()
        self.metrics_timer.stop()
        if self.log_dirty and self.event_log_lines:
            self._prompt_save_log()
        event.accept()
