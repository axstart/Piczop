"""Write assets/piczop.ico (multi-size) using Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "piczop.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, size // 16)
    d.rounded_rectangle(
        (m, m, size - 1 - m, size - 1 - m),
        radius=max(2, size // 6),
        fill=(43, 108, 176, 255),
    )
    # lens body
    cx = cy = size // 2
    r_outer = size // 3
    r_inner = max(2, size // 6)
    d.ellipse(
        (cx - r_outer, cy - r_outer + m, cx + r_outer, cy + r_outer + m),
        fill=(17, 19, 24, 255),
        outline=(232, 234, 237, 255),
        width=max(1, size // 32),
    )
    d.ellipse(
        (cx - r_inner, cy - r_inner + m, cx + r_inner, cy + r_inner + m),
        fill=(56, 161, 105, 255),
    )
    # flash square
    fs = max(2, size // 8)
    d.rounded_rectangle(
        (size - m * 4 - fs, m * 3, size - m * 3, m * 3 + fs),
        radius=max(1, size // 32),
        fill=(250, 240, 137, 255),
    )
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [_draw(s) for s in SIZES]
    images[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
