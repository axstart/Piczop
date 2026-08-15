from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from app.catalog import Catalog
from app.paths import library_root


def thumb_path(sha256: str) -> Path:
    """On-disk JPEG path — thumbs are never stored as SQLite BLOBs."""
    return library_root() / "thumbs" / f"{sha256}.jpg"


def ensure_thumb(sha256: str, source: Path, size: int = 240) -> Path | None:
    dest = thumb_path(sha256)
    if dest.exists():
        return dest
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(dest, "JPEG", quality=80)
        return dest
    except Exception:
        return None


def files_for_month(catalog: Catalog, year_month: str | None, kind: str | None = None):
    rows = catalog.list_files(kind=kind, primaries_only=True, limit=2000)
    if not year_month:
        return rows
    out = []
    for row in rows:
        stamp = row["taken_at"] or row["created_at"] or row["copied_at"] or ""
        if stamp.startswith(year_month):
            out.append(row)
    return out
