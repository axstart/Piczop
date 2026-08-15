"""Local-only structured logging for Piczop (no network / no phone-home)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "piczop"
_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB per file
_BACKUP_COUNT = 3  # ~8 MiB size cap with rotations

_configured = False
_log_file: Path | None = None


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_path() -> Path | None:
    return _log_file


def _library_mode(root: Path) -> str:
    from app.paths import APP_DIR_NAME, app_root

    beside = app_root() / APP_DIR_NAME
    try:
        if root.resolve() == beside.resolve():
            return "portable"
    except OSError:
        pass
    base = os.environ.get("LOCALAPPDATA")
    if base:
        appdata = Path(base) / "Piczop" / APP_DIR_NAME
        try:
            if root.resolve() == appdata.resolve():
                return "appdata"
        except OSError:
            pass
    return "other"


def setup_logging(
    library: Path | None = None,
    *,
    first_run: bool | None = None,
) -> Path | None:
    """
    Configure rotating file logging under ``<library>/logs/piczop.log``.

    Failures are swallowed so logging never blocks the app. Returns the log
    file path when configured, else None.
    """
    global _configured, _log_file
    if _configured:
        return _log_file

    try:
        from app.paths import library_root

        root = Path(library) if library is not None else library_root()
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / "piczop.log"

        logger = logging.getLogger(LOGGER_NAME)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = False

        handler = RotatingFileHandler(
            path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        # INFO/ERROR for normal events; DEBUG allowed for sampled current-file lines
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

        _log_file = path
        _configured = True

        mode = _library_mode(root)
        if first_run is None:
            logger.info("event=library_path mode=%s path=%s", mode, root)
        else:
            logger.info(
                "event=library_path mode=%s path=%s first_run=%s",
                mode,
                root,
                first_run,
            )
        return path
    except Exception:
        return None
