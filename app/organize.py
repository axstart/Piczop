from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.media_meta import camera_and_size, gps_from_exif


ORIGIN_CAMERA = "camera"
ORIGIN_SCREENSHOT = "screenshot"
ORIGIN_DOWNLOAD = "download"
ORIGIN_OTHER = "other"

_SCREENSHOT_HINTS = (
    "screenshot",
    "screen shot",
    "screen-shot",
    "screenshots",
    "screengrab",
    "snip",
    "snipping",
    "screenclip",
    "screen clip",
)
_CAPTURE_NAMES = ("capture", "snip", "annotation", "screenclip")
_DOWNLOAD_HINTS = ("download", "downloads")
_WHATSAPP_HINTS = ("whatsapp", "\\wa\\", "/wa/", "telegram", "signal")
_CAMERA_HINTS = (
    "dcim",
    "camera roll",
    "cameraroll",
    "100canon",
    "100nd800",
    "100msdcf",
)
_IOS_SCREENSHOT_FOLDERS = ("\\screenshots\\", "/screenshots/", "\\screenshot\\")
_COMMON_MONITOR = {
    (1920, 1080),
    (1920, 1200),
    (1366, 768),
    (1536, 864),
    (2560, 1440),
    (2560, 1600),
    (1280, 720),
    (1280, 800),
    (1440, 900),
    (1680, 1050),
    (3840, 2160),
    (2560, 1080),
    (3440, 1440),
}


def classify_origin(path: Path) -> str:
    blob = str(path).lower().replace("/", "\\")
    name = path.name.lower()
    stem = path.stem.lower()

    if any(h in blob for h in _WHATSAPP_HINTS) or name.startswith("img-"):
        return ORIGIN_DOWNLOAD

    if any(h in blob or h in name for h in _SCREENSHOT_HINTS):
        return ORIGIN_SCREENSHOT
    if name.startswith("screenshot") or name.startswith("screen shot"):
        return ORIGIN_SCREENSHOT
    if any(f in blob for f in _IOS_SCREENSHOT_FOLDERS) and name.startswith("img_"):
        return ORIGIN_SCREENSHOT
    if any(stem.startswith(p) or p in stem for p in _CAPTURE_NAMES):
        return ORIGIN_SCREENSHOT

    if any(h in blob for h in _CAMERA_HINTS):
        return ORIGIN_CAMERA
    if path.suffix.lower() in {".cr2", ".nef", ".arw", ".dng", ".rw2", ".orf"}:
        return ORIGIN_CAMERA
    if name.startswith(("dsc_", "dscn", "pict", "p00")):
        return ORIGIN_CAMERA

    if any(h in blob for h in _DOWNLOAD_HINTS):
        return ORIGIN_DOWNLOAD

    make, model, size = camera_and_size(path)
    gps = gps_from_exif(path)
    if make or model or gps:
        if name.startswith("img_"):
            return ORIGIN_CAMERA
        return ORIGIN_CAMERA

    desktop = "\\desktop\\" in blob
    png = path.suffix.lower() == ".png"
    if desktop and png and (any(p in stem for p in _CAPTURE_NAMES) or name.startswith("image")):
        return ORIGIN_SCREENSHOT

    if _ui_like_screenshot(size, png, desktop):
        return ORIGIN_SCREENSHOT

    if name.startswith("img_"):
        return ORIGIN_CAMERA
    return ORIGIN_OTHER


def _ui_like_screenshot(size: tuple[int, int] | None, png: bool, desktop: bool) -> bool:
    if not size:
        return False
    w, h = size
    if w < 400 or h < 400:
        return False
    wide, tall = max(w, h), min(w, h)
    ratio = wide / tall
    if (w, h) in _COMMON_MONITOR or (h, w) in _COMMON_MONITOR:
        return True
    if ratio >= 2.45 and (png or desktop):
        return True
    return False


def origin_label(origin: str) -> str:
    return {
        ORIGIN_CAMERA: "Camera",
        ORIGIN_SCREENSHOT: "Screenshot",
        ORIGIN_DOWNLOAD: "Download",
        ORIGIN_OTHER: "Photo",
    }.get(origin, "Photo")


def smart_filename(when: datetime, origin: str, digest: str, suffix: str) -> str:
    stamp = when.strftime("%Y-%m-%d_%H%M%S")
    label = origin_label(origin)
    short = digest[:8]
    ext = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
    return f"{stamp}_{label}_{short}{ext}"
