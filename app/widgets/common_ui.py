"""Primitive widget components: Panel, MiniMetricBox, ControlButton, EventLine."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.app_settings import px


class Panel(QFrame):
    """Shared rounded panel container with title."""

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QFrame {{
                background:#ffffff;
                border:1px solid #d0dde8;
                border-radius:{px(14)}px;
            }}
            """
        )
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(px(18), px(16), px(18), px(16))
        self.root.setSpacing(px(12))

        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(px(8))
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"font-size:{px(16)}px; font-weight:800; color:#1a2a38; border:none;"
        )
        self.title_row.addWidget(self.title_label)
        self.title_row.addStretch()
        self.root.addLayout(self.title_row)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)


class MiniMetricBox(QFrame):
    """Compact metric card for elapsed/remaining time."""

    def __init__(self, title: str, value: str, subtitle: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QFrame {{
                background:#f0f6fb;
                border:1px solid #c8d8e8;
                border-radius:{px(12)}px;
            }}
            QLabel {{ border:none; }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(14), px(12), px(14), px(10))
        layout.setSpacing(px(4))

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size:{px(12)}px; font-weight:700; color:#283848;"
        )
        layout.addWidget(title_label)

        self.value_label = QLabel(value)
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setStyleSheet(
            f"font-size:{px(28)}px; font-weight:800; color:#1858a0;"
        )
        layout.addWidget(self.value_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(f"font-size:{px(11)}px; color:#6e7781;")
        layout.addWidget(subtitle_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ControlButton(QPushButton):
    """Main control button with primary/secondary visual variants."""

    def __init__(self, text: str, primary: bool = False, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        if primary:
            self.setStyleSheet(
                f"""
                QPushButton {{
                    min-height:{px(36)}px;
                    min-width:{px(94)}px;
                    padding:0 {px(16)}px;
                    border-radius:{px(8)}px;
                    border:1px solid #1d4ed8;
                    background:#2563eb;
                    color:white;
                    font-size:{px(14)}px;
                    font-weight:700;
                }}
                QPushButton:hover {{ background:#1d4ed8; }}
                QPushButton:disabled {{
                    background:#93c5fd;
                    border:1px solid #60a5fa;
                    color:#dbeafe;
                }}
                """
            )
        else:
            self.setStyleSheet(
                f"""
                QPushButton {{
                    min-height:{px(36)}px;
                    min-width:{px(94)}px;
                    padding:0 {px(16)}px;
                    border-radius:{px(8)}px;
                    border:1px solid #93c5fd;
                    background:#e8f2f8;
                    color:#1e40af;
                    font-size:{px(14)}px;
                    font-weight:700;
                }}
                QPushButton:hover {{ background:#dbeafe; }}
                QPushButton:disabled {{
                    background:#ccd8e4;
                    border:1px solid #aabccc;
                    color:#7090a8;
                }}
                """
            )


class EventLine(QFrame):
    """Single line in the event log area."""

    def __init__(self, time_text: str, command_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ border:none; border-bottom:1px solid #e2eaf2; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, px(4), 0, px(8))
        layout.setSpacing(px(2))

        time_lbl = QLabel(time_text)
        time_lbl.setStyleSheet(f"font-size:{px(11)}px; font-weight:700; color:#6b7280; border:none;")
        layout.addWidget(time_lbl)

        cmd_lbl = QLabel(command_text)
        cmd_lbl.setWordWrap(True)
        cmd_lbl.setStyleSheet(f"font-size:{px(12)}px; color:#1e293b; border:none;")
        layout.addWidget(cmd_lbl)
