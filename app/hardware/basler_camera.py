"""Safe Basler/pypylon camera wrapper."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

FrameCallback = Callable[[np.ndarray], None]
MessageCallback = Callable[[str], None]


@dataclass
class CameraFeature:
    name: str
    supported: bool = False
    writable: bool = False
    value: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "supported": self.supported,
            "writable": self.writable,
            "value": self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "reason": self.reason,
        }


class BaslerCameraController:
    """Thin pypylon adapter that keeps camera failures non-fatal to the app."""

    _FEATURE_ALIASES = {
        "exposure": ("ExposureTime", "ExposureTimeAbs"),
        "gain": ("Gain", "GainRaw"),
    }

    def __init__(self):
        self._pylon = None
        self._genicam = None
        self._import_error = ""
        self._devices: List[object] = []
        self._camera = None
        self._connected_index: Optional[int] = None
        self._converter = None
        self._lock = threading.RLock()
        self._preview_stop = threading.Event()
        self._preview_thread: Optional[threading.Thread] = None

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._camera is not None and bool(self._safe_call(self._camera, "IsOpen", False))

    @property
    def preview_running(self) -> bool:
        thread = self._preview_thread
        return thread is not None and thread.is_alive()

    @property
    def connected_index(self) -> Optional[int]:
        return self._connected_index

    def feature_persistence_available(self) -> bool:
        pylon = self._load_pylon()
        return pylon is not None and hasattr(pylon, "FeaturePersistence")

    def _load_pylon(self):
        if self._pylon is not None:
            return self._pylon
        if self._import_error:
            return None
        try:
            from pypylon import genicam, pylon  # type: ignore
        except Exception as exc:
            self._import_error = f"pypylon unavailable: {exc}"
            return None
        self._pylon = pylon
        self._genicam = genicam
        return pylon

    @staticmethod
    def _safe_call(obj, method: str, default: str = ""):
        try:
            attr = getattr(obj, method, None)
            if callable(attr):
                return attr()
        except Exception:
            return default
        return default

    @staticmethod
    def _read_node_value(node):
        try:
            return node.Value
        except Exception:
            pass
        try:
            return node.GetValue()
        except Exception:
            return None

    @staticmethod
    def _write_node_value(node, value) -> None:
        try:
            node.Value = value
            return
        except Exception:
            pass
        node.SetValue(value)

    @staticmethod
    def _node_flag_with_genicam(genicam, node, method: str, default: bool) -> bool:
        genicam_method = getattr(genicam, method, None) if genicam is not None else None
        if callable(genicam_method):
            try:
                return bool(genicam_method(node))
            except Exception:
                pass
        try:
            attr = getattr(node, method, None)
            if callable(attr):
                return bool(attr())
        except Exception:
            return default
        return default

    @staticmethod
    def _node_bound(node, attr_name: str, method_name: str) -> Optional[float]:
        try:
            value = getattr(node, attr_name)
            return float(value)
        except Exception:
            pass
        try:
            method = getattr(node, method_name, None)
            if callable(method):
                return float(method())
        except Exception:
            pass
        return None

    @staticmethod
    def _device_label(index: int, device) -> Dict[str, object]:
        model = str(BaslerCameraController._safe_call(device, "GetModelName", "Basler Camera"))
        serial = str(BaslerCameraController._safe_call(device, "GetSerialNumber", ""))
        user_id = str(BaslerCameraController._safe_call(device, "GetUserDefinedName", ""))
        device_class = str(BaslerCameraController._safe_call(device, "GetDeviceClass", ""))
        full_name = str(BaslerCameraController._safe_call(device, "GetFullName", ""))

        parts = [part for part in (user_id, model, serial) if part]
        display = " - ".join(parts) if parts else f"Camera {index + 1}"
        return {
            "index": index,
            "display_name": display,
            "model": model,
            "serial": serial,
            "user_id": user_id,
            "device_class": device_class,
            "full_name": full_name,
        }

    def enumerate_cameras(self) -> Tuple[List[Dict[str, object]], str]:
        pylon = self._load_pylon()
        if pylon is None:
            return [], self._import_error or "pypylon unavailable"

        try:
            devices = list(pylon.TlFactory.GetInstance().EnumerateDevices())
        except Exception as exc:
            self._devices = []
            return [], f"Camera enumeration failed: {exc}"

        self._devices = devices
        infos = [self._device_label(index, device) for index, device in enumerate(devices)]
        if not infos:
            return [], "No Basler camera detected"
        return infos, f"{len(infos)} camera(s) detected"

    def connect(self, index: int = 0) -> Tuple[bool, str]:
        self.disconnect()

        pylon = self._load_pylon()
        if pylon is None:
            return False, self._import_error or "pypylon unavailable"

        infos, message = self.enumerate_cameras()
        if not infos:
            return False, message
        if index < 0 or index >= len(self._devices):
            return False, f"Camera index {index} is not available"

        try:
            camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateDevice(self._devices[index]))
            camera.Open()
            converter = None
            if hasattr(pylon, "ImageFormatConverter"):
                converter = pylon.ImageFormatConverter()
                converter.OutputPixelFormat = pylon.PixelType_RGB8packed
                converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

            with self._lock:
                self._camera = camera
                self._converter = converter
                self._connected_index = index
                self._set_trigger_off_locked()

            return True, f"Camera connected: {infos[index]['display_name']}"
        except Exception as exc:
            self.disconnect()
            return False, f"Camera connect failed: {exc}"

    def disconnect(self) -> None:
        self.stop_preview()
        with self._lock:
            camera = self._camera
            self._camera = None
            self._converter = None
            self._connected_index = None
        if camera is None:
            return
        try:
            if camera.IsGrabbing():
                camera.StopGrabbing()
        except Exception:
            logger.debug("Failed to stop camera grabbing during disconnect", exc_info=True)
        try:
            if camera.IsOpen():
                camera.Close()
        except Exception:
            logger.debug("Failed to close camera", exc_info=True)

    def _ensure_camera_locked(self):
        if self._camera is None or not bool(self._safe_call(self._camera, "IsOpen", False)):
            raise RuntimeError("Camera is not connected")
        return self._camera

    def _set_enum_locked(self, name: str, value: str) -> None:
        try:
            node = getattr(self._camera, name, None)
        except Exception:
            return
        if node is None or not self._node_flag_with_genicam(self._genicam, node, "IsWritable", True):
            return
        try:
            self._write_node_value(node, value)
        except Exception:
            logger.debug("Camera enum %s=%s failed", name, value, exc_info=True)

    def _set_trigger_off_locked(self) -> None:
        self._ensure_camera_locked()
        self._set_enum_locked("AcquisitionMode", "Continuous")
        self._set_enum_locked("TriggerSelector", "FrameStart")
        self._set_enum_locked("TriggerMode", "Off")

    def _set_software_trigger_locked(self) -> None:
        self._ensure_camera_locked()
        self._set_enum_locked("AcquisitionMode", "Continuous")
        self._set_enum_locked("TriggerSelector", "FrameStart")
        self._set_enum_locked("TriggerMode", "On")
        self._set_enum_locked("TriggerSource", "Software")

    def _set_auto_off_locked(self, name: str) -> None:
        try:
            node = getattr(self._camera, name, None)
        except Exception:
            return
        if node is None or not self._node_flag_with_genicam(self._genicam, node, "IsWritable", False):
            return
        try:
            self._write_node_value(node, "Off")
        except Exception:
            logger.debug("Camera enum %s=Off failed", name, exc_info=True)

    def _find_feature_locked(self, feature: str):
        aliases = self._FEATURE_ALIASES.get(feature, (feature,))
        for name in aliases:
            try:
                node = getattr(self._camera, name, None)
            except Exception:
                node = None
            if node is not None:
                return name, node
        return aliases[0], None

    def get_feature_info(self, feature: str) -> CameraFeature:
        with self._lock:
            if not self.is_connected:
                return CameraFeature(feature, reason="Camera is not connected")
            name, node = self._find_feature_locked(feature)
            if node is None:
                return CameraFeature(feature, reason=f"{name} is not supported")

            available = self._node_flag_with_genicam(self._genicam, node, "IsAvailable", True)
            readable = self._node_flag_with_genicam(self._genicam, node, "IsReadable", True)
            if not available or not readable:
                return CameraFeature(feature, reason=f"{name} is not readable")

            writable = self._node_flag_with_genicam(self._genicam, node, "IsWritable", False)
            value = self._read_node_value(node)
            try:
                value = float(value) if value is not None else None
            except (TypeError, ValueError):
                value = None
            return CameraFeature(
                name=name,
                supported=True,
                writable=writable,
                value=value,
                minimum=self._node_bound(node, "Min", "GetMin"),
                maximum=self._node_bound(node, "Max", "GetMax"),
            )

    def get_feature_infos(self) -> Dict[str, Dict[str, object]]:
        return {
            "exposure": self.get_feature_info("exposure").as_dict(),
            "gain": self.get_feature_info("gain").as_dict(),
        }

    def set_feature(self, feature: str, value: float) -> Tuple[bool, str, Dict[str, object]]:
        with self._lock:
            if not self.is_connected:
                info = CameraFeature(feature, reason="Camera is not connected")
                return False, info.reason, info.as_dict()

            name, node = self._find_feature_locked(feature)
            if node is None:
                info = CameraFeature(feature, reason=f"{name} is not supported")
                return False, info.reason, info.as_dict()
            if not self._node_flag_with_genicam(self._genicam, node, "IsWritable", False):
                info = self.get_feature_info(feature)
                info.reason = f"{name} is not writable"
                return False, info.reason, info.as_dict()

            minimum = self._node_bound(node, "Min", "GetMin")
            maximum = self._node_bound(node, "Max", "GetMax")
            clamped = float(value)
            if minimum is not None:
                clamped = max(minimum, clamped)
            if maximum is not None:
                clamped = min(maximum, clamped)

            current = self._read_node_value(node)
            write_value = int(round(clamped)) if isinstance(current, int) else clamped

            try:
                if feature == "exposure":
                    self._set_auto_off_locked("ExposureAuto")
                elif feature == "gain":
                    self._set_auto_off_locked("GainAuto")
                self._write_node_value(node, write_value)
            except Exception as exc:
                info = self.get_feature_info(feature)
                info.reason = str(exc)
                return False, f"{name} set failed: {exc}", info.as_dict()

            info = self.get_feature_info(feature)
            return True, f"{name} set to {info.value}", info.as_dict()

    def start_preview(
        self,
        on_frame: FrameCallback,
        on_error: Optional[MessageCallback] = None,
        fps_limit: float = 10.0,
    ) -> Tuple[bool, str]:
        if self.preview_running:
            return True, "Camera preview already running"
        if not self.is_connected:
            return False, "Camera is not connected"

        self._preview_stop.clear()
        self._preview_thread = threading.Thread(
            target=self._preview_loop,
            args=(on_frame, on_error, fps_limit),
            daemon=True,
        )
        self._preview_thread.start()
        return True, "Camera preview started"

    def stop_preview(self) -> None:
        thread = self._preview_thread
        if thread is not None and thread.is_alive():
            self._preview_stop.set()
            thread.join(timeout=2.0)
        self._preview_thread = None
        with self._lock:
            try:
                if self._camera is not None and self._camera.IsGrabbing():
                    self._camera.StopGrabbing()
            except Exception:
                logger.debug("Failed to stop preview grabbing", exc_info=True)
        self._preview_stop.clear()

    def _preview_loop(
        self,
        on_frame: FrameCallback,
        on_error: Optional[MessageCallback],
        fps_limit: float,
    ) -> None:
        min_interval = 1.0 / max(1.0, fps_limit)
        try:
            with self._lock:
                camera = self._ensure_camera_locked()
                if camera.IsGrabbing():
                    camera.StopGrabbing()
                self._set_trigger_off_locked()
                camera.StartGrabbing(self._pylon.GrabStrategy_LatestImageOnly)

            while not self._preview_stop.is_set():
                started = time.monotonic()
                grab_result = None
                try:
                    with self._lock:
                        camera = self._ensure_camera_locked()
                        if not camera.IsGrabbing():
                            break
                        grab_result = camera.RetrieveResult(1000, self._pylon.TimeoutHandling_Return)
                    if grab_result is None:
                        continue
                    if grab_result.GrabSucceeded():
                        on_frame(self._grab_result_to_array(grab_result))
                    else:
                        err = f"Camera preview grab failed: {grab_result.ErrorDescription}"
                        if on_error:
                            on_error(err)
                finally:
                    if grab_result is not None:
                        grab_result.Release()

                elapsed = time.monotonic() - started
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
        except Exception as exc:
            if on_error:
                on_error(f"Camera preview stopped: {exc}")
        finally:
            with self._lock:
                try:
                    if self._camera is not None and self._camera.IsGrabbing():
                        self._camera.StopGrabbing()
                except Exception:
                    logger.debug("Failed to stop camera after preview loop", exc_info=True)

    def capture_one(self, timeout_ms: int = 5000) -> Tuple[bool, str, Optional[np.ndarray]]:
        self.stop_preview()
        if not self.is_connected:
            return False, "Camera is not connected", None

        grab_result = None
        try:
            with self._lock:
                camera = self._ensure_camera_locked()
                if camera.IsGrabbing():
                    camera.StopGrabbing()
                self._set_software_trigger_locked()
                camera.StartGrabbingMax(1)
                if hasattr(camera, "WaitForFrameTriggerReady"):
                    camera.WaitForFrameTriggerReady(2000, self._pylon.TimeoutHandling_ThrowException)
                camera.ExecuteSoftwareTrigger()
                grab_result = camera.RetrieveResult(timeout_ms, self._pylon.TimeoutHandling_ThrowException)

                if grab_result is None or not grab_result.GrabSucceeded():
                    err = "" if grab_result is None else str(grab_result.ErrorDescription)
                    return False, f"Camera capture failed: {err}", None
                frame = self._grab_result_to_array(grab_result)
                return True, "Camera capture complete", frame
        except Exception as exc:
            return False, f"Camera capture failed: {exc}", None
        finally:
            if grab_result is not None:
                grab_result.Release()
            with self._lock:
                try:
                    if self._camera is not None and self._camera.IsGrabbing():
                        self._camera.StopGrabbing()
                    if self._camera is not None and self._camera.IsOpen():
                        self._set_trigger_off_locked()
                except Exception:
                    logger.debug("Failed to restore trigger-off mode after capture", exc_info=True)

    def _grab_result_to_array(self, grab_result) -> np.ndarray:
        arr = None
        if self._converter is not None:
            try:
                converted = self._converter.Convert(grab_result)
                arr = converted.GetArray()
            except Exception:
                logger.debug("pypylon image conversion failed; using raw array", exc_info=True)
                arr = None
        if arr is None:
            arr = grab_result.Array

        arr = np.asarray(arr)
        if arr.dtype != np.uint8:
            max_value = float(np.iinfo(arr.dtype).max) if np.issubdtype(arr.dtype, np.integer) else 1.0
            arr = np.clip((arr.astype(np.float32) / max_value) * 255.0, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            arr = np.stack((arr, arr, arr), axis=-1)
        elif arr.ndim == 3 and arr.shape[2] >= 3:
            arr = arr[:, :, :3]
        else:
            raise ValueError(f"Unsupported camera frame shape: {arr.shape}")
        return np.ascontiguousarray(arr).copy()

    def apply_flip(self, flip_h: bool, flip_v: bool) -> None:
        with self._lock:
            if not self.is_connected:
                return
            for attr, value in (("ReverseX", flip_h), ("ReverseY", flip_v)):
                try:
                    node = getattr(self._camera, attr, None)
                    if node is not None and self._node_flag_with_genicam(
                        self._genicam, node, "IsWritable", False
                    ):
                        self._write_node_value(node, value)
                    else:
                        logger.debug("%s not available or not writable on this camera", attr)
                except Exception:
                    logger.debug("%s set failed", attr, exc_info=True)

    def load_pfs(self, path: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Camera is not connected"
        pylon = self._load_pylon()
        if pylon is None or not hasattr(pylon, "FeaturePersistence"):
            return False, "pypylon FeaturePersistence is unavailable"
        self.stop_preview()
        try:
            with self._lock:
                pylon.FeaturePersistence.Load(path, self._camera.GetNodeMap(), True)
            return True, f"Camera settings loaded: {path}"
        except Exception as exc:
            return False, f"Load .pfs failed: {exc}"

    def save_pfs(self, path: str) -> Tuple[bool, str]:
        if not self.is_connected:
            return False, "Camera is not connected"
        pylon = self._load_pylon()
        if pylon is None or not hasattr(pylon, "FeaturePersistence"):
            return False, "pypylon FeaturePersistence is unavailable"
        self.stop_preview()
        try:
            with self._lock:
                pylon.FeaturePersistence.Save(path, self._camera.GetNodeMap())
            return True, f"Camera settings saved: {path}"
        except Exception as exc:
            return False, f"Save .pfs failed: {exc}"
