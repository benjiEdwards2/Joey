"""Generate the PWA icons reproducibly — from the committed joey photo.

Source: hub/static/icon_source.jpg (B.'s joey kangaroo photo, 2026-09-11 —
supersedes the drawn "J" glyph). Square crop keeps the face centred.

Run from the repo root:  python scripts/make_icons.py
Writes hub/static/icon-192.png and hub/static/icon-512.png.
"""

from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parent.parent / "hub" / "static"
SOURCE = STATIC / "icon_source.jpg"

# Face-centred square crop of the 399x501 source: full width, top offset
# tuned so the face sits in the upper-middle of the icon.
CROP_TOP = 40


def make(size: int) -> Image.Image:
    img = Image.open(SOURCE).convert("RGB")
    w, h = img.size
    top = min(CROP_TOP, h - w)
    img = img.crop((0, top, w, top + w))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = STATIC / f"icon-{size}.png"
        make(size).save(path, "PNG")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
