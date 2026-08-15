from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags

from app.media_date import taken_at


def file_created_at(path: Path) -> datetime:
    st = path.stat()
    ts = getattr(st, "st_birthtime", None) or st.st_ctime
    return datetime.fromtimestamp(ts)


def _ratio_to_float(value) -> float:
    if hasattr(value, "numerator"):
        return float(value.numerator) / float(value.denominator or 1)
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1] or 1)
    return float(value)


def _dms_to_deg(values, ref: str) -> float | None:
    try:
        parts = list(values)
        if len(parts) < 3:
            return None
        deg = _ratio_to_float(parts[0])
        minutes = _ratio_to_float(parts[1])
        seconds = _ratio_to_float(parts[2])
        sign = -1.0 if str(ref).upper() in {"S", "W"} else 1.0
        return sign * (deg + minutes / 60.0 + seconds / 3600.0)
    except Exception:
        return None


def gps_from_exif(path: Path) -> tuple[float, float] | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            from PIL.ExifTags import IFD, GPSTAGS

            try:
                gps = exif.get_ifd(IFD.GPSInfo)
            except Exception:
                gps = None
            if not gps:
                return None
            named = {GPSTAGS.get(k, str(k)): v for k, v in gps.items()}
            lat = _dms_to_deg(named.get("GPSLatitude") or (), named.get("GPSLatitudeRef") or "N")
            lon = _dms_to_deg(named.get("GPSLongitude") or (), named.get("GPSLongitudeRef") or "E")
            if lat is None or lon is None:
                return None
            if abs(lat) > 90 or abs(lon) > 180:
                return None
            return lat, lon
    except Exception:
        return None


def loc_key(lat: float, lon: float, decimals: int = 2) -> str:
    return f"{lat:.{decimals}f},{lon:.{decimals}f}"


_PERSON_PATTERNS = (
    re.compile(r"<mwg-rs:Name>([^<]+)</mwg-rs:Name>", re.I),
    re.compile(r"<Iptc4xmpExt:PersonInImage>([^<]+)</Iptc4xmpExt:PersonInImage>", re.I),
    re.compile(r"PersonInImage[^>]*>([^<]+)<", re.I),
    re.compile(r"MicrosoftPhoto:RegionInfo[\s\S]{0,400}?Name>([^<]+)<", re.I),
)


def people_tags_from_xmp(path: Path) -> list[str]:
    names: list[str] = []
    try:
        with Image.open(path) as img:
            blob = ""
            getter = getattr(img, "getxmp", None)
            if callable(getter):
                try:
                    blob = str(getter() or "")
                except Exception:
                    blob = ""
            if not blob:
                blob = str(img.info.get("XML:com.adobe.xmp") or "")
            if not blob:
                return []
            for pat in _PERSON_PATTERNS:
                for match in pat.findall(blob):
                    name = str(match).strip()
                    if name and name not in names:
                        names.append(name)
    except Exception:
        return []
    return names


def enrich_path(path: Path) -> dict:
    gps = gps_from_exif(path)
    tags = people_tags_from_xmp(path)
    created = file_created_at(path)
    when = taken_at(path)
    make, model, size = camera_and_size(path)
    return {
        "gps_lat": gps[0] if gps else None,
        "gps_lon": gps[1] if gps else None,
        "loc_key": loc_key(*gps) if gps else None,
        "people_tags": ", ".join(tags) if tags else None,
        "created_at": created.isoformat(timespec="seconds"),
        "taken_at": when,
        "camera_make": make,
        "camera_model": model,
        "pixel_size": size,
    }


def camera_and_size(path: Path) -> tuple[str | None, str | None, tuple[int, int] | None]:
    try:
        with Image.open(path) as img:
            size = img.size
            exif = img.getexif()
            if not exif:
                return None, None, size
            tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
            make = str(tags.get("Make") or "").strip() or None
            model = str(tags.get("Model") or "").strip() or None
            return make, model, size
    except Exception:
        return None, None, None
