"""HTTP client for Advanced Illumination DCS-100 lighting controllers."""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import socket
import subprocess
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DCSController:
    """JSON-over-HTTP client for DCS firmware that exposes /channels."""

    DEFAULT_IP = "192.168.0.1"
    DEFAULT_PORT = 80
    TIMEOUT = 3.0

    DEFAULT_MAX_CURRENT_MA = 400

    MODE_OFF = 0
    MODE_CONTINUOUS = 1
    MODE_PULSED = 2
    MODE_GATED = 3

    MODE_NAMES = {0: "Off", 1: "Continuous", 2: "Pulsed", 3: "Gated"}
    MODE_FROM_NAME = {"Off": 0, "Continuous": 1, "Pulsed": 2, "Gated": 3}

    CHANNELS = [1, 2, 3]

    def __init__(
        self,
        ip_address: str = DEFAULT_IP,
        port: int = DEFAULT_PORT,
        local_ip: str = "",
        channel: int = 1,
    ):
        self.ip_address = ip_address
        self.port = int(port)
        self.local_ip = local_ip.strip()
        self.channel = self._normalize_channel(channel)
        self.max_current_ma = self.DEFAULT_MAX_CURRENT_MA
        self._connected = False
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    @staticmethod
    def _normalize_channel(channel: Any) -> int:
        if channel is None:
            return 1
        if isinstance(channel, str):
            value = channel.strip().upper()
            if value.startswith("CHANNEL"):
                value = value[len("CHANNEL"):]
            elif value.startswith("CH"):
                value = value[len("CH"):]
            return int(value)
        return int(channel)

    @staticmethod
    def _local_ipv4_addresses() -> List[str]:
        addresses = set()

        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addresses.add(item[4][0])
        except OSError:
            pass

        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["ipconfig"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=2,
                    check=False,
                )
                addresses.update(re.findall(r"IPv4[^:]*:\s*([0-9]+(?:\.[0-9]+){3})", result.stdout))
            except Exception:
                pass

        return sorted(
            ip
            for ip in addresses
            if not ip.startswith("127.") and not ip.startswith("169.254.")
        )

    def _candidate_local_ips(self) -> List[str]:
        if self.local_ip:
            return [self.local_ip]

        candidates = [""]  # First try the OS default route.
        candidates.extend(ip for ip in self._local_ipv4_addresses() if ip not in candidates)
        return candidates

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        local_ip: Optional[str] = None,
    ) -> Any:
        bind_ip = self.local_ip if local_ip is None else local_ip
        source = (bind_ip, 0) if bind_ip else None
        conn = http.client.HTTPConnection(
            self.ip_address,
            self.port,
            timeout=self.TIMEOUT,
            source_address=source,
        )

        headers = {"Accept": "application/json", "Connection": "close"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(data))

        try:
            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            content = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

        if response.status not in (200, 201, 204):
            raise ConnectionError(f"HTTP {response.status} on {method} {path}: {content[:120]}")

        if not content.strip():
            return {}
        return json.loads(content)

    @staticmethod
    def _is_channels_payload(payload: Any) -> bool:
        return (
            isinstance(payload, list)
            and bool(payload)
            and all(isinstance(item, dict) and "id" in item for item in payload)
        )

    def _apply_channel_limits(self, channels: Any) -> None:
        if not isinstance(channels, list):
            return
        for item in channels:
            if not isinstance(item, dict) or item.get("id") != self.channel:
                continue
            max_cont = item.get("maxCont")
            if isinstance(max_cont, int) and max_cont > 0:
                self.max_current_ma = max_cont
            return

    def connect(self) -> bool:
        errors = []
        original_local_ip = self.local_ip

        for candidate_ip in self._candidate_local_ips():
            try:
                channels = self._request("GET", "/channels", local_ip=candidate_ip)
                if not self._is_channels_payload(channels):
                    raise ConnectionError("Unexpected /channels response")

                self.local_ip = candidate_ip
                self._apply_channel_limits(channels)
                self._connected = True
                bind_label = self.local_ip or "default route"
                logger.info("Connected to DCS at %s:%s via %s", self.ip_address, self.port, bind_label)
                return True
            except Exception as exc:
                label = candidate_ip or "default route"
                errors.append(f"{label}: {exc}")

        self.local_ip = original_local_ip
        self._connected = False
        logger.error("DCS connection failed: %s", " | ".join(errors))
        return False

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            self.get_channel_info()
            return True
        except Exception:
            self._connected = False
            return False

    def set_mode(self, mode: int, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        if mode not in self.MODE_NAMES:
            raise ValueError(f"Invalid mode {mode}. Use 0-3")
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"mode": int(mode)})

    def set_mode_by_name(self, mode_name: str, channel: Optional[int] = None) -> Any:
        if mode_name not in self.MODE_FROM_NAME:
            raise ValueError(f"Invalid mode name '{mode_name}'")
        return self.set_mode(self.MODE_FROM_NAME[mode_name], channel)

    def get_mode(self, channel: Optional[int] = None) -> int:
        data = self.get_channel_info(channel)
        return int(data.get("mode", 0))

    def set_level(self, level_ma: int, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        level_ma = max(0, min(self.max_current_ma, int(level_ma)))
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"current": level_ma})

    def get_level(self, channel: Optional[int] = None) -> int:
        data = self.get_channel_info(channel)
        return int(data.get("current", 0))

    def set_intensity_percent(self, percent: float, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        percent = max(0.0, min(100.0, float(percent)))
        level_ma = int(round(percent * self.max_current_ma / 100.0))
        mode = self.MODE_OFF if level_ma == 0 else self.MODE_CONTINUOUS
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"mode": mode, "current": level_ma})

    def set_pulse_width(self, width_us: int, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"pulseWidth": max(0, int(width_us))})

    def set_pulse_delay(self, delay_us: int, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"delay": max(0, int(delay_us))})

    def set_trigger_edge(self, rising: bool = True, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"trigger": 0 if rising else 1})

    def set_trigger_input(self, input_num: int, channel: Optional[int] = None) -> Any:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        with self._lock:
            return self._request("POST", f"/channels/{ch}", {"input": int(input_num)})

    def turn_on(self, mode: int = MODE_CONTINUOUS, channel: Optional[int] = None) -> Any:
        return self.set_mode(mode, channel)

    def turn_off(self, channel: Optional[int] = None) -> Any:
        return self.set_mode(self.MODE_OFF, channel)

    def turn_off_all(self) -> None:
        for ch in self.CHANNELS:
            try:
                self.turn_off(ch)
            except Exception:
                logger.debug("Failed to turn off DCS channel %s", ch, exc_info=True)

    def get_channel_info(self, channel: Optional[int] = None) -> Dict[str, Any]:
        ch = self._normalize_channel(channel) if channel is not None else self.channel
        data = self._request("GET", f"/channels/{ch}")
        return data if isinstance(data, dict) else {}

    def get_all_channels(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/channels")
        return data if isinstance(data, list) else []
