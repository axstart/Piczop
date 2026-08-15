from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.catalog import Catalog
from app.paths import library_root


@dataclass
class Suggestion:
    kind: str
    key: str
    title: str
    count: int
    target: str
    shas: list[str]


_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_name(name: str) -> str:
    cleaned = _SAFE.sub("_", name).strip(" ._")
    return cleaned or "Unknown"


def _when(row) -> datetime | None:
    raw = row["taken_at"] or row["created_at"] or row["copied_at"]
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)[:19])
    except ValueError:
        return None


def month_suggestions(catalog: Catalog) -> list[Suggestion]:
    out: list[Suggestion] = []
    for ym, n in catalog.months():
        if not ym or ym == "Unknown":
            continue
        rows = catalog.list_files_matching(year_month=ym)
        out.append(
            Suggestion(
                kind="month",
                key=ym,
                title=f"{ym} · by date",
                count=n,
                target=f"photos/{ym.replace('-', '/')}/  (and videos/…)",
                shas=[r["sha256"] for r in rows],
            )
        )
    return out


def screenshot_suggestions(catalog: Catalog) -> list[Suggestion]:
    rows = catalog.list_files_matching(origin="screenshot", primaries_only=True)
    if not rows:
        return []
    return [
        Suggestion(
            kind="screenshot",
            key="all",
            title="Screenshots · keep separate from people",
            count=len(rows),
            target="photos/Screenshots/YYYY/MM/",
            shas=[r["sha256"] for r in rows],
        )
    ]


def people_suggestions(catalog: Catalog) -> list[Suggestion]:
    out: list[Suggestion] = []
    for pid, label, n in catalog.person_groups():
        rows = [
            r
            for r in catalog.list_files_matching(person_id=pid)
            if (r["origin"] or "") != "screenshot"
        ]
        if not rows:
            continue
        folder = _safe_name(label)
        out.append(
            Suggestion(
                kind="person",
                key=pid,
                title=f"{label} · by person (camera photos only)",
                count=len(rows),
                target=f"photos/People/{folder}/",
                shas=[r["sha256"] for r in rows],
            )
        )
    return out


def place_suggestions(catalog: Catalog) -> list[Suggestion]:
    out: list[Suggestion] = []
    for key, n in catalog.location_groups():
        rows = catalog.list_files_matching(loc_key=key)
        if key == "none":
            title = "No location"
            target = "(no GPS — skipped unless you apply a date suggestion)"
        else:
            title = f"{key} · GPS cluster"
            target = f"photos/YYYY/loc_{_safe_name(key)}/"
        out.append(
            Suggestion(
                kind="place",
                key=key,
                title=title,
                count=n,
                target=target,
                shas=[r["sha256"] for r in rows],
            )
        )
    return out


def apply_suggestion(catalog: Catalog, suggestion: Suggestion) -> int:
    if suggestion.kind == "place" and suggestion.key == "none":
        return 0
    moved = 0
    for sha in suggestion.shas:
        row = catalog.get_file(sha)
        if not row or row["trashed"]:
            continue
        dest = _target_path(row, suggestion)
        src = Path(row["dest_path"])
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == src.resolve():
            catalog.set_library_path(sha, dest)
            continue
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}_org{dest.suffix}")
        shutil.move(str(src), str(dest))
        catalog.set_library_path(sha, dest)
        moved += 1
    return moved


def _target_path(row, suggestion: Suggestion) -> Path:
    when = _when(row) or datetime.now()
    year = f"{when.year:04d}"
    month = f"{when.month:02d}"
    name = Path(row["dest_path"]).name
    kind_folder = "photos" if row["kind"] == "photo" else "videos"
    root = library_root() / kind_folder
    if suggestion.kind == "month":
        parts = suggestion.key.split("-")
        y, m = (parts + [month])[:2]
        return root / y / m / name
    if suggestion.kind == "person":
        label = row["person_label"] or suggestion.title.split(" ·")[0]
        return root / "People" / _safe_name(label) / name
    if suggestion.kind == "screenshot":
        return root / "Screenshots" / year / month / name
    loc = _safe_name(suggestion.key)
    return root / year / f"loc_{loc}" / name
