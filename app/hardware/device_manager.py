"""Central hardware facade for DCS LED controller and DLP projector."""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

from PySide6.QtCore import QObject, Signal

from app.hardware.basler_camera import BaslerCameraController
from app.hardware.led_controller import DCSController
from app.hardware.dlp_projector_driver import dlp6500

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


DEFAULT_DCS_IP = os.environ.get("DCS_IP", DCSController.DEFAULT_IP)
DEFAULT_DCS_PORT = _env_int("DCS_PORT", DCSController.DEFAULT_PORT)
DEFAULT_DCS_LOCAL_IP = os.environ.get("DCS_LOCAL_IP", "")
DEFAULT_DCS_CHANNEL = _env_int("DCS_CHANNEL", 1)

DLP_WIDTH = 1920
DLP_HEIGHT = 1080
_THRESHOLD = 128


class HardwareManager(QObject):
    dcs_connected = Signal(bool, str)
    dlp_connected = Signal(bool, str)
    dlp_upload_done = Signal(bool, str)
    camera_devices_found = Signal(object, str)
    camera_connected = Signal(bool, str)
    camera_preview_state = Signal(bool, str)
    camera_frame_ready = Signal(object)
    camera_capture_done = Signal(bool, str, object)
    camera_features_updated = Signal(object)
    camera_feature_set_done = Signal(bool, str, object)
    camera_pfs_done = Signal(bool, str)
    camera_warning = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dcs: Optional[DCSController] = None
        self._dlp: Optional[dlp6500] = None
        self._camera = BaslerCameraController()
        self._camera_devices: List[Dict[str, object]] = []
        self._lock = threading.Lock()

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def dcs_is_connected(self) -> bool:
        return self._dcs is not None and self._dcs.connected

    @property
    def dlp_is_connected(self) -> bool:
        return self._dlp is not None

    @property
    def camera_is_connected(self) -> bool:
        return self._camera.is_connected

    @property
    def camera_devices(self) -> List[Dict[str, object]]:
        return list(self._camera_devices)

    # ── DCS ─────────────────────────────────────────────────────────────────

    def connect_dcs_async(
        self,
        ip: str = DEFAULT_DCS_IP,
        port: int = DEFAULT_DCS_PORT,
        local_ip: str = DEFAULT_DCS_LOCAL_IP,
        channel: int = DEFAULT_DCS_CHANNEL,
    ) -> None:
        def _run():
            try:
                ctrl = DCSController(
                    ip_address=ip,
                    port=port,
                    local_ip=local_ip,
                    channel=channel,
                )
                ok = ctrl.connect()
                if ok:
                    with self._lock:
                        if self._dcs is not None:
                            try:
                                self._dcs.disconnect()
                            except Exception:
                                pass
                        self._dcs = ctrl
                    via = f" via {ctrl.local_ip}" if ctrl.local_ip else ""
                    self.dcs_connected.emit(True, f"DCS connected — {ip}:{port}{via}")
                else:
                    self.dcs_connected.emit(False, f"DCS connect failed — {ip}")
            except Exception as exc:
                self.dcs_connected.emit(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def disconnect_dcs(self) -> None:
        with self._lock:
            if self._dcs:
                try:
                    self._dcs.turn_off_all()
                    self._dcs.disconnect()
                except Exception:
                    pass
                self._dcs = None

    def set_led_percent(self, percent: float) -> None:
        if not self.dcs_is_connected:
            return
        try:
            self._dcs.set_intensity_percent(percent)
        except Exception as exc:
            logger.warning("DCS set_intensity_percent: %s", exc)

    # ── DLP ─────────────────────────────────────────────────────────────────

    def connect_dlp_async(self) -> None:
        def _run():
            try:
                dev = dlp6500(initialize=True, debug=False)
                with self._lock:
                    if self._dlp is not None:
                        try:
                            self._dlp.start_stop_sequence("stop")
                        except Exception:
                            pass
                    self._dlp = dev
                self.dlp_connected.emit(True, "DLP6500 connected")
            except Exception as exc:
                self.dlp_connected.emit(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def disconnect_dlp(self) -> None:
        with self._lock:
            if self._dlp:
                try:
                    self._dlp.start_stop_sequence("stop")
                except Exception:
                    pass
                self._dlp = None

    def stop_dlp_sequence(self) -> None:
        if self._dlp is None:
            return
        try:
            self._dlp.start_stop_sequence("stop")
        except Exception as exc:
            logger.warning("DLP stop_sequence: %s", exc)

    # Camera

    def refresh_camera_devices_async(self, auto_connect: bool = False) -> None:
        def _run():
            devices, message = self._camera.enumerate_cameras()
            self._camera_devices = devices
            self.camera_devices_found.emit(devices, message)
            if auto_connect and devices:
                first_index = int(devices[0].get("index", 0))
                self.connect_camera_async(first_index)
            elif not devices:
                self.camera_connected.emit(False, message)

        threading.Thread(target=_run, daemon=True).start()

    def connect_camera_async(self, index: int = 0) -> None:
        def _run():
            try:
                ok, message = self._camera.connect(int(index))
                self.camera_connected.emit(ok, message)
                if ok:
                    self.camera_features_updated.emit(self._camera.get_feature_infos())
                else:
                    self.camera_warning.emit(message)
            except Exception as exc:
                self.camera_connected.emit(False, str(exc))
                self.camera_warning.emit(str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def disconnect_camera(self) -> None:
        self._camera.disconnect()

    def get_camera_features(self) -> Dict[str, Dict[str, object]]:
        return self._camera.get_feature_infos()

    def refresh_camera_features_async(self) -> None:
        def _run():
            self.camera_features_updated.emit(self._camera.get_feature_infos())

        threading.Thread(target=_run, daemon=True).start()

    def set_camera_feature_async(self, feature: str, value: float) -> None:
        def _run():
            ok, message, info = self._camera.set_feature(feature, value)
            self.camera_feature_set_done.emit(ok, message, info)
            self.camera_features_updated.emit(self._camera.get_feature_infos())
            if not ok:
                self.camera_warning.emit(message)

        threading.Thread(target=_run, daemon=True).start()

    def apply_camera_flip_async(self, flip_h: bool, flip_v: bool) -> None:
        def _run():
            was_previewing = self._camera.preview_running
            if was_previewing:
                self._camera.stop_preview()
            self._camera.apply_flip(flip_h, flip_v)
            if was_previewing:
                ok, message = self._camera.start_preview(
                    on_frame=lambda frame: self.camera_frame_ready.emit(frame),
                    on_error=lambda msg: self.camera_warning.emit(msg),
                )
                self.camera_preview_state.emit(ok, message)

        threading.Thread(target=_run, daemon=True).start()

    def start_camera_preview(self) -> None:
        ok, message = self._camera.start_preview(
            on_frame=lambda frame: self.camera_frame_ready.emit(frame),
            on_error=lambda msg: self.camera_warning.emit(msg),
        )
        self.camera_preview_state.emit(ok, message)
        if not ok:
            self.camera_warning.emit(message)

    def stop_camera_preview(self) -> None:
        self._camera.stop_preview()
        self.camera_preview_state.emit(False, "Camera preview stopped")

    def capture_camera_snapshot_async(self) -> None:
        def _run():
            restore_preview = self._camera.preview_running
            if restore_preview:
                self._camera.stop_preview()
                self.camera_preview_state.emit(False, "Camera preview stopped for capture")

            ok, message, frame = self._camera.capture_one()
            self.camera_capture_done.emit(ok, message, frame)
            if not ok:
                self.camera_warning.emit(message)

            if restore_preview and self._camera.is_connected:
                preview_ok, preview_message = self._camera.start_preview(
                    on_frame=lambda arr: self.camera_frame_ready.emit(arr),
                    on_error=lambda msg: self.camera_warning.emit(msg),
                )
                self.camera_preview_state.emit(preview_ok, preview_message)
                if not preview_ok:
                    self.camera_warning.emit(preview_message)

        threading.Thread(target=_run, daemon=True).start()

    def load_camera_pfs_async(self, path: str) -> None:
        def _run():
            restore_preview = self._camera.preview_running
            if restore_preview:
                self._camera.stop_preview()
                self.camera_preview_state.emit(False, "Camera preview stopped for .pfs load")

            ok, message = self._camera.load_pfs(path)
            self.camera_pfs_done.emit(ok, message)
            self.camera_features_updated.emit(self._camera.get_feature_infos())
            if not ok:
                self.camera_warning.emit(message)

            if restore_preview and self._camera.is_connected:
                preview_ok, preview_message = self._camera.start_preview(
                    on_frame=lambda arr: self.camera_frame_ready.emit(arr),
                    on_error=lambda msg: self.camera_warning.emit(msg),
                )
                self.camera_preview_state.emit(preview_ok, preview_message)
                if not preview_ok:
                    self.camera_warning.emit(preview_message)

        threading.Thread(target=_run, daemon=True).start()

    def save_camera_pfs_async(self, path: str) -> None:
        def _run():
            restore_preview = self._camera.preview_running
            if restore_preview:
                self._camera.stop_preview()
                self.camera_preview_state.emit(False, "Camera preview stopped for .pfs save")

            ok, message = self._camera.save_pfs(path)
            self.camera_pfs_done.emit(ok, message)
            if not ok:
                self.camera_warning.emit(message)

            if restore_preview and self._camera.is_connected:
                preview_ok, preview_message = self._camera.start_preview(
                    on_frame=lambda arr: self.camera_frame_ready.emit(arr),
                    on_error=lambda msg: self.camera_warning.emit(msg),
                )
                self.camera_preview_state.emit(preview_ok, preview_message)
                if not preview_ok:
                    self.camera_warning.emit(preview_message)

        threading.Thread(target=_run, daemon=True).start()

    # ── pattern helpers ──────────────────────────────────────────────────────

    @staticmethod
    def load_pattern_image(path: str) -> Optional[np.ndarray]:
        """Load a mask image, resize to DLP resolution, and return uint8 0/1 data."""
        try:
            img = Image.open(path).convert("L")
            img = img.resize((DLP_WIDTH, DLP_HEIGHT), Image.LANCZOS)
            arr = np.array(img, dtype=np.uint8)
            return (arr >= _THRESHOLD).astype(np.uint8)
        except Exception as exc:
            logger.error("load_pattern_image %s: %s", path, exc)
            return None

    @staticmethod
    def convert_png_patterns_to_bmp(
        folder: str,
        sequences: List[int],
        bases: List[str],
    ) -> Dict[str, object]:
        """Convert expected Pos{sequence}_{base}.png masks to 1-channel BMP files."""
        result: Dict[str, object] = {
            "converted": 0,
            "skipped": 0,
            "missing_png": [],
            "failed": [],
        }

        missing_png: List[str] = []
        failed: List[str] = []

        for seq in sequences:
            for base in bases:
                stem = f"Pos{seq}_{base}"
                png_path = os.path.join(folder, f"{stem}.png")
                bmp_path = os.path.join(folder, f"{stem}.bmp")

                if not os.path.exists(png_path):
                    if os.path.exists(bmp_path):
                        result["skipped"] = int(result["skipped"]) + 1
                        continue
                    missing_png.append(f"{stem}.png")
                    continue

                try:
                    if (
                        os.path.exists(bmp_path)
                        and os.path.getmtime(bmp_path) >= os.path.getmtime(png_path)
                    ):
                        result["skipped"] = int(result["skipped"]) + 1
                        continue

                    img = Image.open(png_path).convert("L")
                    if img.size != (DLP_WIDTH, DLP_HEIGHT):
                        img = img.resize((DLP_WIDTH, DLP_HEIGHT), Image.LANCZOS)
                    arr = np.array(img, dtype=np.uint8)
                    mask = np.where(arr >= _THRESHOLD, 255, 0).astype(np.uint8)
                    Image.fromarray(mask, mode="L").save(bmp_path, format="BMP")
                    result["converted"] = int(result["converted"]) + 1
                except Exception as exc:
                    logger.error("convert_png_patterns_to_bmp %s: %s", png_path, exc)
                    failed.append(f"{stem}.png")

        result["missing_png"] = missing_png
        result["failed"] = failed
        return result

    def project_test_pattern_async(self, image_path: str) -> None:
        """Upload and start a single test pattern on the DLP."""
        def _run():
            if self._dlp is None:
                self.dlp_upload_done.emit(False, "DLP not connected")
                return
            arr = self.load_pattern_image(image_path)
            if arr is None:
                self.dlp_upload_done.emit(False, "Image load failed")
                return
            try:
                dlp = self._dlp
                dlp.upload_pattern_sequence(
                    patterns=arr[np.newaxis, ...],
                    exp_times=[dlp.min_time_us],
                    dark_times=0,
                    num_repeats=0,
                    compression_mode="erle",
                )
                self.dlp_upload_done.emit(True, "Projecting")
            except Exception as exc:
                self.dlp_upload_done.emit(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def upload_all_patterns_async(
        self,
        folder: str,
        sequences: List[int],
        bases: List[str],
        base_times_ms: Dict[str, int],
        file_extension: str = ".bmp",
    ) -> None:
        """Load all pattern masks and upload to DLP in a daemon thread."""
        def _run():
            if self._dlp is None:
                self.dlp_upload_done.emit(False, "DLP not connected")
                return

            pattern_list: List[np.ndarray] = []
            exp_times_us: List[int] = []
            missing: List[str] = []

            for seq in sequences:
                for base in bases:
                    ext = file_extension if file_extension.startswith(".") else f".{file_extension}"
                    fname = f"Pos{seq}_{base}{ext}"
                    fpath = os.path.join(folder, fname)
                    arr = self.load_pattern_image(fpath)
                    if arr is None:
                        arr = np.zeros((DLP_HEIGHT, DLP_WIDTH), dtype=np.uint8)
                        missing.append(fname)
                    pattern_list.append(arr)
                    exp_us = max(self._dlp.min_time_us, base_times_ms.get(base, 3500) * 1000)
                    exp_times_us.append(exp_us)

            patterns_np = np.stack(pattern_list, axis=0)

            try:
                self._dlp.upload_pattern_sequence(
                    patterns=patterns_np,
                    exp_times=exp_times_us,
                    dark_times=0,
                    num_repeats=0,
                    compression_mode="erle",
                )
                warn_str = f" ({len(missing)} missing)" if missing else ""
                self.dlp_upload_done.emit(True, f"DLP upload complete{warn_str}")
            except Exception as exc:
                self.dlp_upload_done.emit(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()
