from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.catalog import Catalog
from app.hashing import full_sha256, perceptual_hash, quick_key
from app.media_date import taken_at
from app.media_meta import enrich_path
from app.organize import ORIGIN_SCREENSHOT, classify_origin, smart_filename
from app.paths import library_root, review_root
from app.scan import default_roots, iter_media
from app.settings import AppSettings


@dataclass
class BackupStats:
    found: int = 0
    copied: int = 0
    skipped: int = 0
    skipped_near: int = 0
    proposed_near: int = 0
    held_for_review: int = 0
    errors: int = 0
    bytes_copied: int = 0
    current: str = ""
    phase: str = "scan"
    finished: bool = False
    error_messages: list[str] = field(default_factory=list)


class BackupCancelled(Exception):
    pass


class BackupJob:
    def __init__(self, catalog: Catalog, settings: AppSettings) -> None:
        self.catalog = catalog
        self.settings = settings
        self.stats = BackupStats()
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()

    def toggle_pause(self) -> bool:
        if self._pause.is_set():
            self._pause.clear()
            return True
        self._pause.set()
        return False

    def _check(self) -> None:
        if self._cancel.is_set():
            raise BackupCancelled()
        self._pause.wait()
        if self._cancel.is_set():
            raise BackupCancelled()

    def run(self, on_progress=None) -> BackupStats:
        backup_id = self.catalog.start_backup()
        try:
            roots = default_roots(self.settings)
            self.stats.phase = "scan"
            candidates: list[tuple[Path, str]] = []
            for path, kind in iter_media(
                roots, self.settings.include_videos, cancel_flag=self._cancel.is_set
            ):
                self._check()
                candidates.append((path, kind))
                self.stats.found = len(candidates)
                self.stats.current = str(path)
                if on_progress:
                    on_progress(self.stats)

            self.stats.phase = "copy"
            for path, kind in candidates:
                self._check()
                self.stats.current = str(path)
                if on_progress:
                    on_progress(self.stats)
                try:
                    self._process_file(path, kind)
                except BackupCancelled:
                    raise
                except Exception as exc:
                    self.stats.errors += 1
                    self.stats.error_messages.append(f"{path}: {exc}")
                    if len(self.stats.error_messages) > 50:
                        self.stats.error_messages.pop(0)
                if on_progress:
                    on_progress(self.stats)
        except BackupCancelled:
            self.stats.current = "Cancelled"
        finally:
            self.catalog.finish_backup(
                backup_id,
                self.stats.copied,
                self.stats.skipped,
                self.stats.errors,
                self.stats.bytes_copied,
            )
            self.stats.phase = "done"
            self.stats.finished = True
            if on_progress:
                on_progress(self.stats)
        return self.stats

    def _process_file(self, path: Path, kind: str) -> None:
        size = path.stat().st_size
        qk = quick_key(path, size)
        known = self.catalog.hash_for_quick_key(qk)
        if known and self.catalog.has_hash(known):
            self.stats.skipped += 1
            return

        digest = full_sha256(path)
        self.catalog.remember_quick_key(qk, digest)
        if self.catalog.has_hash(digest):
            self.stats.skipped += 1
            return

        phash = perceptual_hash(path) if kind == "photo" else None
        near = self.catalog.find_near_duplicate(phash) if phash else None
        # Near-duplicates are never skipped or deleted here. They are copied
        # (into the library or review/) and queued for the Review page.

        origin = classify_origin(path)
        when = taken_at(path)
        meta = enrich_path(path)
        library_dest = self._destination(kind, when, path, digest, origin)
        hold = bool(near) and not self.settings.copy_similar_before_review
        if hold:
            dest = review_root() / library_dest.name
            n = 1
            while dest.exists():
                dest = review_root() / f"{library_dest.stem}_{n}{library_dest.suffix}"
                n += 1
            self.stats.held_for_review += 1
        else:
            dest = library_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

        review_status = None
        if near:
            review_status = "pending_review"
            self.stats.proposed_near += 1

        is_shot = origin == ORIGIN_SCREENSHOT
        tags = None if is_shot else meta["people_tags"]
        first = tags.split(",")[0].strip() if tags else None
        self.catalog.add_file(
            sha256=digest,
            size=size,
            taken_at=when,
            dest_path=dest,
            original_name=path.name,
            kind=kind,
            source_path=path,
            phash=phash,
            origin=origin,
            is_primary=True,
            duplicate_of=None,
            review_status=review_status,
            library_path=library_dest,
            gps_lat=meta["gps_lat"],
            gps_lon=meta["gps_lon"],
            loc_key=meta["loc_key"],
            person_label=first,
            person_id=(f"tag:{first.lower()}" if first else None),
            people_tags=tags,
            created_at=meta["created_at"],
        )
        if near:
            self.catalog.enqueue_near_pair(digest, near["sha256"])
        self.stats.copied += 1
        self.stats.bytes_copied += size

    def _destination(self, kind: str, when, path: Path, digest: str, origin: str) -> Path:
        folder = "photos" if kind == "photo" else "videos"
        name = smart_filename(when, origin, digest, path.suffix)
        return (
            library_root()
            / folder
            / f"{when.year:04d}"
            / f"{when.month:02d}"
            / name
        )
