"""Arduino Mega 2560 serial driver."""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # Keep the rest of the app usable when pyserial is absent.
    serial = None  # type: ignore[assignment]


class ArduinoController:
    DEFAULT_BAUD = 9600
    _DONE_MARKER = "DONE"
    _BOOT_MARKERS = (
        "System init",
        "96-Well Stage",
        "[Takasago] Init OK",
        "Ready.",
    )
    _ARDUINO_USB_VIDS = {0x2341, 0x2A03}
    _LIKELY_USB_ADAPTERS = {
        (0x1A86, 0x7523),  # CH340/CH341
        (0x0403, 0x6001),  # FTDI
        (0x10C4, 0xEA60),  # CP210x
    }
    _PORT_KEYWORDS = ("arduino", "mega", "ch340", "wch", "usb-serial", "usb serial")
    _SKIP_KEYWORDS = ("bluetooth",)

    def __init__(self) -> None:
        self._serial: Optional[object] = None
        self._lock = threading.Lock()
        self._port: str = ""

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    @property
    def port(self) -> str:
        return self._port

    @classmethod
    def auto_detect(
        cls,
        baud: int = DEFAULT_BAUD,
        scan_timeout_s: float = 12.0,
    ) -> Tuple[Optional[str], str]:
        """Return the Arduino port when the expected firmware answers.

        The supplied firmware prints boot banners in setup() and prints DONE
        after each newline-terminated command. PSTATUS is read-only in that
        sketch, so it is safe for probing.
        """
        if serial is None:
            return None, "pyserial is not installed"

        infos = cls._sorted_port_infos()
        if not infos:
            return None, "No COM ports found"

        candidates = [info for info in infos if not cls._is_skipped_port(info)]
        if not candidates:
            candidates = infos

        deadline = time.monotonic() + scan_timeout_s
        scanned: List[str] = []
        errors: List[str] = []

        for info in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            port = str(getattr(info, "device", ""))
            if not port:
                continue

            scanned.append(port)
            found, detail = cls._probe_port(port, baud, remaining)
            if found:
                return port, f"Arduino detected on {port}"
            if detail:
                errors.append(f"{port}: {detail}")

        likely_ports = [str(getattr(info, "device", "")) for info in candidates if cls._port_score(info) <= 2]
        likely_ports = [port for port in likely_ports if port]
        if likely_ports:
            return (
                None,
                "Arduino-like port(s) found but no firmware reply at "
                f"{baud} baud: {', '.join(likely_ports)}",
            )

        scanned_text = ", ".join(scanned) if scanned else "none"
        if errors:
            return None, f"Arduino not found; scanned {scanned_text}; {errors[-1]}"
        return None, f"Arduino not found; scanned {scanned_text}"

    def connect(self, port: str, baud: int = DEFAULT_BAUD) -> Tuple[bool, str]:
        if serial is None:
            return False, "Arduino connect failed: pyserial is not installed"

        with self._lock:
            if self._serial and getattr(self._serial, "is_open", False):
                try:
                    self._serial.close()
                except Exception:
                    pass
            try:
                ser = serial.Serial(port, baud, timeout=2)
                time.sleep(4.0)
                ser.reset_input_buffer()
                self._serial = ser
                self._port = port
                return True, f"Arduino connected on {port}"
            except Exception as exc:
                self._serial = None
                self._port = ""
                return False, f"Arduino connect failed on {port}: {exc}"

    def disconnect(self) -> None:
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                self._port = ""

    def _drop_serial(self, ser: object) -> None:
        with self._lock:
            if self._serial is not ser:
                return
            try:
                ser.close()
            except Exception:
                pass
            self._serial = None
            self._port = ""

    def send_and_wait(self, command: str, timeout_s: float = 120.0) -> Tuple[bool, str]:
        """Send a semicolon-delimited command and wait for Arduino DONE."""
        with self._lock:
            if not self._serial or not getattr(self._serial, "is_open", False):
                return False, "Arduino not connected"
            ser = self._serial

        try:
            ser.reset_input_buffer()
            ser.write((command.strip() + "\n").encode())
            ser.flush()
        except Exception as exc:
            self._drop_serial(ser)
            return False, f"Arduino write error: {exc}"

        deadline = time.monotonic() + timeout_s
        rx_lines: List[str] = []
        while time.monotonic() < deadline:
            try:
                line = ser.readline().decode(errors="replace").strip()
                if not line:
                    continue
                if line == self._DONE_MARKER:
                    detail = " | ".join(rx_lines[-8:])
                    return True, f"Done: {detail}" if detail else "Done"
                rx_lines.append(line)
            except Exception as exc:
                self._drop_serial(ser)
                return False, f"Arduino read error: {exc}"

        self._drop_serial(ser)
        return False, f"Arduino timeout after {int(timeout_s)}s"

    @staticmethod
    def list_ports() -> List[str]:
        if serial is None:
            return []
        return [str(getattr(p, "device", "")) for p in ArduinoController._sorted_port_infos()]

    @classmethod
    def _probe_port(cls, port: str, baud: int, budget_s: float) -> Tuple[bool, str]:
        ser = None
        try:
            ser = serial.Serial(port, baud, timeout=0.25, write_timeout=1.0)
            time.sleep(0.2)

            boot_deadline = time.monotonic() + min(4.5, max(0.5, budget_s - 2.5))
            if cls._read_until_marker(ser, boot_deadline):
                return True, ""

            try:
                ser.reset_input_buffer()
            except Exception:
                pass

            ser.write(b"PSTATUS\n")
            ser.flush()

            command_deadline = time.monotonic() + min(4.5, max(0.5, budget_s - 0.3))
            if cls._read_until_marker(ser, command_deadline):
                return True, ""
            return False, "no DONE/Ready reply"
        except Exception as exc:
            return False, str(exc)
        finally:
            if ser is not None:
                try:
                    ser.close()
                    time.sleep(0.2)
                except Exception:
                    pass

    @classmethod
    def _read_until_marker(cls, ser: object, deadline: float) -> bool:
        while time.monotonic() < deadline:
            line = ser.readline().decode(errors="replace").strip()
            if not line:
                continue
            if line == cls._DONE_MARKER:
                return True
            if any(marker in line for marker in cls._BOOT_MARKERS):
                return True
        return False

    @classmethod
    def _sorted_port_infos(cls) -> List[object]:
        return sorted(serial.tools.list_ports.comports(), key=cls._port_score)

    @classmethod
    def _port_score(cls, info: object) -> int:
        text = cls._port_text(info)
        vid = getattr(info, "vid", None)
        pid = getattr(info, "pid", None)

        if any(keyword in text for keyword in cls._SKIP_KEYWORDS):
            return 100
        if vid in cls._ARDUINO_USB_VIDS:
            return 0
        if (vid, pid) in cls._LIKELY_USB_ADAPTERS:
            return 1
        if any(keyword in text for keyword in cls._PORT_KEYWORDS):
            return 2
        if vid is not None:
            return 20
        return 50

    @classmethod
    def _is_skipped_port(cls, info: object) -> bool:
        return any(keyword in cls._port_text(info) for keyword in cls._SKIP_KEYWORDS)

    @staticmethod
    def _port_text(info: object) -> str:
        parts = (
            getattr(info, "device", ""),
            getattr(info, "description", ""),
            getattr(info, "manufacturer", ""),
            getattr(info, "hwid", ""),
        )
        return " ".join(str(part or "") for part in parts).lower()
