"""Base visual widgets: BaseDot, BigBaseCircle, BaseChip, CircleProgress."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from app.constants import px


class BaseDot(QLabel):
    def __init__(self, filled: bool = False, parent=None):
        super().__init__(parent)
        self._filled = filled
        self._is_current = False
        self._blink_on = True
        size = px(24)
        self.setFixedSize(size, size)
        self._refresh_style()

    def set_filled(self, filled: bool) -> None:
        """Faqat bajarilganlik holatini o'zgartirish."""
        self._filled = filled
        self._refresh_style()

    def set_current(self, is_current: bool, blink_on: bool = True) -> None:
        """Jarayon davomida miltillovchi indikator."""
        self._is_current = is_current
        self._blink_on = blink_on
        self._refresh_style()

    def _refresh_style(self) -> None:
        """Hozirgi holatga qarab CSS uslubini qo'llash."""
        radius = self.width() // 2

        if self._is_current:
            bg = "#1a1a1a" if self._blink_on else "#888888"
            border = "#000000" if self._blink_on else "#555555"
        elif self._filled:
            bg = "#63c27d"
            border = "#5ab171"
        else:
            bg = "#ffffff"
            border = "#cdd6df"

        self.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            """
        )


class CircleProgress(QFrame):
    """Circular percent progress widget drawn with QPainter."""

    def __init__(self, percent: int = 0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._percent = max(0, min(100, percent))
        self.setFixedSize(px(68), px(68))
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_percent(self, value: int) -> None:
        self._percent = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401
        del event
        size = min(self.width(), self.height())
        pen_w = px(6)
        margin = pen_w // 2 + px(2)
        rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e7f0f6"))
        painter.drawEllipse(QRectF(0, 0, size, size))

        bg_pen = QPen(QColor("#d0dce6"), pen_w)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, 0, 360 * 16)

        fg_pen = QPen(QColor("#5b9ac7"), pen_w)
        fg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(fg_pen)
        span = int((self._percent / 100.0) * 360 * 16)
        painter.drawArc(rect, 90 * 16, -span)

        font = QFont()
        font.setBold(False)
        font.setPixelSize(px(15))
        painter.setFont(font)
        painter.setPen(QColor("#232b33"))
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, f"{self._percent}%")
        painter.end()


class BigBaseCircle(QFrame):
    """Large circular widget displaying the current base letter."""

    def __init__(self, base: str = "A", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._base = base
        self._active = False
        self._blink_on = True
        self._progress_percent = 0
        self.setFixedSize(px(108), px(108))
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_base(self, base: str) -> None:
        self._base = base
        self.update()

    def set_active(self, active: bool, blink_on: bool = True) -> None:
        self._active = active
        self._blink_on = blink_on
        self.update()

    def set_progress(self, percent: int) -> None:
        self._progress_percent = max(0, min(100, int(percent)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401
        del event
        size = min(self.width(), self.height())
        pen_w = px(8)
        margin = pen_w // 2 + px(3)
        rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#d7edf7" if self._active else "#edf4f8"))
        painter.drawEllipse(QRectF(0, 0, size, size))

        bg_pen = QPen(QColor("#b4d2e3"), pen_w)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, 0, 360 * 16)

        if self._active and self._progress_percent > 0:
            active_color = "#147eb3" if self._blink_on else "#4fa3cf"
            fg_pen = QPen(QColor(active_color), pen_w)
            fg_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(fg_pen)
            span = int((self._progress_percent / 100.0) * 360 * 16)
            painter.drawArc(rect, 90 * 16, -span)

        font = QFont()
        font.setBold(True)
        font.setPixelSize(px(38))
        painter.setFont(font)
        painter.setPen(QColor("#195f86" if self._active else "#456f8d"))
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, self._base)
        painter.end()


class BaseChip(QPushButton):
    """Clickable base chip for A/T/C/G selection."""

    def __init__(self, base: str, selected: bool = False, parent: Optional[QWidget] = None):
        super().__init__(base, parent)
        self.base = base
        self.setFixedSize(px(34), px(34))
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        if selected:
            bg = "#3f8fbd"
            fg = "#ffffff"
            border = "#347fa9"
        else:
            bg = "#ffffff"
            fg = "#3f4650"
            border = "#c9d5de"
        self.setStyleSheet(
            f"""
            QPushButton {{
                background:{bg};
                color:{fg};
                border:1px solid {border};
                border-radius:{px(17)}px;
                font-size:{px(15)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ border-color:#3f8fbd; }}
            """
        )
