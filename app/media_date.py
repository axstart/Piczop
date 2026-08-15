from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags


_DATETIME_TAGS = {"DateTimeOriginal", "DateTimeDigitized", "DateTime"}


def file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def taken_at(path: Path) -> datetime:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
                for name in _DATETIME_TAGS:
                    raw = tags.get(name)
                    if raw:
                        parsed = _parse_exif_dt(str(raw))
                        if parsed:
                            return parsed
            ifd = getattr(exif, "get_ifd", None)
            if ifd:
                try:
                    from PIL.ExifTags import IFD

                    for ifd_id in (IFD.Exif, IFD.GPSInfo):
                        try:
                            nested = exif.get_ifd(ifd_id)
                        except Exception:
                            continue
                        nested_tags = {
                            ExifTags.TAGS.get(k, str(k)): v for k, v in nested.items()
                        }
                        for name in _DATETIME_TAGS:
                            raw = nested_tags.get(name)
                            if raw:
                                parsed = _parse_exif_dt(str(raw))
                                if parsed:
                                    return parsed
                except Exception:
                    pass
    except Exception:
        pass
    return file_mtime(path)


def _parse_exif_dt(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(raw[:19] if len(raw) >= 19 else raw, fmt)
        except ValueError:
            continue
    return None
