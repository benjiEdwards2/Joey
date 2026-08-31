"""Generate the PWA icons reproducibly — accent-on-dark "J" glyph, no external assets.

Run from the repo root:  python scripts/make_icons.py
Writes hub/static/icon-192.png and hub/static/icon-512.png.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BG = (8, 9, 13)          # --bg  #08090D
ACCENT = (63, 217, 192)  # Money teal #3FD9C0 — the hero accent
OUT = Path(__file__).resolve().parent.parent / "hub" / "static"


def make(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    u = size / 512  # design units on a 512 grid

    # Rounded-square card face
    pad = int(56 * u)
    d.rounded_rectangle([pad, pad, size - pad, size - pad],
                        radius=int(96 * u), outline=ACCENT, width=int(18 * u))

    # "J" glyph drawn as strokes (no font dependency = reproducible everywhere)
    w = int(34 * u)
    top_y = int(168 * u)
    d.line([int(196 * u), top_y, int(340 * u), top_y], fill=ACCENT, width=w)   # top bar
    d.line([int(300 * u), top_y, int(300 * u), int(310 * u)], fill=ACCENT, width=w)  # stem
    d.arc([int(172 * u), int(250 * u), int(316 * u), int(370 * u)],
          start=20, end=180, fill=ACCENT, width=w)                              # hook

    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = OUT / f"icon-{size}.png"
        make(size).save(path, "PNG")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
