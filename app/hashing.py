from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps

QUICK_CHUNK = 1024 * 1024
PHASH_SIZE = 8
NEAR_DUP_HAMMING = 8


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
