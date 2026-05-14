"""Persistent last-used directory storage for file dialogs."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

_ORG = "FiduciaLab"
_APP = "GeneSynthesizerDLP"

_KEYS = {
    "pattern_folder": "paths/pattern_folder",
    "save_log_dir":   "paths/save_log_dir",
    "test_image_dir": "paths/test_image_dir",
    "save_image_dir": "paths/save_image_dir",
}


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def get(key: str) -> str:
    """Return last-used directory for *key*, or '' if never set."""
    s = _settings()
    value = s.value(_KEYS[key], "")
    return value if isinstance(value, str) and os.path.isdir(value) else ""


def save(key: str, path: str) -> None:
    """Save *path* as the last-used directory for *key*.

    Accepts either a file path or a directory path — always stores the directory.
    """
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    if directory:
        s = _settings()
        s.setValue(_KEYS[key], directory)
        s.sync()
