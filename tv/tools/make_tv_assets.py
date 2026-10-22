"""Generate the Joey TV launcher assets reproducibly from the committed joey photo.

Source: hub/static/icon_source.jpg with the same face-centred square crop as scripts/make_icons.py
(parent DECISIONS 2026-09-11). Writes:
  tv/app/src/main/res/mipmap-<density>/ic_launcher.png   (48/72/96/144/192 px)
  tv/app/src/main/res/drawable-xhdpi/banner.png          (320x180, kangaroo + "Joey Media" on #09090b)

Run from the repo root:  python tv/tools/make_tv_assets.py [--font <bold .ttf>]
Needs Pillow. The font only affects the banner text; any bold sans works.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "hub" / "static" / "icon_source.jpg"
RES = REPO / "tv" / "app" / "src" / "main" / "res"
CROP_TOP = 40  # same as scripts/make_icons.py
BG = (9, 9, 11)  # #09090b, the Joey ground colour
FG = (250, 250, 250)
DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def square(size: int) -> Image.Image:
    img = Image.open(SOURCE).convert("RGB")
    w, h = img.size
    top = min(CROP_TOP, h - w)
    return img.crop((0, top, w, top + w)).resize((size, size), Image.LANCZOS)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), mask)
    return out


def font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    for candidate in ([path] if path else []) + FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit("no bold font found; pass --font <path to a bold .ttf>")


def banner(font_path: str | None) -> Image.Image:
    out = Image.new("RGB", (320, 180), BG)
    icon = rounded(square(120), 18)
    out.paste(icon, (24, 30), icon)
    draw = ImageDraw.Draw(out)
    f = font(font_path, 40)
    draw.text((164, 44), "Joey", font=f, fill=FG)
    draw.text((164, 92), "Media", font=f, fill=FG)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font")
    args = ap.parse_args()
    for density, size in DENSITIES.items():
        path = RES / f"mipmap-{density}" / "ic_launcher.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        square(size).quantize(256).save(path, "PNG", optimize=True)
        print(f"wrote {path.relative_to(REPO)}")
    path = RES / "drawable-xhdpi" / "banner.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    banner(args.font).save(path, "PNG", optimize=True)
    print(f"wrote {path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
