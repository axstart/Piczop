from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from app.hashing import dhash_image, hamming_hex


FACE_HAMMING = 10


def _haar_detect(img: Image.Image) -> list[tuple[int, int, int, int]]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    cascade_path = None
    try:
        cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    except Exception:
        return []
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return []
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    arr = np.array(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def extract_face_hashes(path: Path, max_faces: int = 8) -> list[str]:
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            boxes = _haar_detect(img)
            hashes: list[str] = []
            if boxes:
                for x, y, w, h in boxes[:max_faces]:
                    pad = int(min(w, h) * 0.12)
                    crop = img.crop((max(0, x - pad), max(0, y - pad), x + w + pad, y + h + pad))
                    digest = dhash_image(crop)
                    if digest:
                        hashes.append(digest)
                return hashes
            # Best-effort fallback: hash a center crop as a weak "unknown people" signal only
            # when OpenCV is missing — skip clustering in that case.
            return []
    except Exception:
        return []


def cluster_face_hashes(items: list[tuple[str, str]]) -> dict[str, str]:
    """Map sha256 -> person_id (p1, p2, ...) from (sha256, face_hash) pairs."""
    if not items:
        return {}
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, (_, ha) in enumerate(items):
        for j in range(i + 1, len(items)):
            if hamming_hex(ha, items[j][1]) <= FACE_HAMMING:
                union(i, j)

    roots: dict[int, str] = {}
    next_id = 1
    mapping: dict[str, str] = {}
    for i, (sha, _) in enumerate(items):
        root = find(i)
        if root not in roots:
            roots[root] = f"p{next_id}"
            next_id += 1
        mapping[sha] = roots[root]
    return mapping


def face_engine_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except Exception:
        return False
