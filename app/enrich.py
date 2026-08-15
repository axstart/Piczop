from __future__ import annotations

from pathlib import Path

from app.catalog import Catalog
from app.media_meta import enrich_path
from app.organize import ORIGIN_SCREENSHOT, classify_origin
from app.people import cluster_face_hashes, extract_face_hashes, face_engine_available


def enrich_library(catalog: Catalog, on_progress=None) -> dict:
    """Fill GPS, created_at, EXIF people tags, screenshot tags, optional face clusters."""
    rows = catalog.list_files(primaries_only=False, limit=20000)
    face_pairs: list[tuple[str, str]] = []
    tagged = 0
    gps_n = 0
    faces_n = 0
    shots = 0
    opencv = face_engine_available()
    total = max(len(rows), 1)
    for i, row in enumerate(rows):
        if on_progress:
            on_progress(i + 1, total)
        dest = Path(row["dest_path"])
        source = Path(row["source_path"] or dest)
        probe = source if source.exists() else dest
        if not dest.exists() and not source.exists():
            continue
        origin = classify_origin(probe if probe.exists() else dest)
        catalog.set_origin(row["sha256"], origin)
        meta = enrich_path(dest if dest.exists() else probe)
        is_shot = origin == ORIGIN_SCREENSHOT
        if is_shot:
            shots += 1
            catalog.clear_person(row["sha256"])
        person_id = None
        person_label = None
        tags = meta["people_tags"] if not is_shot else None
        if tags:
            first = tags.split(",")[0].strip()
            person_id = f"tag:{first.lower()}"
            person_label = first
            tagged += 1
        if meta["gps_lat"] is not None:
            gps_n += 1
        catalog.update_file_meta(
            row["sha256"],
            gps_lat=meta["gps_lat"],
            gps_lon=meta["gps_lon"],
            loc_key=meta["loc_key"],
            person_id=person_id,
            person_label=person_label,
            people_tags=tags,
            created_at=meta["created_at"],
        )
        if (
            opencv
            and row["kind"] == "photo"
            and not is_shot
            and not person_id
        ):
            hashes = extract_face_hashes(dest if dest.exists() else probe)
            if hashes:
                faces_n += 1
                face_pairs.append((row["sha256"], hashes[0]))
    mapping = cluster_face_hashes(face_pairs)
    for sha, pid in mapping.items():
        catalog.assign_person(sha, pid, f"Person {pid[1:]}")
    return {
        "files": len(rows),
        "gps": gps_n,
        "named_tags": tagged,
        "faces": faces_n,
        "clusters": len(set(mapping.values())),
        "screenshots": shots,
        "opencv": opencv,
    }
