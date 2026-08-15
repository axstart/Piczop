from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.hashing import NEAR_DUP_HAMMING, NearDupIndex
from app.paths import catalog_path, trash_root


STATUS_PENDING = "pending_review"
STATUS_CONFIRMED = "confirmed_duplicate"
STATUS_DISMISSED = "dismissed"
STATUS_MERGED = "merged"

# Relational metadata only — thumbnails live on disk under library/thumbs/, never BLOBs.
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    sha256 TEXT UNIQUE NOT NULL,
    size INTEGER NOT NULL,
    taken_at TEXT,
    dest_path TEXT NOT NULL,
    original_name TEXT,
    kind TEXT NOT NULL,
    copied_at TEXT NOT NULL,
    source_path TEXT,
    phash TEXT,
    origin TEXT,
    is_primary INTEGER DEFAULT 1,
    duplicate_of TEXT,
    review_status TEXT,
    library_path TEXT,
    restore_path TEXT,
    trashed INTEGER DEFAULT 0,
    gps_lat REAL,
    gps_lon REAL,
    loc_key TEXT,
    person_id TEXT,
    person_label TEXT,
    people_tags TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ui_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS persons (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quick_keys (
    quick_key TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    copied INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    bytes INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_groups (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_members (
    group_id INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (group_id, sha256)
);

CREATE INDEX IF NOT EXISTS idx_files_taken ON files(taken_at);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind);
CREATE INDEX IF NOT EXISTS idx_files_phash ON files(phash);
CREATE INDEX IF NOT EXISTS idx_files_origin ON files(origin);
CREATE INDEX IF NOT EXISTS idx_files_loc ON files(loc_key);
CREATE INDEX IF NOT EXISTS idx_files_person ON files(person_id);
CREATE INDEX IF NOT EXISTS idx_review_members_sha ON review_members(sha256);
"""

_MIGRATIONS = [
    "ALTER TABLE files ADD COLUMN phash TEXT",
    "ALTER TABLE files ADD COLUMN origin TEXT",
    "ALTER TABLE files ADD COLUMN is_primary INTEGER DEFAULT 1",
    "ALTER TABLE files ADD COLUMN duplicate_of TEXT",
    "ALTER TABLE files ADD COLUMN review_status TEXT",
    "ALTER TABLE files ADD COLUMN library_path TEXT",
    "ALTER TABLE files ADD COLUMN restore_path TEXT",
    "ALTER TABLE files ADD COLUMN trashed INTEGER DEFAULT 0",
    "ALTER TABLE files ADD COLUMN gps_lat REAL",
    "ALTER TABLE files ADD COLUMN gps_lon REAL",
    "ALTER TABLE files ADD COLUMN loc_key TEXT",
    "ALTER TABLE files ADD COLUMN person_id TEXT",
    "ALTER TABLE files ADD COLUMN person_label TEXT",
    "ALTER TABLE files ADD COLUMN people_tags TEXT",
    "ALTER TABLE files ADD COLUMN created_at TEXT",
]


class Catalog:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or catalog_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
        self.seed_unreviewed_groups()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for sql in _MIGRATIONS:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

    @contextmanager
    def connect(self):
        # WAL + busy_timeout: catalog often lives on USB; tolerate brief locks/flakes.
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def load_near_dup_index(self) -> NearDupIndex:
        """Load all active photo pHashes once (e.g. start of a backup job)."""
        index = NearDupIndex()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, sha256, phash, COALESCE(is_primary, 1) AS is_primary, size
                FROM files
                WHERE phash IS NOT NULL AND kind = 'photo' AND COALESCE(trashed, 0) = 0
                ORDER BY is_primary DESC, size DESC, id ASC
                """
            ).fetchall()
        for row in rows:
            index.add(
                sha256=row["sha256"],
                phash=row["phash"],
                is_primary=row["is_primary"],
                size=row["size"],
                id=row["id"],
            )
        return index

    def has_hash(self, sha256: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM files WHERE sha256 = ? AND COALESCE(trashed, 0) = 0",
                (sha256,),
            ).fetchone()
            return row is not None

    def get_file(self, sha256: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM files WHERE sha256 = ?", (sha256,)
            ).fetchone()

    def hash_for_quick_key(self, quick_key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT sha256 FROM quick_keys WHERE quick_key = ?", (quick_key,)
            ).fetchone()
            return row["sha256"] if row else None

    def remember_quick_key(self, quick_key: str, sha256: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO quick_keys(quick_key, sha256) VALUES (?, ?)",
                (quick_key, sha256),
            )

    def add_file(
        self,
        sha256: str,
        size: int,
        taken_at: datetime | None,
        dest_path: Path,
        original_name: str,
        kind: str,
        source_path: Path,
        phash: str | None = None,
        origin: str | None = None,
        is_primary: bool = True,
        duplicate_of: str | None = None,
        review_status: str | None = None,
        library_path: Path | str | None = None,
        gps_lat: float | None = None,
        gps_lon: float | None = None,
        loc_key: str | None = None,
        person_id: str | None = None,
        person_label: str | None = None,
        people_tags: str | None = None,
        created_at: datetime | str | None = None,
    ) -> None:
        lib = str(library_path) if library_path else str(dest_path)
        created = created_at
        if isinstance(created, datetime):
            created = created.isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO files
                (sha256, size, taken_at, dest_path, original_name, kind, copied_at,
                 source_path, phash, origin, is_primary, duplicate_of, review_status,
                 library_path, trashed, gps_lat, gps_lon, loc_key, person_id,
                 person_label, people_tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sha256,
                    size,
                    taken_at.isoformat() if taken_at else None,
                    str(dest_path),
                    original_name,
                    kind,
                    datetime.now().isoformat(timespec="seconds"),
                    str(source_path),
                    phash,
                    origin,
                    1 if is_primary else 0,
                    duplicate_of,
                    review_status,
                    lib,
                    gps_lat,
                    gps_lon,
                    loc_key,
                    person_id,
                    person_label,
                    people_tags,
                    created,
                ),
            )

    def find_near_duplicate(
        self,
        phash: str | None,
        threshold: int = NEAR_DUP_HAMMING,
        index: NearDupIndex | None = None,
    ) -> sqlite3.Row | dict | None:
        if not phash:
            return None
        if index is not None:
            hit = index.find(phash, threshold=threshold)
            return hit.as_row() if hit else None
        # One-shot callers: build a band index for this lookup instead of O(n) scan.
        built = self.load_near_dup_index()
        hit = built.find(phash, threshold=threshold)
        if not hit:
            return None
        return self.get_file(hit.sha256)

    def mark_duplicate(self, sha256: str, primary_sha: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files SET is_primary = 0, duplicate_of = ?,
                    review_status = ?
                WHERE sha256 = ?
                """,
                (primary_sha, STATUS_CONFIRMED, sha256),
            )

    def pending_group_id_for(self, sha256: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT g.id FROM review_groups g
                JOIN review_members m ON m.group_id = g.id
                WHERE m.sha256 = ? AND g.status = ?
                """,
                (sha256, STATUS_PENDING),
            ).fetchone()
            return int(row["id"]) if row else None

    def enqueue_near_pair(self, sha_a: str, sha_b: str) -> int:
        ga = self.pending_group_id_for(sha_a)
        gb = self.pending_group_id_for(sha_b)
        with self.connect() as conn:
            if ga and gb and ga != gb:
                conn.execute(
                    "UPDATE review_members SET group_id = ? WHERE group_id = ?",
                    (ga, gb),
                )
                conn.execute("DELETE FROM review_groups WHERE id = ?", (gb,))
                group_id = ga
            elif ga:
                group_id = ga
            elif gb:
                group_id = gb
            else:
                cur = conn.execute(
                    "INSERT INTO review_groups(status, created_at) VALUES (?, ?)",
                    (STATUS_PENDING, datetime.now().isoformat(timespec="seconds")),
                )
                group_id = int(cur.lastrowid)
            for sha in (sha_a, sha_b):
                conn.execute(
                    "INSERT OR IGNORE INTO review_members(group_id, sha256) VALUES (?, ?)",
                    (group_id, sha),
                )
                conn.execute(
                    """
                    UPDATE files SET review_status = ?
                    WHERE sha256 = ? AND (review_status IS NULL OR review_status = ?)
                    """,
                    (STATUS_PENDING, sha, STATUS_PENDING),
                )
        return group_id

    def seed_unreviewed_groups(self) -> None:
        for group in self.duplicate_groups():
            decided = {
                STATUS_CONFIRMED,
                STATUS_DISMISSED,
                STATUS_MERGED,
            }
            if any((r["review_status"] or "") in decided for r in group):
                continue
            if all(self.pending_group_id_for(r["sha256"]) for r in group):
                continue
            first = group[0]["sha256"]
            for other in group[1:]:
                self.enqueue_near_pair(first, other["sha256"])

    def pending_review_count(self) -> int:
        return len(self.pending_review_groups())

    def pending_review_groups(self) -> list[tuple[int, list[sqlite3.Row]]]:
        with self.connect() as conn:
            groups = conn.execute(
                "SELECT id FROM review_groups WHERE status = ? ORDER BY id DESC",
                (STATUS_PENDING,),
            ).fetchall()
            out = []
            for g in groups:
                members = conn.execute(
                    """
                    SELECT f.* FROM files f
                    JOIN review_members m ON m.sha256 = f.sha256
                    WHERE m.group_id = ? AND COALESCE(f.trashed, 0) = 0
                    ORDER BY f.size DESC, f.id ASC
                    """,
                    (g["id"],),
                ).fetchall()
                if len(members) >= 2:
                    out.append((int(g["id"]), members))
        return out

    def set_group_status(self, group_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE review_groups SET status = ? WHERE id = ?",
                (status, group_id),
            )

    def keep_all(self, group_id: int) -> None:
        members = self._group_members(group_id)
        with self.connect() as conn:
            for row in members:
                conn.execute(
                    """
                    UPDATE files SET review_status = ?, is_primary = 1, duplicate_of = NULL
                    WHERE sha256 = ?
                    """,
                    (STATUS_DISMISSED, row["sha256"]),
                )
            conn.execute(
                "UPDATE review_groups SET status = ? WHERE id = ?",
                (STATUS_DISMISSED, group_id),
            )
        for row in members:
            self.promote_to_library(row["sha256"])

    def keep_primary(self, group_id: int, primary_sha: str) -> None:
        members = self._group_members(group_id)
        with self.connect() as conn:
            for row in members:
                if row["sha256"] == primary_sha:
                    conn.execute(
                        """
                        UPDATE files SET is_primary = 1, duplicate_of = NULL,
                            review_status = ?
                        WHERE sha256 = ?
                        """,
                        (STATUS_DISMISSED, primary_sha),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE files SET is_primary = 0, duplicate_of = ?,
                            review_status = ?
                        WHERE sha256 = ?
                        """,
                        (primary_sha, STATUS_CONFIRMED, row["sha256"]),
                    )
            conn.execute(
                "UPDATE review_groups SET status = ? WHERE id = ?",
                (STATUS_CONFIRMED, group_id),
            )
        self.promote_to_library(primary_sha)

    def merge_or_delete_extras(self, group_id: int, primary_sha: str) -> list[str]:
        self.keep_primary(group_id, primary_sha)
        members = self._group_members(group_id)
        moved: list[str] = []
        for row in members:
            if row["sha256"] == primary_sha:
                continue
            if self.trash_file(row["sha256"]):
                moved.append(row["original_name"] or Path(row["dest_path"]).name)
        with self.connect() as conn:
            conn.execute(
                "UPDATE files SET review_status = ? WHERE duplicate_of = ?",
                (STATUS_MERGED, primary_sha),
            )
            conn.execute(
                "UPDATE review_groups SET status = ? WHERE id = ?",
                (STATUS_MERGED, group_id),
            )
        return moved

    def group_members(self, group_id: int) -> list[sqlite3.Row]:
        return self._group_members(group_id)

    def _group_members(self, group_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT f.* FROM files f
                JOIN review_members m ON m.sha256 = f.sha256
                WHERE m.group_id = ?
                ORDER BY f.size DESC, f.id ASC
                """,
                (group_id,),
            ).fetchall()

    def promote_to_library(self, sha256: str) -> None:
        row = self.get_file(sha256)
        if not row or row["trashed"]:
            return
        dest = Path(row["dest_path"])
        intended = Path(row["library_path"] or row["dest_path"])
        if dest.resolve() == intended.resolve():
            return
        if not dest.exists():
            return
        intended.parent.mkdir(parents=True, exist_ok=True)
        if intended.exists() and intended.resolve() != dest.resolve():
            intended = intended.with_name(f"{intended.stem}_keep{intended.suffix}")
        shutil.move(str(dest), str(intended))
        with self.connect() as conn:
            conn.execute(
                "UPDATE files SET dest_path = ? WHERE sha256 = ?",
                (str(intended), sha256),
            )

    def trash_file(self, sha256: str) -> bool:
        row = self.get_file(sha256)
        if not row:
            return False
        src = Path(row["dest_path"])
        trash = trash_root()
        name = src.name
        dest = trash / name
        n = 1
        while dest.exists():
            dest = trash / f"{src.stem}_{n}{src.suffix}"
            n += 1
        if src.exists():
            shutil.move(str(src), str(dest))
        elif not dest.exists():
            return False
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files SET dest_path = ?, restore_path = ?, trashed = 1,
                    review_status = COALESCE(review_status, ?)
                WHERE sha256 = ?
                """,
                (str(dest), str(src), STATUS_MERGED, sha256),
            )
        return True

    def restore_file(self, sha256: str) -> bool:
        row = self.get_file(sha256)
        if not row or not row["trashed"]:
            return False
        src = Path(row["dest_path"])
        target = Path(row["restore_path"] or row["library_path"] or src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.stem}_restored{target.suffix}")
        if src.exists():
            shutil.move(str(src), str(target))
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files SET dest_path = ?, trashed = 0, restore_path = NULL,
                    review_status = ?
                WHERE sha256 = ?
                """,
                (str(target), STATUS_DISMISSED, sha256),
            )
        return True

    def trashed_files(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM files WHERE COALESCE(trashed, 0) = 1
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def start_backup(self) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO backups(started_at) VALUES (?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
            return int(cur.lastrowid)

    def finish_backup(
        self, backup_id: int, copied: int, skipped: int, errors: int, nbytes: int
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE backups
                SET finished_at = ?, copied = ?, skipped = ?, errors = ?, bytes = ?
                WHERE id = ?
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    copied,
                    skipped,
                    errors,
                    nbytes,
                    backup_id,
                ),
            )

    def last_backup(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM backups WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()

    def file_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM files WHERE COALESCE(trashed, 0) = 0"
            ).fetchone()
            return int(row["n"])

    def list_files(
        self,
        kind: str | None = None,
        origin: str | None = None,
        primaries_only: bool = False,
        limit: int = 500,
        person_id: str | None = None,
        loc_key: str | None = None,
        review_pending: bool = False,
        has_gps: bool | None = None,
        year_month: str | None = None,
    ) -> list[sqlite3.Row]:
        return self.list_files_matching(
            kind=kind,
            origin=origin,
            primaries_only=primaries_only,
            limit=limit,
            person_id=person_id,
            loc_key=loc_key,
            review_pending=review_pending,
            has_gps=has_gps,
            year_month=year_month,
        )

    def list_files_matching(
        self,
        kind: str | None = None,
        origin: str | None = None,
        primaries_only: bool = True,
        limit: int = 4000,
        person_id: str | None = None,
        loc_key: str | None = None,
        review_pending: bool = False,
        has_gps: bool | None = None,
        year_month: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["COALESCE(trashed, 0) = 0"]
        args: list = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if origin:
            clauses.append("origin = ?")
            args.append(origin)
        if primaries_only:
            clauses.append("COALESCE(is_primary, 1) = 1")
            clauses.append("COALESCE(review_status, '') != ?")
            args.append(STATUS_CONFIRMED)
            clauses.append("COALESCE(review_status, '') != ?")
            args.append(STATUS_MERGED)
        if person_id:
            clauses.append("person_id = ?")
            args.append(person_id)
        if loc_key == "none":
            clauses.append("(loc_key IS NULL OR loc_key = '')")
        elif loc_key:
            clauses.append("loc_key = ?")
            args.append(loc_key)
        if has_gps is True:
            clauses.append("loc_key IS NOT NULL AND loc_key != ''")
        elif has_gps is False:
            clauses.append("(loc_key IS NULL OR loc_key = '')")
        if review_pending:
            clauses.append("review_status = ?")
            args.append(STATUS_PENDING)
        if year_month:
            clauses.append(
                "substr(coalesce(taken_at, created_at, copied_at), 1, 7) = ?"
            )
            args.append(year_month)
        where = f"WHERE {' AND '.join(clauses)}"
        args.append(limit)
        with self.connect() as conn:
            return conn.execute(
                f"SELECT * FROM files {where} ORDER BY coalesce(taken_at, created_at, copied_at) DESC, id DESC LIMIT ?",
                args,
            ).fetchall()

    def get_ui(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM ui_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_ui(self, key: str, value: str | None) -> None:
        with self.connect() as conn:
            if value is None:
                conn.execute("DELETE FROM ui_state WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO ui_state(key, value) VALUES (?, ?)",
                    (key, value),
                )

    def set_origin(self, sha256: str, origin: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE files SET origin = ? WHERE sha256 = ?",
                (origin, sha256),
            )

    def clear_person(self, sha256: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files SET person_id = NULL, person_label = NULL
                WHERE sha256 = ?
                """,
                (sha256,),
            )

    def update_file_meta(
        self,
        sha256: str,
        *,
        gps_lat=None,
        gps_lon=None,
        loc_key: str | None = None,
        person_id: str | None = None,
        person_label: str | None = None,
        people_tags: str | None = None,
        created_at: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE files SET
                    gps_lat = COALESCE(?, gps_lat),
                    gps_lon = COALESCE(?, gps_lon),
                    loc_key = COALESCE(?, loc_key),
                    person_id = COALESCE(?, person_id),
                    person_label = COALESCE(?, person_label),
                    people_tags = COALESCE(?, people_tags),
                    created_at = COALESCE(?, created_at)
                WHERE sha256 = ?
                """,
                (
                    gps_lat,
                    gps_lon,
                    loc_key,
                    person_id,
                    person_label,
                    people_tags,
                    created_at,
                    sha256,
                ),
            )

    def set_library_path(self, sha256: str, dest: Path) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE files SET dest_path = ?, library_path = ? WHERE sha256 = ?",
                (str(dest), str(dest), sha256),
            )

    def person_groups(self) -> list[tuple[str, str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT person_id AS pid,
                       COALESCE(MAX(person_label), person_id) AS label,
                       COUNT(*) AS n
                FROM files
                WHERE person_id IS NOT NULL AND person_id != ''
                  AND COALESCE(trashed, 0) = 0
                  AND COALESCE(origin, '') != 'screenshot'
                GROUP BY person_id
                ORDER BY n DESC
                """
            ).fetchall()
            return [(r["pid"], r["label"] or r["pid"], int(r["n"])) for r in rows]

    def location_groups(self) -> list[tuple[str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(loc_key, ''), 'none') AS lk, COUNT(*) AS n
                FROM files
                WHERE COALESCE(trashed, 0) = 0
                  AND COALESCE(is_primary, 1) = 1
                GROUP BY lk
                ORDER BY CASE WHEN lk = 'none' THEN 1 ELSE 0 END, n DESC
                """
            ).fetchall()
            return [(r["lk"], int(r["n"])) for r in rows]

    def rename_person(self, person_id: str, label: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO persons(id, label) VALUES (?, ?)",
                (person_id, label),
            )
            conn.execute(
                "UPDATE files SET person_label = ? WHERE person_id = ?",
                (label, person_id),
            )

    def assign_person(self, sha256: str, person_id: str, label: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO persons(id, label) VALUES (?, ?)",
                (person_id, label),
            )
            conn.execute(
                """
                UPDATE files SET person_id = ?, person_label = ? WHERE sha256 = ?
                """,
                (person_id, label, sha256),
            )

    def months(self) -> list[tuple[str, int]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT substr(coalesce(taken_at, copied_at), 1, 7) AS ym, COUNT(*) AS n
                FROM files
                WHERE COALESCE(is_primary, 1) = 1 AND COALESCE(trashed, 0) = 0
                  AND COALESCE(review_status, '') NOT IN (?, ?)
                GROUP BY ym
                ORDER BY ym DESC
                """,
                (STATUS_CONFIRMED, STATUS_MERGED),
            ).fetchall()
            return [(r["ym"] or "Unknown", int(r["n"])) for r in rows]

    def duplicate_groups(self, threshold: int = NEAR_DUP_HAMMING) -> list[list[sqlite3.Row]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM files
                WHERE phash IS NOT NULL AND kind = 'photo' AND COALESCE(trashed, 0) = 0
                ORDER BY size DESC, id ASC
                """
            ).fetchall()
        if not rows:
            return []

        index = NearDupIndex()
        row_by_sha = {row["sha256"]: row for row in rows}
        for row in rows:
            index.add(
                sha256=row["sha256"],
                phash=row["phash"],
                is_primary=row["is_primary"] if row["is_primary"] is not None else 1,
                size=row["size"],
                id=row["id"],
            )

        parent = list(range(len(index)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Band-bucket candidate pairs — same HITL groups, without O(n²) full scan.
        for a, b in index.candidate_pairs(threshold=threshold):
            union(a, b)

        entries = index.entries()
        buckets: dict[int, list[sqlite3.Row]] = {}
        for i, entry in enumerate(entries):
            buckets.setdefault(find(i), []).append(row_by_sha[entry.sha256])
        groups = [g for g in buckets.values() if len(g) > 1]
        groups.sort(key=lambda g: g[0]["taken_at"] or "", reverse=True)
        return groups
