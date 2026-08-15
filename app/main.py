from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.logging_setup import get_logger, setup_logging
from app.paths import library_root, resolve_library_root
from app.ui.main_window import MainWindow


def _icon_path() -> Path | None:
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "piczop.ico")
        candidates.append(Path(sys.executable).resolve().parent / "assets" / "piczop.ico")
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "assets" / "piczop.ico")
    for path in candidates:
        if path.is_file():
            return path
    return None


def main() -> int:
    _resolved, first_run = resolve_library_root()
    root = library_root()
    setup_logging(root, first_run=first_run)
    log = get_logger()
    log.info("event=app_start")
    app = QApplication(sys.argv)
    app.setApplicationName("Piczop")
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
