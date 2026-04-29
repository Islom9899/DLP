"""Gene Synthesizer control software (PySide6) - entry point."""
from __future__ import annotations

import os
import sys

from app.qt_environment import configure_qt_environment

if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
    os.environ.pop("QT_QPA_PLATFORM", None)

configure_qt_environment()

from PySide6.QtWidgets import QApplication

import app.constants as widgets_module  # alias: widgets_module._SCALE = scale ishlaydi
from pages.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    geometry = app.primaryScreen().availableGeometry()
    scale = min(geometry.width() / 1920.0, geometry.height() / 1080.0)
    widgets_module._SCALE = scale

    app.setStyle("Fusion")
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
