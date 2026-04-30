"""Sahifa 1: DLP optical test dialog."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Dict, List, Optional

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.app_settings import LED_MAX, LED_MIN, px
from app.widgets.common_ui import Panel

if TYPE_CHECKING:
    from app.hardware import HardwareManager


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

    def __init__(self, hw: "HardwareManager", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hw = hw
        self._current_pixmap: Optional[QPixmap] = None
        self._camera_pixmap: Optional[QPixmap] = None
        self._camera_devices: List[Dict[str, object]] = []
        self._updating_camera_controls = False
        self._image_path = ""
        self._flip_h = False
        self._flip_v = False
        self.setWindowTitle("DLP Test")
        self._build_ui()
        self._connect_camera_signals()
        self._initialize_camera_ui()
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

        root.addWidget(self._build_camera_panel())

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

    def _build_camera_panel(self) -> Panel:
        panel = Panel("Camera Control")
        panel.root.setSpacing(px(8))

        body = QHBoxLayout()
        body.setSpacing(px(12))

        controls = QVBoxLayout()
        controls.setSpacing(px(8))

        device_row = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumHeight(px(32))
        self.camera_combo.setStyleSheet(
            f"background:#f8fafc; border:1px solid #b8c8d8; border-radius:{px(6)}px; padding:0 {px(8)}px;"
        )
        self.refresh_camera_btn = QPushButton("Refresh")
        self.connect_camera_btn = QPushButton("Connect")
        self.refresh_camera_btn.clicked.connect(self._refresh_camera_devices)
        self.connect_camera_btn.clicked.connect(self._connect_selected_camera)
        device_row.addWidget(self.camera_combo, 1)
        device_row.addWidget(self.refresh_camera_btn)
        device_row.addWidget(self.connect_camera_btn)
        controls.addLayout(device_row)

        feature_row = QHBoxLayout()
        feature_row.setSpacing(px(8))
        exposure_label = QLabel("Exposure")
        exposure_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700;")
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setRange(0.0, 1.0)
        self.exposure_spin.setSuffix(" us")
        self.exposure_spin.setEnabled(False)
        self.exposure_spin.setMinimumWidth(px(130))
        self.exposure_spin.editingFinished.connect(lambda: self._apply_camera_feature("exposure"))

        gain_label = QLabel("Gain")
        gain_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700;")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setDecimals(2)
        self.gain_spin.setRange(0.0, 1.0)
        self.gain_spin.setEnabled(False)
        self.gain_spin.setMinimumWidth(px(110))
        self.gain_spin.editingFinished.connect(lambda: self._apply_camera_feature("gain"))

        self.exposure_info_label = QLabel("Unavailable")
        self.gain_info_label = QLabel("Unavailable")
        for label in (self.exposure_info_label, self.gain_info_label):
            label.setStyleSheet(f"font-size:{px(11)}px; color:#6b7280;")

        feature_row.addWidget(exposure_label)
        feature_row.addWidget(self.exposure_spin)
        feature_row.addWidget(self.exposure_info_label)
        feature_row.addSpacing(px(12))
        feature_row.addWidget(gain_label)
        feature_row.addWidget(self.gain_spin)
        feature_row.addWidget(self.gain_info_label)
        feature_row.addStretch(1)
        controls.addLayout(feature_row)

        action_row = QHBoxLayout()
        self.start_preview_btn = QPushButton("Start Preview")
        self.stop_preview_btn = QPushButton("Stop Preview")
        self.capture_camera_btn = QPushButton("Capture One")
        self.start_preview_btn.clicked.connect(self._start_camera_preview)
        self.stop_preview_btn.clicked.connect(self._stop_camera_preview)
        self.capture_camera_btn.clicked.connect(self._capture_camera_snapshot)
        _flip_style = (
            f"QPushButton {{ min-height:{px(32)}px; padding:0 {px(10)}px;"
            f" border-radius:{px(6)}px; border:1px solid #8aaabb;"
            f" background:#ddeaf5; color:#1a2a38; font-weight:700; }}"
            f"QPushButton:checked {{ background:#2878b5; color:#ffffff; border:1px solid #1868a5; }}"
        )
        self.flip_h_btn = QPushButton("Flip H")
        self.flip_h_btn.setCheckable(True)
        self.flip_h_btn.setStyleSheet(_flip_style)
        self.flip_h_btn.toggled.connect(self._on_flip_h_toggled)

        self.flip_v_btn = QPushButton("Flip V")
        self.flip_v_btn.setCheckable(True)
        self.flip_v_btn.setStyleSheet(_flip_style)
        self.flip_v_btn.toggled.connect(self._on_flip_v_toggled)

        action_row.addWidget(self.start_preview_btn)
        action_row.addWidget(self.stop_preview_btn)
        action_row.addWidget(self.capture_camera_btn)
        action_row.addWidget(self.flip_h_btn)
        action_row.addWidget(self.flip_v_btn)
        action_row.addStretch(1)

        self.camera_status_label = QLabel("Camera: Idle")
        self.camera_status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f4960;")
        action_row.addWidget(self.camera_status_label)
        controls.addLayout(action_row)

        body.addLayout(controls, 1)
        panel.root.addLayout(body)
        return panel

    def _connect_camera_signals(self) -> None:
        self._hw.camera_devices_found.connect(self._on_camera_devices_found)
        self._hw.camera_connected.connect(self._on_camera_connected)
        self._hw.camera_preview_state.connect(self._on_camera_preview_state)
        self._hw.camera_frame_ready.connect(self._on_camera_frame_ready)
        self._hw.camera_capture_done.connect(self._on_camera_capture_done)
        self._hw.camera_features_updated.connect(self._on_camera_features_updated)
        self._hw.camera_feature_set_done.connect(self._on_camera_feature_set_done)
        self._hw.camera_warning.connect(self._on_camera_warning)
        self._hw.dlp_upload_done.connect(self._on_dlp_project_done)

    def _initialize_camera_ui(self) -> None:
        self._hw.set_led_percent(float(self.optics_slider.value()))
        self._populate_camera_devices(self._hw.camera_devices)
        self._set_camera_controls_enabled(self._hw.camera_is_connected)
        if self._hw.camera_is_connected:
            self._set_camera_status("Camera: Connected", ok=True)
            self._hw.refresh_camera_features_async()
        else:
            self._set_camera_status("Camera: Not connected", ok=False)
        if not self._hw.camera_devices:
            self._refresh_camera_devices()

    def _set_camera_status(self, text: str, ok: Optional[bool] = None) -> None:
        color = "#2f4960"
        if ok is True:
            color = "#2f7c4e"
        elif ok is False:
            color = "#a44747"
        self.camera_status_label.setText(text)
        self.camera_status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:{color};")

    def _set_camera_controls_enabled(self, connected: bool) -> None:
        self.start_preview_btn.setEnabled(connected)
        self.stop_preview_btn.setEnabled(False)
        self.capture_camera_btn.setEnabled(connected)

    def _populate_camera_devices(self, devices: object) -> None:
        self._camera_devices = list(devices) if isinstance(devices, list) else []
        current_index = self.camera_combo.currentData()
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for device in self._camera_devices:
            display = str(device.get("display_name", "Basler Camera"))
            index = int(device.get("index", 0))
            self.camera_combo.addItem(display, index)
        if current_index is not None:
            match = self.camera_combo.findData(current_index)
            if match >= 0:
                self.camera_combo.setCurrentIndex(match)
        self.camera_combo.blockSignals(False)
        self.connect_camera_btn.setEnabled(self.camera_combo.count() > 0)

    def _selected_camera_index(self) -> int:
        data = self.camera_combo.currentData()
        try:
            return int(data)
        except (TypeError, ValueError):
            return 0

    def _refresh_camera_devices(self) -> None:
        self._set_camera_status("Camera: Scanning...", ok=None)
        self._hw.refresh_camera_devices_async(auto_connect=False)

    def _connect_selected_camera(self) -> None:
        self._set_camera_status("Camera: Connecting...", ok=None)
        self.connect_camera_btn.setEnabled(False)
        self._hw.connect_camera_async(self._selected_camera_index())

    def _start_camera_preview(self) -> None:
        self._set_camera_status("Camera: Starting preview...", ok=None)
        self._hw.start_camera_preview()

    def _stop_camera_preview(self) -> None:
        self._hw.stop_camera_preview()

    def _capture_camera_snapshot(self) -> None:
        self.capture_camera_btn.setEnabled(False)
        self._set_camera_status("Camera: Capturing...", ok=None)
        self._hw.capture_camera_snapshot_async()

    def _apply_camera_feature(self, feature: str) -> None:
        if self._updating_camera_controls:
            return
        spin = self.exposure_spin if feature == "exposure" else self.gain_spin
        if not spin.isEnabled():
            return
        self._hw.set_camera_feature_async(feature, spin.value())

    def _on_camera_devices_found(self, devices: object, message: str) -> None:
        self._populate_camera_devices(devices)
        ok = bool(self._camera_devices)
        self._set_camera_status(f"Camera: {message}", ok=ok)
        self._set_camera_controls_enabled(self._hw.camera_is_connected)

    def _on_camera_connected(self, success: bool, message: str) -> None:
        self.connect_camera_btn.setEnabled(self.camera_combo.count() > 0)
        self._set_camera_controls_enabled(success)
        self._set_camera_status(f"Camera: {message}", ok=success)
        if success:
            self._hw.refresh_camera_features_async()
            self._apply_camera_flip()

    def _on_camera_preview_state(self, running: bool, message: str) -> None:
        connected = self._hw.camera_is_connected
        self.start_preview_btn.setEnabled(connected and not running)
        self.stop_preview_btn.setEnabled(connected and running)
        self.capture_camera_btn.setEnabled(connected)
        self._set_camera_status(f"Camera: {message}", ok=running or connected)

    def _on_camera_frame_ready(self, frame: object) -> None:
        pixmap = self._frame_to_pixmap(frame)
        if pixmap is None:
            return
        self._camera_pixmap = pixmap
        self.projection_preview.set_pixmap(pixmap)
        try:
            mean_value = float(np.mean(np.asarray(frame)))
            self._set_camera_status(f"Camera: Frame received  (mean={mean_value:.1f})", ok=True)
        except Exception:
            self._set_camera_status("Camera: Frame received", ok=True)

    def _on_camera_capture_done(self, success: bool, message: str, frame: object) -> None:
        self.capture_camera_btn.setEnabled(self._hw.camera_is_connected)
        self._set_camera_status(f"Camera: {message}", ok=success)
        if success and frame is not None:
            self._on_camera_frame_ready(frame)

    def _on_camera_feature_set_done(self, success: bool, message: str, _info: object) -> None:
        self._set_camera_status(f"Camera: {message}", ok=success)

    def _on_camera_warning(self, message: str) -> None:
        self._set_camera_status(f"Camera: {message[:80]}", ok=False)

    def _on_camera_features_updated(self, features: object) -> None:
        if not isinstance(features, dict):
            return
        self._configure_feature_spin("exposure", features.get("exposure", {}))
        self._configure_feature_spin("gain", features.get("gain", {}))

    def _configure_feature_spin(self, feature: str, info: object) -> None:
        spin = self.exposure_spin if feature == "exposure" else self.gain_spin
        label = self.exposure_info_label if feature == "exposure" else self.gain_info_label
        data = info if isinstance(info, dict) else {}
        supported = bool(data.get("supported"))
        writable = bool(data.get("writable"))
        value = data.get("value")
        minimum = data.get("minimum")
        maximum = data.get("maximum")
        reason = str(data.get("reason") or "")

        self._updating_camera_controls = True
        spin.blockSignals(True)
        try:
            if supported and writable and value is not None:
                min_value = float(minimum) if minimum is not None else 0.0
                max_value = float(maximum) if maximum is not None else max(min_value + 1.0, float(value))
                if max_value <= min_value:
                    max_value = min_value + 1.0
                spin.setRange(min_value, max_value)
                spin.setValue(max(min_value, min(max_value, float(value))))
                spin.setEnabled(True)
                label.setText(f"{min_value:g}-{max_value:g}")
            else:
                spin.setEnabled(False)
                label.setText(reason or "Not writable")
        finally:
            spin.blockSignals(False)
            self._updating_camera_controls = False

    def _on_flip_h_toggled(self, checked: bool) -> None:
        self._flip_h = checked
        self._apply_camera_flip()

    def _on_flip_v_toggled(self, checked: bool) -> None:
        self._flip_v = checked
        self._apply_camera_flip()

    def _apply_camera_flip(self) -> None:
        self._hw.apply_camera_flip_async(self._flip_h, self._flip_v)

    def _frame_to_pixmap(self, frame: object) -> Optional[QPixmap]:
        try:
            arr = np.asarray(frame)
            if arr.dtype != np.uint8:
                max_value = float(np.iinfo(arr.dtype).max) if np.issubdtype(arr.dtype, np.integer) else 1.0
                arr = np.clip((arr.astype(np.float32) / max_value) * 255.0, 0, 255).astype(np.uint8)
            arr = np.ascontiguousarray(arr.copy())
            if arr.ndim == 2:
                height, width = arr.shape
                image = QImage(arr.data, width, height, width, QImage.Format_Grayscale8).copy()
            elif arr.ndim == 3 and arr.shape[2] >= 3:
                arr = np.ascontiguousarray(arr[:, :, :3].copy())
                height, width, _channels = arr.shape
                image = QImage(arr.data, width, height, width * 3, QImage.Format_RGB888).copy()
            else:
                return None
            return QPixmap.fromImage(image)
        except Exception:
            return None

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
        self._hw.set_led_percent(float(value))

    def _project_image(self) -> None:
        if self._current_pixmap is None:
            self.status_label.setText("Status: No image selected")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
            return
        if not self._hw.dlp_is_connected:
            self.status_label.setText("Status: DLP not connected")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
            return
        if not self._hw.dcs_is_connected:
            self.status_label.setText("Status: LED not connected — no light")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")
            return

        self._hw.set_led_percent(float(self.optics_slider.value()))
        self.status_label.setText("Status: Uploading...")
        self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#1e40af;")
        self.project_btn.setEnabled(False)
        self._hw.project_test_pattern_async(self._image_path)

    def _on_dlp_project_done(self, success: bool, message: str) -> None:
        self.project_btn.setEnabled(True)
        if success:
            self.status_label.setText("Status: Projecting")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#2f7c4e;")
        else:
            self.status_label.setText(f"Status: Error — {message[:60]}")
            self.status_label.setStyleSheet(f"font-size:{px(12)}px; font-weight:700; color:#a44747;")

    def _stop_projection(self) -> None:
        if self._hw.dlp_is_connected:
            try:
                self._hw._dlp.start_stop_sequence("stop")
            except Exception:
                pass
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

    def closeEvent(self, event) -> None:  # noqa: D401
        self._hw.stop_camera_preview()
        super().closeEvent(event)
