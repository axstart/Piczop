from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_DIR_NAME = "PiczopLibrary"
PHOTO_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".cr2",
    ".nef",
    ".arw",
    ".dng",
    ".rw2",
    ".orf",
}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".m4v", ".mkv", ".wmv"}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _local_appdata_library() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Piczop" / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / "Piczop" / APP_DIR_NAME


def _can_use_library_at(root: Path) -> bool:
    """True when we can create the library folder and write inside it."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".piczop_write_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _bundled_library_template() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / APP_DIR_NAME)
        candidates.append(Path(sys.executable).resolve().parent / "_internal" / APP_DIR_NAME)
        candidates.append(Path(sys.executable).resolve().parent / APP_DIR_NAME)
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "assets" / APP_DIR_NAME)
    for path in candidates:
        if path.is_dir():
            return path
    return None


def resolve_library_root() -> tuple[Path, bool]:
    """Return (library path, first_run). Prefer next-to-exe when writable; else LocalAppData."""
    beside_exe = app_root() / APP_DIR_NAME
    beside_existed = beside_exe.exists()
    if _can_use_library_at(beside_exe):
        return beside_exe, not beside_existed
    if getattr(sys, "frozen", False):
        appdata = _local_appdata_library()
        return appdata, not appdata.exists()
    return beside_exe, not beside_existed


def library_root() -> Path:
    """Media library for photos/videos/catalog. Never inside _MEIPASS."""
    root, first_run = resolve_library_root()
    if first_run:
        template = _bundled_library_template()
        if template is not None:
            shutil.copytree(template, root, dirs_exist_ok=True)
        else:
            root.mkdir(parents=True, exist_ok=True)
    else:
        root.mkdir(parents=True, exist_ok=True)
    for name in ("photos", "videos", "thumbs", "review", "trash"):
        (root / name).mkdir(exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        template = _bundled_library_template()
        src = template / "README.txt" if template else None
        if src and src.is_file():
            shutil.copy2(src, readme)
        else:
            readme.write_text(
                "Piczop library folder. Photos and videos copied here stay on this drive.\n",
                encoding="utf-8",
            )
    return root


def catalog_path() -> Path:
    return library_root() / "catalog.db"


def review_root() -> Path:
    root = library_root() / "review"
    root.mkdir(parents=True, exist_ok=True)
    return root


def trash_root() -> Path:
    root = library_root() / "trash"
    root.mkdir(parents=True, exist_ok=True)
    return root


def settings_path() -> Path:
    return library_root() / "settings.json"


def is_removable_drive(path: Path | None = None) -> bool:
    target = (path or app_root()).drive or str(path or app_root())
    if os.name != "nt":
        return False
    try:
        import ctypes

        drive = target[:2]
        if len(drive) < 2 or drive[1] != ":":
            return False
        dtype = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        return dtype == 2  # DRIVE_REMOVABLE
    except Exception:
        return False


def drive_free_bytes(path: Path | None = None) -> tuple[int, int]:
    target = path or library_root()
    usage = os.statvfs(target) if hasattr(os, "statvfs") else None
    if usage:
        return usage.f_bavail * usage.f_frsize, usage.f_blocks * usage.f_frsize
    import shutil

    du = shutil.disk_usage(target)
    return du.free, du.total


def format_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def kind_for_suffix(suffix: str) -> str | None:
    ext = suffix.lower()
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    return None
