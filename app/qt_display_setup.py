"""Qt runtime environment defaults."""
from __future__ import annotations

import os
from pathlib import Path


def configure_qt_environment() -> None:
    """Set Qt defaults that must exist before QApplication is created."""
    if os.name != "nt" or os.environ.get("QT_QPA_FONTDIR"):
        return

    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if font_dir.is_dir():
        os.environ["QT_QPA_FONTDIR"] = str(font_dir)
