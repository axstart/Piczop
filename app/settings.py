from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.paths import settings_path


@dataclass
class AppSettings:
    scan_pictures: bool = True
    scan_videos: bool = True
    scan_desktop: bool = True
    scan_downloads: bool = True
    scan_documents: bool = False
    include_videos: bool = True
    copy_similar_before_review: bool = True
    extra_folders: list[str] = field(default_factory=list)

    def save(self) -> None:
        path = settings_path()
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> AppSettings:
        path = settings_path()
        if not path.exists():
            settings = cls()
            settings.save()
            return settings
        data = json.loads(path.read_text(encoding="utf-8"))
        extra = data.get("extra_folders") or []
        if "copy_similar_before_review" in data:
            copy_similar = bool(data.get("copy_similar_before_review", True))
        else:
            # Legacy skip_near_duplicates must never auto-drop similar files.
            copy_similar = True
        return cls(
            scan_pictures=bool(data.get("scan_pictures", True)),
            scan_videos=bool(data.get("scan_videos", True)),
            scan_desktop=bool(data.get("scan_desktop", True)),
            scan_downloads=bool(data.get("scan_downloads", True)),
            scan_documents=bool(data.get("scan_documents", False)),
            include_videos=bool(data.get("include_videos", True)),
            copy_similar_before_review=copy_similar,
            extra_folders=[str(p) for p in extra if p],
        )

    def extra_paths(self) -> list[Path]:
        return [Path(p) for p in self.extra_folders if p]
