"""SequenceRow widget showing one DNA sequence with base progress dots."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.command_helpers import resource_path

from app.app_settings import BASES, px
from app.widgets.base_display_widgets import BaseDot


class SequenceRow(QFrame):
    def __init__(self, seq_no: int, active: bool = False, parent=None):
        super().__init__(parent)
        self.seq_no = seq_no
        self.active = active
        self._fully_completed = False
        self._dots = {}
        self._build_ui()
        self.set_active(active)

    def _build_ui(self):
        self.setObjectName("sequenceRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(px(12), px(10), px(12), px(10))
        layout.setSpacing(px(10))

        seq_label = QLabel(f"{self.seq_no:02d}")
        seq_label.setFixedSize(px(40), px(40))
        seq_label.setAlignment(Qt.AlignCenter)
        seq_label.setStyleSheet(f"font-size:{px(22)}px; font-weight:700; color:#1e2e3e; background:transparent; border:none;")
        layout.addWidget(seq_label)

        dna_label = QLabel()
        _icon_size = px(42)
        dna_label.setFixedSize(_icon_size, _icon_size)
        dna_label.setAlignment(Qt.AlignCenter)
        dna_label.setStyleSheet("background:transparent; border:none;")
        _pix = QPixmap(resource_path("DNK.png"))
        dna_label.setPixmap(_pix.scaled(_icon_size, _icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(dna_label)

        dots_wrap = QHBoxLayout()
        dots_wrap.setSpacing(px(8))
        for base in BASES:
            dot = BaseDot(False)
            dot.setToolTip(base)
            self._dots[base] = dot
            dots_wrap.addWidget(dot)
        layout.addLayout(dots_wrap)

    def set_active(self, active: bool):
        self.active = active
        self._refresh_row_style()

    def _refresh_row_style(self):
        if self._fully_completed:
            row_color = "#a8c8b0"
        elif self.active:
            row_color = "#b8d0e0"
        else:
            row_color = "#c5d8e5"
        border_color = "#3878b5" if self.active else "#8aafc8"
        self.setStyleSheet(f"""
            QFrame#sequenceRow {{
                background: {row_color};
                border: 1px solid {border_color};
                border-radius: {px(10)}px;
            }}
        """)

    def set_fully_completed(self, completed: bool) -> None:
        self._fully_completed = completed
        self._refresh_row_style()

    def set_current_base(self, base_index: Optional[int], blink_on: bool = True) -> None:
        for idx, base in enumerate(BASES):
            dot = self._dots[base]
            if idx == base_index:
                dot.set_current(True, blink_on)
            else:
                dot.set_current(False)

    def clear_current_base(self) -> None:
        for dot in self._dots.values():
            dot.set_current(False)

    def set_base_complete(self, base_index: int, completed: bool = True) -> None:
        if 0 <= base_index < len(BASES):
            dot = self._dots[BASES[base_index]]
            dot.set_filled(completed)
            dot.set_current(False)

    def set_progress(self, count: int) -> None:
        for idx, base in enumerate(BASES):
            self._dots[base].set_filled(idx < count)

    def reset(self) -> None:
        self._fully_completed = False
        self._refresh_row_style()
        for base in BASES:
            self._dots[base].set_filled(False)
