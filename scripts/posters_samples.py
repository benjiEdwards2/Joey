"""JY-260 phase 1: render sample posters, redraw the starter kit's guide.png, and measure the renderer's peak RAM.

  python scripts/posters_samples.py --out <folder> [--template <kit folder>] [--guide]

No network: the art is generated placeholder art (2000 x 3000 JPEG, the size of a large TMDB poster). Prints one
PASS / FAIL line per step and writes samples.log beside the posters. --guide also rewrites
hub/posters_template/guide.png from the kit's template.json (the safe-area overlay B. drops into Canva).
"""
from __future__ import annotations

import argparse
import gc
import io
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from hub import media_posters_render as r  # noqa: E402

SAMPLES = [   # (file, kind, title, year, seasons, years)
    ("1-short-film-up.jpg", "movie", "Up", 2009, None, None),
    ("2-short-film-heat.jpg", "movie", "Heat", 1995, None, None),
    ("3-long-film-jesse-james.jpg", "movie", "The Assassination of Jesse James by the Coward Robert Ford", 2007,
     None, None),
    ("4-long-film-everything.jpg", "movie", "Everything Everywhere All at Once", 2022, None, None),
    ("5-series-the-bear.jpg", "tv", "The Bear", 2022, (1, 4), (2022, 2025)),
    ("6-series-severance.jpg", "tv", "Severance", 2022, (1, 2), (2022, None)),
]
PALETTES = [((214, 120, 60), (40, 70, 120)), ((30, 40, 60), (180, 60, 40)), ((200, 170, 110), (60, 50, 40)),
            ((90, 40, 120), (230, 120, 170)), ((40, 90, 80), (220, 200, 160)), ((20, 60, 90), (210, 220, 230))]


def placeholder(i: int, w: int = 2000, h: int = 3000) -> bytes:
    """Busy placeholder art: a vertical gradient with a few shapes, so the scrim and text are tested on detail."""
    a, b = PALETTES[i % len(PALETTES)]
    col = Image.new("RGB", (1, h))
    col.putdata([tuple(int(a[k] + (b[k] - a[k]) * y / h) for k in range(3)) for y in range(h)])
    im = col.resize((w, h))
    d = ImageDraw.Draw(im)
    for n in range(7):
        x, y, s = (n * 397 + i * 211) % w, (n * 613 + i * 151) % h, 180 + (n * 97) % 420
        d.ellipse((x - s, y - s, x + s, y + s), fill=tuple(min(255, c + 40) for c in (b if n % 2 else a)))
    d.rectangle((0, int(h * 0.82), w, h), fill=tuple(min(255, c + 60) for c in b))   # bright detail under the text
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def peak_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)
    if peak is None:   # Linux: ru_maxrss in KiB
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return peak / 1048576


def rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / 1048576


def measure(art_path: Path, template: str) -> int:
    """Fresh process: imports + kit + art bytes loaded, then one render; the peak's rise is the renderer's cost."""
    tpl = r.load_template(template)
    data = art_path.read_bytes()
    r._font(tpl, 40, 800)
    gc.collect()
    base_rss, base_peak = rss_mb(), peak_mb()
    if base_peak is None:
        print("SKIP peak RAM: psutil not installed")
        return 0
    r.render(tpl, data, "The Assassination of Jesse James by the Coward Robert Ford", "2007")
    peak = peak_mb()
    print(f"PASS peak RAM of one render: +{peak - base_peak:.1f} MB over the process peak before it "
          f"(rss before {base_rss:.1f} MB, peak after {peak:.1f} MB); source 2000 x 3000 JPEG, {len(data) // 1024} KB")
    return 0


def draw_guide(tpl: r.Template, path: Path) -> None:
    """The safe-area overlay: title box, sub-line box, scrim band, side margins. Transparent PNG at the canvas size."""
    w, h = tpl.width, tpl.height
    t, s, band = tpl.data["title"], tpl.data["sub"], tpl.data.get("scrim_band") or {}
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    font = r._font(tpl, max(14, w // 50), 600)
    if band:
        d.rectangle((0, int(h * band["top"]), w, h), fill=(0, 160, 255, 40))
        d.line((0, int(h * band["top"]), w, int(h * band["top"])), fill=(0, 160, 255, 220), width=3)
        d.text((12, int(h * band["top"]) + 8), f"scrim_band.top {band['top']}", font=font, fill=(0, 160, 255, 255))
        d.line((0, int(h * band["solid"]), w, int(h * band["solid"])), fill=(0, 160, 255, 160), width=2)
    x0, x1 = int(w * t["margin_x"]), int(w * (1 - t["margin_x"]))
    for x in (x0, x1):
        d.line((x, 0, x, h), fill=(255, 0, 200, 120), width=2)
    ty0 = int(h * t["title_anchor"])
    ty1 = int(ty0 + int(t["max_lines"]) * t["max_size"] * t["line_height"])
    d.rectangle((x0, ty0, x1, ty1), outline=(255, 0, 200, 255), width=4)
    d.text((x0 + 8, ty0 - font.size - 10), f"title box: top {t['title_anchor']}, {t['max_lines']} lines max",
           font=font, fill=(255, 0, 200, 255))
    sy0 = int(h * s["sub_anchor"])
    d.rectangle((x0, sy0, x1, int(sy0 + s["size"] * 1.2)), outline=(255, 200, 0, 255), width=4)
    d.text((x0 + 8, int(sy0 + s["size"] * 1.2) + 6), f"sub-line: top {s['sub_anchor']}", font=font,
           fill=(255, 200, 0, 255))
    d.text((x0 + 8, 12), f"canvas {w} x {h} · margins {t['margin_x']} · keep faces above the blue line",
           font=font, fill=(255, 255, 255, 230))
    im.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=str(r.STARTER))
    ap.add_argument("--guide", action="store_true")
    ap.add_argument("--measure", help="internal: render this art once in a fresh process and print the peak RAM")
    ns = ap.parse_args(argv)
    if ns.measure:
        return measure(Path(ns.measure), ns.template)
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    lines, ok = [], True

    def say(line):
        print(line)
        lines.append(line)

    try:
        tpl = r.load_template(ns.template)
        say(f"PASS template {tpl.version} ({tpl.data.get('name', '')})")
    except r.TemplateError as exc:
        say(f"FAIL {exc}")
        (out / "samples.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    if ns.guide:
        draw_guide(tpl, r.STARTER / "guide.png")
        say("PASS guide.png redrawn")
    times = []
    for i, (name, kind, title, year, seasons, years) in enumerate(SAMPLES):
        sub = r.sub_line(kind, year=year, seasons=seasons, years=years, series_sub=True)
        t0 = time.perf_counter()
        jpg = r.render(tpl, placeholder(i), title, sub)
        times.append(time.perf_counter() - t0)
        (out / name).write_bytes(jpg)
        lay = r.layout_title(tpl, title)
        inside = all(tpl.width * 0.06 - 0.5 <= ln.x and ln.x + ln.width <= tpl.width * 0.94 + 0.5 for ln in lay.lines)
        ok &= inside
        say(f"{'PASS' if inside else 'FAIL'} {name}: {lay.size}px, {len(lay.lines)} line(s), sub '{sub}', "
            f"{len(jpg) // 1024} KB, {times[-1] * 1000:.0f} ms")
    art = out / "_measure-art.jpg"
    art.write_bytes(placeholder(2))
    got = subprocess.run([sys.executable, __file__, "--measure", str(art), "--template", ns.template, "--out", str(out)],
                         capture_output=True, text=True)
    art.unlink()
    say(got.stdout.strip() or f"FAIL measure: {got.stderr.strip()[-300:]}")
    say(f"PASS render time: max {max(times) * 1000:.0f} ms, mean {sum(times) / len(times) * 1000:.0f} ms")
    sheet = Image.new("RGB", (6 * 340 + 70, 530), (24, 24, 27))
    for i, (name, *_rest) in enumerate(SAMPLES):
        with Image.open(out / name) as im:
            sheet.paste(im.resize((340, 510)), (10 + i * 350, 10))
    sheet.save(out / "contact-sheet.jpg", quality=88)
    say("PASS contact-sheet.jpg")
    (out / "samples.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
