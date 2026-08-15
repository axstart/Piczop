from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

QUICK_CHUNK = 1024 * 1024
PHASH_SIZE = 8
NEAR_DUP_HAMMING = 8
# 9 bands of 7 bits ⇒ any Hamming ≤ 8 pair shares at least one identical band.
_NEAR_DUP_BANDS = 9
_NEAR_DUP_BAND_BITS = 7
_NEAR_DUP_BAND_MASK = (1 << _NEAR_DUP_BAND_BITS) - 1


def quick_key(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as fh:
        digest.update(fh.read(QUICK_CHUNK))
    return digest.hexdigest()


def full_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def dhash_image(img: Image.Image) -> str | None:
    try:
        gray = ImageOps.exif_transpose(img).convert("L").resize(
            (PHASH_SIZE + 1, PHASH_SIZE), Image.LANCZOS
        )
        pixels = list(gray.getdata())
        bits = 0
        for row in range(PHASH_SIZE):
            row_start = row * (PHASH_SIZE + 1)
            for col in range(PHASH_SIZE):
                bits <<= 1
                if pixels[row_start + col] > pixels[row_start + col + 1]:
                    bits |= 1
        return f"{bits:016x}"
    except Exception:
        return None


def perceptual_hash(path: Path) -> str | None:
    """64-bit difference hash as 16 hex chars. None if the file is not an image."""
    try:
        with Image.open(path) as img:
            return dhash_image(img)
    except Exception:
        return None


def hamming_hex(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    return (int(a, 16) ^ int(b, 16)).bit_count()


def is_near_duplicate(a: str | None, b: str | None, threshold: int = NEAR_DUP_HAMMING) -> bool:
    if not a or not b:
        return False
    return hamming_hex(a, b) <= threshold


def _band_keys(phash: str) -> list[int]:
    value = int(phash, 16)
    return [
        (value >> (i * _NEAR_DUP_BAND_BITS)) & _NEAR_DUP_BAND_MASK
        for i in range(_NEAR_DUP_BANDS)
    ]


@dataclass(slots=True)
class NearDupRecord:
    """Lightweight row used by the in-memory near-dup index."""

    sha256: str
    phash: str
    is_primary: int
    size: int
    id: int

    def as_row(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "phash": self.phash,
            "is_primary": self.is_primary,
            "size": self.size,
            "id": self.id,
        }


class NearDupIndex:
    """In-memory pHash index with band bucketing (avoids full-table scans)."""

    def __init__(self) -> None:
        self._entries: list[NearDupRecord] = []
        self._bands: list[dict[int, list[int]]] = [
            defaultdict(list) for _ in range(_NEAR_DUP_BANDS)
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def add(
        self,
        *,
        sha256: str,
        phash: str,
        is_primary: int = 1,
        size: int = 0,
        id: int = 0,
    ) -> None:
        if not phash or len(phash) != 16:
            return
        idx = len(self._entries)
        self._entries.append(
            NearDupRecord(
                sha256=sha256,
                phash=phash,
                is_primary=int(is_primary or 0),
                size=int(size or 0),
                id=int(id or 0),
            )
        )
        for band, key in enumerate(_band_keys(phash)):
            self._bands[band][key].append(idx)

    def find(
        self, phash: str | None, threshold: int = NEAR_DUP_HAMMING
    ) -> NearDupRecord | None:
        if not phash or len(phash) != 16:
            return None
        candidates: set[int] = set()
        for band, key in enumerate(_band_keys(phash)):
            candidates.update(self._bands[band].get(key, ()))
        best: NearDupRecord | None = None
        best_key: tuple[int, int, int, int] | None = None
        for idx in candidates:
            entry = self._entries[idx]
            dist = hamming_hex(phash, entry.phash)
            if dist > threshold:
                continue
            # Match Catalog.find_near_duplicate ordering: closer first, then
            # is_primary DESC, size DESC, id ASC.
            key = (dist, -entry.is_primary, -entry.size, entry.id)
            if best is None or key < best_key:
                best = entry
                best_key = key
                if dist == 0 and entry.is_primary:
                    break
        return best

    def candidate_pairs(
        self, threshold: int = NEAR_DUP_HAMMING
    ) -> list[tuple[int, int]]:
        """Index pairs that share a band; caller still verifies Hamming."""
        seen: set[tuple[int, int]] = set()
        pairs: list[tuple[int, int]] = []
        for band_map in self._bands:
            for idxs in band_map.values():
                if len(idxs) < 2:
                    continue
                for i in range(len(idxs)):
                    for j in range(i + 1, len(idxs)):
                        a, b = idxs[i], idxs[j]
                        if a > b:
                            a, b = b, a
                        pair = (a, b)
                        if pair in seen:
                            continue
                        seen.add(pair)
                        left, right = self._entries[a], self._entries[b]
                        if hamming_hex(left.phash, right.phash) <= threshold:
                            pairs.append(pair)
        return pairs

    def entries(self) -> list[NearDupRecord]:
        return self._entries
