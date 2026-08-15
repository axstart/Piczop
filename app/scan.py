from __future__ import annotations

import os
from pathlib import Path

from app.paths import kind_for_suffix, library_root
from app.settings import AppSettings

SKIP_DIR_NAMES = {
    "$recycle.bin",
    "recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "appdata",
    "node_modules",
    ".git",
    "piczoplibrary",
}


def default_roots(settings: AppSettings) -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    mapping = [
        (settings.scan_pictures, home / "Pictures"),
        (settings.scan_videos, home / "Videos"),
        (settings.scan_desktop, home / "Desktop"),
        (settings.scan_downloads, home / "Downloads"),
        (settings.scan_documents, home / "Documents"),
    ]
    for enabled, path in mapping:
        if enabled and path.exists():
            roots.append(path)
    for extra in settings.extra_paths():
        if extra.exists():
            roots.append(extra)

    pictures = home / "Pictures"
    camera_roll = pictures / "Camera Roll"
    if camera_roll.exists() and camera_roll not in roots:
        roots.append(camera_roll)

    for drive in _windows_drives():
        dcim = drive / "DCIM"
        if dcim.exists() and dcim not in roots:
            roots.append(dcim)
    return _unique(roots)


def _windows_drives() -> list[Path]:
    drives: list[Path] = []
    if os.name != "nt":
        return drives
    import string

    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:/")
        if p.exists():
            drives.append(p)
    return drives


def _unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def should_skip_dir(path: Path) -> bool:
    name = path.name.lower()
    if name in SKIP_DIR_NAMES:
        return True
    try:
        lib = library_root().resolve()
        resolved = path.resolve()
        if resolved == lib or lib in resolved.parents:
            return True
    except Exception:
        pass
    return False


def iter_media(roots: list[Path], include_videos: bool, cancel_flag=None):
    lib = library_root().resolve()
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if cancel_flag and cancel_flag():
                return
            current = Path(dirpath)
            try:
                resolved = current.resolve()
                if resolved == lib or lib in resolved.parents:
                    dirnames[:] = []
                    continue
            except Exception:
                pass
            dirnames[:] = [d for d in dirnames if not should_skip_dir(current / d)]
            for name in filenames:
                if cancel_flag and cancel_flag():
                    return
                path = current / name
                kind = kind_for_suffix(path.suffix)
                if not kind:
                    continue
                if kind == "video" and not include_videos:
                    continue
                yield path, kind
