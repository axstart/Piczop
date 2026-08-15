from __future__ import annotations

import errno
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.catalog import Catalog
from app.hashing import full_sha256, perceptual_hash, quick_key
from app.media_date import taken_at
from app.media_meta import enrich_path
from app.organize import ORIGIN_SCREENSHOT, classify_origin, smart_filename
from app.paths import assess_library_space, library_root, review_root
from app.scan import default_roots, iter_media
from app.settings import AppSettings

# Minimum completed files / elapsed seconds before ETA is shown.
_ETA_MIN_PROCESSED = 3
_ETA_MIN_ELAPSED = 1.0

# Windows winerror codes that mean disk full / drive gone / not ready.
_STORAGE_WINERRORS = {
    15,  # ERROR_INVALID_DRIVE
    19,  # ERROR_WRITE_PROTECT
    21,  # ERROR_NOT_READY
    112,  # ERROR_DISK_FULL
    433,  # ERROR_NO_SUCH_DEVICE
    1167,  # ERROR_DEVICE_NOT_CONNECTED
}
_STORAGE_ERRNOS = {errno.ENOSPC, errno.ENODEV, errno.EROFS}
if hasattr(errno, "ENOMEDIUM"):
    _STORAGE_ERRNOS.add(errno.ENOMEDIUM)


def format_eta(seconds: float | None) -> str:
    """Human-readable remaining-time estimate."""
    if seconds is None:
        return "Estimating…"
    if seconds < 5:
        return "Less than 5 sec left"
    if seconds < 60:
        return f"About {int(seconds)} sec left"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"About {minutes} min left"
    hours = minutes // 60
    mins = minutes % 60
    if mins:
        return f"About {hours}h {mins}m left"
    return f"About {hours}h left"


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
    # Progress / ETA (total is None while discovering files)
    total: int | None = None
    processed: int = 0
    remaining: int | None = None
    eta_seconds: float | None = None
    # Disk / USB graceful degradation
    abort_reason: str | None = None
    estimated_bytes: int | None = None
    space_warning: str | None = None

    @property
    def eta_text(self) -> str:
        return format_eta(self.eta_seconds)


class BackupCancelled(Exception):
    pass


class BackupStorageError(Exception):
    """Fatal disk-full / USB-removed style failure — stop the job with one message."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _library_drive_unreachable() -> bool:
    try:
        root = library_root()
        if not root.exists():
            return True
        from app.paths import drive_free_bytes

        drive_free_bytes(root)
        return False
    except OSError:
        return True


def _is_storage_oserror(exc: OSError) -> bool:
    if exc.errno in _STORAGE_ERRNOS:
        return True
    winerr = getattr(exc, "winerror", None)
    if winerr in _STORAGE_WINERRORS:
        return True
    msg = (exc.strerror or str(exc)).lower()
    needles = (
        "no space",
        "disk full",
        "not enough space",
        "device not ready",
        "device not connected",
        "the device is not ready",
        "cannot find the device",
    )
    if any(n in msg for n in needles):
        return True
    # Path-not-found mid-copy usually means the stick vanished — confirm via free-space probe.
    if winerr in (2, 3) or exc.errno == errno.ENOENT:
        return _library_drive_unreachable()
    return False


def _storage_message(exc: OSError) -> str:
    winerr = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerr == 112:
        return (
            "The library drive is full. Backup stopped so the same error "
            "is not repeated for every remaining file. Free up space and try again."
        )
    if winerr in (15, 21, 433, 1167) or exc.errno == errno.ENODEV:
        return (
            "The USB drive was removed or became unavailable. "
            "Backup cancelled. Reconnect the drive and run backup again."
        )
    return (
        f"Storage error — backup stopped: {exc}. "
        "Check that the library drive is connected and has free space."
    )


def _estimate_candidate_bytes(candidates: list[tuple[Path, str]]) -> int | None:
    total = 0
    any_ok = False
    for path, _kind in candidates:
        try:
            total += path.stat().st_size
            any_ok = True
        except OSError:
            continue
    return total if any_ok else None


class BackupJob:
    def __init__(self, catalog: Catalog, settings: AppSettings) -> None:
        self.catalog = catalog
        self.settings = settings
        self.stats = BackupStats()
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._rate_ema: float | None = None
        self._phase_started: float | None = None
        self._last_tick: float | None = None
        self._last_processed: int = 0

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

    def _reset_throughput(self) -> None:
        self._rate_ema = None
        self._phase_started = time.monotonic()
        self._last_tick = None
        self._last_processed = 0
        self.stats.eta_seconds = None

    def _update_progress_counts(self, *, discovering: bool) -> None:
        """Refresh total / processed / remaining / ETA on stats."""
        if discovering:
            self.stats.total = None
            self.stats.processed = 0
            self.stats.remaining = None
            self.stats.eta_seconds = None
            return

        total = self.stats.found
        processed = self.stats.copied + self.stats.skipped + self.stats.errors
        remaining = max(0, total - processed)
        self.stats.total = total
        self.stats.processed = processed
        self.stats.remaining = remaining

        now = time.monotonic()
        if self._phase_started is None:
            self._phase_started = now

        if self._last_tick is not None:
            dt = now - self._last_tick
            dp = processed - self._last_processed
            if dt > 0 and dp > 0:
                instant = dp / dt
                if self._rate_ema is None:
                    self._rate_ema = instant
                else:
                    self._rate_ema = 0.35 * instant + 0.65 * self._rate_ema

        self._last_tick = now
        self._last_processed = processed

        elapsed = now - self._phase_started
        if (
            remaining > 0
            and self._rate_ema
            and self._rate_ema > 0
            and processed >= _ETA_MIN_PROCESSED
            and elapsed >= _ETA_MIN_ELAPSED
        ):
            self.stats.eta_seconds = remaining / self._rate_ema
        elif remaining == 0 and total > 0:
            self.stats.eta_seconds = 0.0
        else:
            self.stats.eta_seconds = None

    def run(self, on_progress=None) -> BackupStats:
        backup_id = self.catalog.start_backup()
        try:
            roots = default_roots(self.settings)
            self.stats.phase = "scan"
            self._update_progress_counts(discovering=True)
            candidates: list[tuple[Path, str]] = []
            for path, kind in iter_media(
                roots, self.settings.include_videos, cancel_flag=self._cancel.is_set
            ):
                self._check()
                candidates.append((path, kind))
                self.stats.found = len(candidates)
                self.stats.current = str(path)
                self._update_progress_counts(discovering=True)
                if on_progress:
                    on_progress(self.stats)

            self._preflight_space(candidates)
            if on_progress:
                on_progress(self.stats)

            self.stats.phase = "copy"
            self.stats.found = len(candidates)
            self._reset_throughput()
            self._update_progress_counts(discovering=False)
            if on_progress:
                on_progress(self.stats)

            for path, kind in candidates:
                self._check()
                self.stats.current = str(path)
                if on_progress:
                    on_progress(self.stats)
                try:
                    self._process_file(path, kind)
                except BackupCancelled:
                    raise
                except BackupStorageError:
                    raise
                except OSError as exc:
                    if _is_storage_oserror(exc):
                        raise BackupStorageError(_storage_message(exc)) from exc
                    self.stats.errors += 1
                    self.stats.error_messages.append(f"{path}: {exc}")
                    if len(self.stats.error_messages) > 50:
                        self.stats.error_messages.pop(0)
                except Exception as exc:
                    self.stats.errors += 1
                    self.stats.error_messages.append(f"{path}: {exc}")
                    if len(self.stats.error_messages) > 50:
                        self.stats.error_messages.pop(0)
                self._update_progress_counts(discovering=False)
                if on_progress:
                    on_progress(self.stats)
        except BackupStorageError as exc:
            self.stats.abort_reason = exc.message
            self.stats.current = exc.message
            self.stats.errors += 1
            if not self.stats.error_messages or self.stats.error_messages[-1] != exc.message:
                self.stats.error_messages.append(exc.message)
        except BackupCancelled:
            if not self.stats.abort_reason:
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
            if self.stats.total is None and self.stats.found:
                self.stats.total = self.stats.found
            if self.stats.remaining is None and self.stats.total is not None:
                self.stats.processed = (
                    self.stats.copied + self.stats.skipped + self.stats.errors
                )
                self.stats.remaining = max(0, self.stats.total - self.stats.processed)
            if on_progress:
                on_progress(self.stats)
        return self.stats

    def _preflight_space(self, candidates: list[tuple[Path, str]]) -> None:
        """Block before copy when free space cannot cover found sizes (or floor)."""
        estimated = _estimate_candidate_bytes(candidates)
        self.stats.estimated_bytes = estimated
        try:
            level, _free, _total, message = assess_library_space(estimated)
        except OSError as exc:
            raise BackupStorageError(
                "Cannot read free space on the library drive. "
                "Is the USB still connected?\n\n"
                f"({exc})"
            ) from exc
        if level == "block":
            raise BackupStorageError(message)
        if level == "warn":
            self.stats.space_warning = message

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
