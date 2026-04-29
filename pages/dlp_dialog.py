"""Sahifa 1: DLP optical test dialog."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.constants import LED_MAX, LED_MIN, px
from app.widgets.primitives import Panel


class ProjectionPreviewFrame(QFrame):
    """Projection preview area with a bracket/grid style background."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setMinimumSize(px(420), px(260))
        self.setStyleSheet("background:#c8dceb; border:1px solid #7fa1b8; border-radius:8px;")

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(px(10), px(10), -px(10), -px(10))
        painter.fillRect(rect, QColor("#d5e5f2"))

        grid_pen = QPen(QColor("#aac3d4"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        step = px(24)
        x = rect.left()
        while x <= rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += step
        y = rect.top()
        while y <= rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += step

        bracket_pen = QPen(QColor("#37678d"))
        bracket_pen.setWidth(px(3))
        painter.setPen(bracket_pen)
        bracket = px(24)

        painter.drawLine(rect.left(), rect.top(), rect.left() + bracket, rect.top())
        painter.drawLine(rect.left(), rect.top(), rect.left(), rect.top() + bracket)
        painter.drawLine(rect.right() - bracket, rect.top(), rect.right(), rect.top())
        painter.drawLine(rect.right(), rect.top(), rect.right(), rect.top() + bracket)
        painter.drawLine(rect.left(), rect.bottom() - bracket, rect.left(), rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.left() + bracket, rect.bottom())
        painter.drawLine(rect.right(), rect.bottom() - bracket, rect.right(), rect.bottom())
        painter.drawLine(rect.right() - bracket, rect.bottom(), rect.right(), rect.bottom())

        if self._pixmap and not self._pixmap.isNull():
            target = rect.adjusted(px(18), px(18), -px(18), -px(18))
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x_pos = target.left() + (target.width() - scaled.width()) // 2
            y_pos = target.top() + (target.height() - scaled.height()) // 2
            painter.drawPixmap(x_pos, y_pos, scaled)
        else:
            painter.setPen(QColor("#3e5972"))
            painter.drawText(rect, Qt.AlignCenter, "Projection Preview")

        painter.end()


class DlpDialog(QDialog):
    """Independent DLP test dialog."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_pixmap: Optional[QPixmap] = None
        self._image_path = ""
        self.setWindowTitle("DLP Test")
        self._build_ui()
        self.setWindowState(Qt.WindowMaximized)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background:#a8c0d0; }
            QLabel { color:#101820; }
            QPushButton {
                min-height:34px;
                border-radius:6px;
                border:1px solid #4878a8;
                background:#c8dce8;
                padding:0 12px;
                font-weight:700;
            }
            QPushButton:hover { background:#b0cce0; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(px(18), px(16), px(18), px(16))
        root.setSpacing(px(12))

        title = QLabel("DLP Optics Test & Calibration")
        title.setStyleSheet(f"font-size:{px(22)}px; font-weight:800; color:#1e2a34;")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(px(14))
        root.addLayout(top, 1)

        left = Panel("DLP Image Load")
        select_btn = QPushButton("🖹 Select Test Image")
        select_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(38)}px;
                border-radius:{px(8)}px;
                background:#2878b5;
                color:#ffffff;
                border:1px solid #1868a5;
                font-size:{px(14)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#1868a5; }}
            """
        )
        select_btn.clicked.connect(self._select_test_image)
        left.root.addWidget(select_btn)

        self.file_name_label = QLabel("No image selected")
        self.file_name_label.setStyleSheet(f"font-size:{px(12)}px; color:#2a3848;")
        left.root.addWidget(self.file_name_label)

        self.image_preview = QLabel("Preview")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumHeight(px(280))
        self.image_preview.setStyleSheet(
            f"background:#2f3135; color:#7d8a95; border-radius:{px(8)}px; border:1px solid #364855;"
        )
        left.root.addWidget(self.image_preview, 1)

        top.addWidget(left, 2)

        right = Panel("Projection Output")
        self.projection_preview = ProjectionPreviewFrame()
        right.root.addWidget(self.projection_preview, 1)
        top.addWidget(right, 3)

        optics = Panel("Optics Control")
        optics.root.setSpacing(px(8))

        led_title = QLabel("LED Power")
        led_title.setStyleSheet(f"font-size:{px(13)}px; font-weight:700;")
        optics.root.addWidget(led_title)

        slider_row = QHBoxLayout()
        self.optics_slider = QSlider(Qt.Horizontal)
        self.optics_slider.setRange(LED_MIN, LED_MAX)
        self.optics_slider.setValue(45)
        self.optics_slider.setStyleSheet(
            """
            QSlider::groove:horizontal {
                height:6px; background:#6888a8; border-radius:3px;
            }
            QSlider::sub-page:horizontal {
                background:#2878b5; border-radius:3px;
            }
            QSlider::handle:horizontal {
                width:18px; height:18px; margin:-6px 0;
                background:#ddeaf5; border:2px solid #2878b5; border-radius:9px;
            }
            """
        )
        self.optics_slider.valueChanged.connect(self._on_optics_slider_changed)
        self.optics_value_label = QLabel("45%")
        self.optics_value_label.setStyleSheet(
            f"""
            background:#a8c0d8;
            border:1px solid #6080a8;
            border-radius:{px(6)}px;
            font-size:{px(12)}px;
            font-weight:700;
            color:#101828;
            """
        )
        self.optics_value_label.setFixedWidth(px(48))
        slider_row.addWidget(self.optics_slider, 1)
        slider_row.addWidget(self.optics_value_label)
        optics.root.addLayout(slider_row)

        buttons = QHBoxLayout()
        self.project_btn = QPushButton("Project Image")
        self.stop_project_btn = QPushButton("Stop Projection")
        self.project_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(36)}px;
                padding:0 {px(18)}px;
                border-radius:{px(8)}px;
                background:#d8b060;
                color:#5a2e00;
                border:1px solid #b08030;
                font-size:{px(14)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#c89840; }}
            """
        )
        self.stop_project_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(36)}px;
                padding:0 {px(18)}px;
                border-radius:{px(8)}px;
                background:#b0c8dc;
                color:#1a2a38;
                border:1px solid #6088a8;
                font-size:{px(14)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#98b8cc; }}
            """
        )
        self.save_image_btn = QPushButton("Save Image")
        self.save_image_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height:{px(36)}px;
                padding:0 {px(18)}px;
                border-radius:{px(8)}px;
                background:#2f7c4e;
                color:#ffffff;
                border:1px solid #1f5c38;
                font-size:{px(14)}px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#276840; }}
            """
        )
        self.project_btn.clicked.connect(self._project_image)
        self.stop_project_btn.clicked.connect(self._stop_projection)
        self.save_image_btn.clicked.connect(self._save_image)
        buttons.addWidget(self.project_btn)
        buttons.addWidget(self.stop_project_btn)
        buttons.addWidget(self.save_image_btn)
        buttons.addStretch(1)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f4960;")
        buttons.addWidget(self.status_label)
        optics.root.addLayout(buttons)

        root.addWidget(optics)

    def _select_test_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Test Image",
            "",
            "Images (*.png *.bmp *.jpg *.jpeg *.tif *.tiff);;All Files (*)",
        )
        if not path:
            return
        self._image_path = path
        self.file_name_label.setText(os.path.basename(path))
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_preview.setText("Failed to load image")
            self.projection_preview.set_pixmap(None)
            return
        self._current_pixmap = pixmap
        preview_scaled = pixmap.scaled(
            self.image_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.image_preview.setPixmap(preview_scaled)
        self.projection_preview.set_pixmap(pixmap)

    def resizeEvent(self, event) -> None:  # noqa: D401
        super().resizeEvent(event)
        if (
            hasattr(self, "image_preview")
            and self._current_pixmap
            and not self._current_pixmap.isNull()
        ):
            preview_scaled = self._current_pixmap.scaled(
                self.image_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.image_preview.setPixmap(preview_scaled)

    def _on_optics_slider_changed(self, value: int) -> None:
        self.optics_value_label.setText(f"{value}%")

    def _project_image(self) -> None:
        if self._current_pixmap is None:
            self.status_label.setText("Status: No image selected")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
            return
        self.status_label.setText("Status: Projecting")
        self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f7c4e;")

    def _stop_projection(self) -> None:
        self.status_label.setText("Status: Idle")
        self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f4960;")

    def _save_image(self) -> None:
        if self._current_pixmap is None:
            self.status_label.setText("Status: No image to save")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Image", "captured.png",
            "PNG (*.png);;BMP (*.bmp);;JPEG (*.jpg *.jpeg);;All Files (*)"
        )
        if not path:
            return
        if self._current_pixmap.save(path):
            self.status_label.setText(f"Status: Saved — {os.path.basename(path)}")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f7c4e;")
        else:
            self.status_label.setText("Status: Save failed")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
