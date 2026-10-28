"""JY-260 phase 1: the poster renderer and the template kit (spec docs/specs/JY-260-posters.md, Q1B / Q8).

A template kit is a folder B. refines in Canva and re-exports, with no code change (docs/posters-template-guide.md):

  template.json   canvas, font, title box, sub-line box, scrim and frame (validated here as a whole)
  scrim.png       optional: a transparent PNG at the canvas size, drawn over the art (else the `scrim_band` gradient)
  frame.png       optional: a transparent PNG at the canvas size, drawn on top of everything
  <font file>     the TTF / OTF / WOFF2 named in template.json (else the hub's own font folder: Geist ships there)

Layers, bottom to top: TMDB art (cover-cropped, full bleed) -> scrim -> title -> sub-line -> frame. The title's top
sits at `title_anchor` x height and is centred between the side margins; it auto-fits: one line shrinking from
max_size to min_size, then two (up to max_lines) balanced lines from max_size down, then an ellipsis at min_size.

Memory: one RGB canvas (4.5 MB at 1000 x 1500), JPEG art decoded at reduced scale (`draft`), text masks cut to the
text band only. No network here: the caller hands in the art bytes. `python -m hub.media_posters_render --help`
renders a preview on any machine.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

STARTER = Path(__file__).resolve().parent / "posters_template"
HUB_FONTS = Path(__file__).resolve().parent / "static" / "fonts"
RENDER_VERSION = 3          # bump when the drawing code changes, so every poster re-renders
JPEG_QUALITY = 90
ELLIPSIS = "…"
FONT_EXT = (".ttf", ".otf", ".woff2", ".woff")
COLOUR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_SOURCE_PIXELS = 64_000_000   # header check: a JPEG this big still decodes at 1/8 scale (`draft`)
MAX_DECODED_PIXELS = 4_000_000   # what a PNG / WebP may decode to: <= 16 MB as RGBA (+12 MB as RGB): render < ~30 MB
MAX_DECODED_JPEG = 8_000_000     # a JPEG after `draft`: <= 24 MB as RGB (a 2000 x 3000 source drafts to 1000 x 1500)
MAX_TITLE_CHARS = 120            # longer titles are cut (and flagged) before any layout work
MAX_JSON_BYTES = 64 * 1024
MAX_PNG_BYTES = 10 * 1024 * 1024
MAX_FONT_BYTES = 5 * 1024 * 1024


class TemplateError(ValueError):
    """A template kit refused as a whole; `problems` lists every reason, each naming its field or file."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("Template rejected: " + "; ".join(self.problems))


class RenderError(ValueError):
    """The art could not be read as an image."""


@dataclass
class Template:
    folder: Path
    data: dict
    version: str
    font_path: Path
    scrim_path: Path | None
    frame_path: Path | None
    width: int = field(init=False)
    height: int = field(init=False)

    def __post_init__(self):
        self.width, self.height = self.data["canvas"]


@dataclass
class Line:
    text: str
    x: float          # left edge
    top: float        # top of the line box (a title line: the top of its ink, the cap height for capitals)
    width: float
    base: float | None = None   # the baseline (title lines, 2026-10-28 fill layout); None = centred in its line box


@dataclass
class TitleLayout:
    size: int
    lines: list[Line]
    top: float
    bottom: float
    truncated: bool = False   # cut short with an ellipsis (past the hard floor)


# ---- template.json ----

def _num(problems, node, key, where, lo, hi, required=True):
    v = node.get(key) if isinstance(node, dict) else None
    if v is None:
        if required:
            problems.append(f"{where}.{key} is missing")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        problems.append(f"{where}.{key} must be a number from {lo} to {hi} (got {v!r})")
        return None
    return v


def _colour(problems, node, key, where):
    v = node.get(key) if isinstance(node, dict) else None
    if not isinstance(v, str) or not COLOUR_RE.match(v):
        problems.append(f"{where}.{key} must be a colour like #FFFFFF (got {v!r})")


def _shadow(problems, node, where):
    s = node.get("shadow") if isinstance(node, dict) else None
    if s is None:
        return
    if not isinstance(s, dict):
        problems.append(f"{where}.shadow must be an object or null")
        return
    _colour(problems, s, "colour", f"{where}.shadow")
    _num(problems, s, "opacity", f"{where}.shadow", 0, 1)
    _num(problems, s, "blur", f"{where}.shadow", 0, 60)
    _num(problems, s, "dy", f"{where}.shadow", -60, 60)


def _font_file(folder: Path, name) -> Path | None:
    if not isinstance(name, str) or not name or Path(name).name != name or not name.lower().endswith(FONT_EXT):
        return None
    for base in (folder, HUB_FONTS):
        if (base / name).is_file():
            return base / name
    return None


def _layer(problems, folder: Path, name, key: str, size) -> Path | None:
    if name is None:
        return None
    if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".png"):
        problems.append(f"{key} must be a .png file name in the template folder, or null (got {name!r})")
        return None
    path = folder / name
    if not path.is_file():
        problems.append(f"{key}: {name} is not in the template folder")
        return None
    if path.stat().st_size > MAX_PNG_BYTES:
        problems.append(f"{key}: {name} is over {MAX_PNG_BYTES // 1048576} MB")
        return None
    try:
        with Image.open(path) as im:
            if size and im.size != tuple(size):
                problems.append(f"{key}: {name} is {im.size[0]} × {im.size[1]}, the canvas is {size[0]} × {size[1]}")
            if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
                problems.append(f"{key}: {name} has no transparent background (export as PNG with transparency)")
    except Exception:
        problems.append(f"{key}: {name} is not a readable PNG")
    return path


def validate(data, folder: Path) -> list[str]:
    """Every problem with a parsed template.json, in words naming the field or file ([] = good)."""
    folder = Path(folder)
    p: list[str] = []
    if not isinstance(data, dict):
        return ["template.json must be a JSON object"]
    if data.get("version") != 1:
        p.append(f"version must be 1 (got {data.get('version')!r})")
    canvas = data.get("canvas")
    size = None
    if (isinstance(canvas, list) and len(canvas) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                for v in canvas)):
        w, h = canvas
        if w * 3 != h * 2 or not 600 <= w <= 2000:
            p.append(f"canvas must be 2:3, from [600, 900] to [2000, 3000] (got {canvas})")
        else:
            size = canvas
    else:
        p.append(f"canvas must be [width, height] in whole pixels (got {canvas!r})")

    font = data.get("font")
    if not isinstance(font, dict):
        p.append("font is missing (an object with family and file)")
    else:
        if not isinstance(font.get("family"), str) or not font["family"].strip():
            p.append("font.family must be the font's name, e.g. \"Geist\"")
        if _font_file(folder, font.get("file")) is None:
            p.append(f"font.file: {font.get('file')!r} is not a .ttf / .otf / .woff2 file in the template folder")
        elif _font_file(folder, font.get("file")).stat().st_size > MAX_FONT_BYTES:
            p.append(f"font.file: {font.get('file')} is over {MAX_FONT_BYTES // 1048576} MB")
        else:
            try:
                ImageFont.truetype(str(_font_file(folder, font.get("file"))), 20)
            except Exception:
                p.append(f"font.file: {font.get('file')} cannot be read as a font")

    _layer(p, folder, data.get("scrim"), "scrim", size)
    _layer(p, folder, data.get("frame"), "frame", size)
    band = data.get("scrim_band")
    if band is not None:
        if not isinstance(band, dict):
            p.append("scrim_band must be an object or null")
        else:
            top = _num(p, band, "top", "scrim_band", 0, 1)
            solid = _num(p, band, "solid", "scrim_band", 0, 1.5)   # past 1: still fading at the bottom edge
            _num(p, band, "opacity", "scrim_band", 0, 1)
            _colour(p, band, "colour", "scrim_band")
            if top is not None and solid is not None and solid < top:
                p.append("scrim_band.solid must be at or below scrim_band.top (a larger fraction)")

    t, s = data.get("title"), data.get("sub")
    if not isinstance(t, dict):
        p.append("title is missing")
        t = {}
    if not isinstance(s, dict):
        p.append("sub is missing")
        s = {}
    anchor = _num(p, t, "title_anchor", "title", 0, 1)
    margin = _num(p, t, "margin_x", "title", 0, 0.3)
    hi = _num(p, t, "max_size", "title", 8, 400)
    lo = _num(p, t, "min_size", "title", 8, 400)
    lines = _num(p, t, "max_lines", "title", 1, 3)
    lh = _num(p, t, "line_height", "title", 0.7, 2)
    _num(p, t, "tracking", "title", -0.2, 0.5)
    _num(p, t, "weight", "title", 100, 1000)
    _colour(p, t, "colour", "title")
    _shadow(p, t, "title")
    if lines is not None and not isinstance(lines, int):
        p.append("title.max_lines must be a whole number")
    if hi is not None and lo is not None and lo > hi:
        p.append(f"title.min_size ({lo}) must not be larger than title.max_size ({hi})")
    sub_anchor = _num(p, s, "sub_anchor", "sub", 0, 1)
    _num(p, s, "size", "sub", 8, 300)
    _num(p, s, "weight", "sub", 100, 1000)
    _num(p, s, "opacity", "sub", 0, 1)
    _num(p, s, "tracking", "sub", -0.2, 0.5)
    _colour(p, s, "colour", "sub")
    _shadow(p, s, "sub")
    _num(p, t, "title_fill", "title", 0.3, 1, required=False)
    _num(p, t, "max_cap_height", "title", 0.03, 0.4, required=False)
    rule = data.get("accent_rule")
    if rule is not None:
        if not isinstance(rule, dict):
            p.append("accent_rule must be an object or null (null = no rule)")
        else:
            _colour(p, rule, "colour", "accent_rule")
            _num(p, rule, "width", "accent_rule", 0.01, 0.5)
            _num(p, rule, "height", "accent_rule", 1, 40)
            _num(p, rule, "gap", "accent_rule", 0, 200)
    wrap = _num(p, t, "wrap_at", "title", 8, 400, required=False)
    if wrap is not None and None not in (hi, lo) and not lo <= wrap <= hi:
        p.append(f"title.wrap_at ({wrap}) must be from title.min_size to title.max_size")
    mode = t.get("title_anchor_mode", "top")
    if mode not in ("top", "bottom"):
        p.append(f'title.title_anchor_mode must be "top" or "bottom" (got {mode!r})')
    gap = _num(p, t, "title_gap", "title", 0, 0.2, required=False) or 0
    rise = _num(p, t, "title_top_limit", "title", 0, 1, required=False) if mode == "bottom" else None
    if rise is not None and anchor is not None and rise > anchor:
        p.append(f"title.title_top_limit ({rise}) must be at or above title.title_anchor ({anchor})")
    if None not in (anchor, sub_anchor, lo, lines, lh) and size:
        room = (sub_anchor - gap - (rise if rise is not None else anchor)) * size[1]
        if room < int(lines) * lo * lh - 0.5:
            p.append(f"sub.sub_anchor ({sub_anchor}) leaves {max(0, room):.0f} px for the title block; "
                     f"{lines} title lines at min_size need {int(lines) * lo * lh:.0f} px")
    return p


def _digest(paths, raw: bytes) -> str:
    h = hashlib.sha256(raw + f"|r{RENDER_VERSION}".encode())
    for path in paths:
        if path is not None:
            h.update(path.name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()[:12]


def load_template(folder) -> Template:
    """The kit in `folder`, validated. Raises TemplateError naming every problem."""
    folder = Path(folder)
    path = folder / "template.json"
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise TemplateError([f"template.json is over {MAX_JSON_BYTES // 1024} KB"])
        raw = path.read_bytes()
    except OSError:
        raise TemplateError([f"no template.json in {folder.name or 'the template folder'}"]) from None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TemplateError([f"template.json is not valid JSON ({type(exc).__name__}: line "
                             f"{getattr(exc, 'lineno', '?')})"]) from None
    problems = validate(data, folder)
    if problems:
        raise TemplateError(problems)
    font = _font_file(folder, data["font"]["file"])
    scrim = folder / data["scrim"] if data.get("scrim") else None
    frame = folder / data["frame"] if data.get("frame") else None
    return Template(folder, data, _digest((font, scrim, frame), raw), font, scrim, frame)


# ---- text ----

def _font(tpl: Template, size: int, weight) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(tpl.font_path), size)
    try:
        axes = f.get_variation_axes()
    except Exception:   # a static font has no axes
        return f
    values = []
    for ax in axes:
        name = ax.get("name")
        name = name.decode() if isinstance(name, bytes) else str(name)
        values.append(max(ax["minimum"], min(ax["maximum"], weight)) if name.lower() == "weight" else ax["default"])
    f.set_variation_by_axes(values)
    return f


def _width(font, text: str, tracking: float, size: int) -> float:
    if not text:
        return 0.0
    if not tracking:
        return font.getlength(text)
    return sum(font.getlength(c) for c in text) + tracking * size * (len(text) - 1)


def _ellipsise(font, text: str, room: float, tracking: float, size: int) -> str:
    while text and _width(font, text.rstrip() + ELLIPSIS, tracking, size) > room:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def _split(words: list[str], n: int, measure) -> list[str] | None:
    """The split of `words` into n lines (n <= 3) with the narrowest widest line. Word widths are measured once and
    summed (prefix sums), so 2 lines are O(words) and 3 lines O(words^2) of additions - bounded by MAX_TITLE_CHARS.
    The caller checks the chosen lines with the real font."""
    if len(words) < n:
        return None
    if n == 1:
        return [" ".join(words)]
    ww = [measure(w) for w in words]
    gap = measure(words[0] + " " + words[1]) - ww[0] - ww[1]
    pre = [0.0]
    for w in ww:
        pre.append(pre[-1] + w)

    def width(a, b):   # words a..b-1 on one line
        return pre[b] - pre[a] + gap * (b - a - 1)
    k = len(words)
    if n == 2:
        cuts = ((i,) for i in range(1, k))
    else:
        cuts = ((i, j) for i in range(1, k - 1) for j in range(i + 1, k))
    best, best_w = None, None
    for cut in cuts:
        bounds = (0, *cut, k)
        widest = max(width(a, b) for a, b in zip(bounds, bounds[1:]))
        if best_w is None or widest < best_w:
            best, best_w = bounds, widest
    return [" ".join(words[a:b]) for a, b in zip(best, best[1:])]


def title_band(tpl: Template) -> tuple[float, float, float]:
    """(where a title's top sits, the highest it may rise, the lowest its block may reach) in pixels.
    "top" mode: the block hangs from title_anchor down to the sub-line. "bottom" mode: the block's bottom may reach
    sub_anchor - title_gap; a title that fits starts at title_anchor, a taller one grows upward to title_top_limit."""
    t, h = tpl.data["title"], tpl.height
    floor_y = h * (tpl.data["sub"]["sub_anchor"] - float(t.get("title_gap") or 0))
    if t.get("title_anchor_mode", "top") == "bottom":
        return h * t["title_anchor"], h * float(t.get("title_top_limit", t["title_anchor"])), floor_y
    return h * t["title_anchor"], h * t["title_anchor"], floor_y


def layout_title(tpl: Template, title: str) -> TitleLayout:
    """Where the title goes: font size and each line's box. The block runs from title_anchor down to sub_anchor.
    One line shrinks from max_size to wrap_at; then 2 balanced lines (and so on up to max_lines) from the largest size
    that fits the block down to wrap_at - the last line count down to min_size, the hard floor. Only a title too
    long even then is ellipsised (`truncated`, shown on the review page)."""
    t = tpl.data["title"]
    text = " ".join(str(title or "").split())
    capped = len(text) > MAX_TITLE_CHARS
    if capped:   # bounded work whatever the input; the cut is flagged like any other
        text = text[:MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip() + ELLIPSIS
    if t.get("uppercase"):
        text = text.upper()
    left = tpl.width * t["margin_x"]
    room = tpl.width - 2 * left
    # B. 2026-10-28 ("To fill more portions of things"): the widest line is sized to fill title_fill of the safe
    # width (default 1.0 = the phase-1 behaviour: as large as fits), up to max_size
    target = room * float(t.get("title_fill") or 1.0)
    top_at, limit, floor_y = title_band(tpl)
    block = floor_y - limit
    hi, lo, max_lines = int(t["max_size"]), int(t["min_size"]), int(t["max_lines"])
    wrap_at = int(t.get("wrap_at") or lo)
    tracking, weight, lh = float(t.get("tracking") or 0), t["weight"], float(t["line_height"])
    words = text.split(" ") if text else []

    ref = 100
    ref_font = _font(tpl, ref, weight)
    hb = ref_font.getbbox("H", anchor="ls")
    cap_h = max((hb[3] - hb[1]) / ref, 0.01)   # capital height per pixel of size
    seen: dict[str, float] = {}

    def ref_measure(s: str) -> float:
        if s not in seen:
            seen[s] = _width(ref_font, s, tracking, ref)
        return seen[s]

    def ink(lines) -> tuple[float, float]:
        """(top, bottom) of the lines' real glyphs relative to the baseline, per pixel of font size (the top is
        negative). Measured, not assumed: a tall single line at max_size is placed by its real height."""
        bb = [ref_font.getbbox(ln, anchor="ls") for ln in lines if ln]
        if not bb:
            return -0.7, 0.0
        return min(b[1] for b in bb) / ref, max(b[3] for b in bb) / ref

    def height(n, a, d) -> float:   # the ink height of n lines per pixel of size
        return (n - 1) * lh + (d - a)

    def fit(n, goal):
        """Widths scale with the size, so the best split is found once at a reference size; the size is then the
        largest that fits (the widest line within `target`, the real ink height within the block), checked with the
        real font (hinting is not quite linear)."""
        lines = [text] if n == 1 else _split(words, n, ref_measure)
        if not lines:
            return None
        a, d = ink(lines)
        cap = min(hi, int(block / height(n, a, d)))
        if t.get("max_cap_height"):   # the sanity cap: the font's capital height ("H"), as a share of the canvas height
            cap = min(cap, int(tpl.height * float(t["max_cap_height"]) / cap_h))
        floor = lo if n == max_lines else max(lo, wrap_at)
        if cap < floor:
            return None
        widest = max(ref_measure(ln) for ln in lines) or 1
        for size in range(min(cap, int(goal / widest * ref) + 1), floor - 1, -1):
            font = _font(tpl, size, weight)
            if all(_width(font, ln, tracking, size) <= goal for ln in lines):
                return size, font, lines
        return None

    got, truncated = None, False
    for goal in ((target, room) if target < room else (room,)):   # the fill target; a title too long for it even
        for n in range(1, max_lines + 1):                          # on max_lines at the floor may use the whole width
            got = fit(n, goal)
            if got:
                break
        if got:
            break
    if not got:   # too long even at the floor on max_lines: fill the lines, ellipsise the last
        truncated = True
        size = min(lo, int(block / height(max_lines, *ink(words or [""]))))
        font = _font(tpl, size, weight)
        measure = lambda s: _width(font, s, tracking, size)   # noqa: E731
        lines, rest = [], list(words)
        while rest and len(lines) < max_lines:
            line = rest.pop(0)
            while rest and measure(line + " " + rest[0]) <= room:
                line += " " + rest.pop(0)
            lines.append(line)
        if rest or measure(lines[-1]) > room:
            lines[-1] = _ellipsise(font, lines[-1] + (" " + " ".join(rest) if rest else ""), room, tracking, size)
        lines = [ln if measure(ln) <= room else _ellipsise(font, ln, room, tracking, size) for ln in lines]
        got = (size, font, lines)
    size, font, lines = got
    step = size * lh
    bb = [font.getbbox(ln, anchor="ls") for ln in lines if ln]   # the real glyphs at the chosen size (no rounding)
    a = min(b[1] for b in bb) / size if bb else -0.7
    d = max(b[3] for b in bb) / size if bb else 0.0
    tall = height(len(lines), a, d) * size
    top = min(top_at, floor_y - tall)   # bottom mode: a taller block grows upward, never into the gap (real ink)
    out = []
    for i, ln in enumerate(lines):
        w = _width(font, ln, tracking, size)
        base = top - a * size + i * step
        out.append(Line(ln, (tpl.width - w) / 2, top + i * step, w, base))
    return TitleLayout(size, out, top, top + tall, truncated or capped)


def rule_box(tpl: Template, lay: TitleLayout) -> tuple[float, float, float, float] | None:
    """The accent rule under the title block (left, top, right, bottom), or None when the kit has none."""
    rule = tpl.data.get("accent_rule")
    if not rule or not any(ln.text for ln in lay.lines):
        return None
    w = tpl.width * float(rule["width"])
    top = lay.bottom + float(rule["gap"])
    return (tpl.width - w) / 2, top, (tpl.width + w) / 2, top + float(rule["height"])


def sub_top(tpl: Template, lay: TitleLayout) -> float:
    """Where the sub-line's box starts: sub_anchor, or lower when the accent rule needs the room (the rule's gap is
    kept below it as well), so the title, the rule and the sub-line never meet."""
    at = tpl.height * tpl.data["sub"]["sub_anchor"]
    box = rule_box(tpl, lay)
    return max(at, box[3] + float(tpl.data["accent_rule"]["gap"])) if box else at


def sub_line(kind: str, year=None, seasons=None, season=None) -> str:
    """The line under the title. A film: its year (Q7A). A series: "Seasons 1–4", or "Season 1" with one season
    (B. 2026-10-28: no years for now); `seasons` is its real season numbers (specials / season 0 never count).
    A season item: "Season 2"."""
    if kind == "season":
        return f"Season {season}" if isinstance(season, int) and season >= 1 else ""
    if kind != "tv":
        return str(year) if year else ""
    real = sorted({n for n in seasons or [] if isinstance(n, int) and not isinstance(n, bool) and n >= 1})
    if not real:
        return ""
    return f"Season {real[0]}" if len(real) == 1 else f"Seasons {real[0]}–{real[-1]}"


# ---- drawing ----

def _rgb(hexcolour: str) -> tuple[int, int, int]:
    return tuple(int(hexcolour[i:i + 2], 16) for i in (1, 3, 5))


def _cover(art: bytes, w: int, h: int) -> Image.Image:
    try:
        src = Image.open(io.BytesIO(art))   # lazy: only the header is read here
        if src.width * src.height > MAX_SOURCE_PIXELS:
            raise RenderError("source image too large")
        if src.format == "JPEG":
            src.draft("RGB", (w, h))   # decode at 1/2, 1/4, 1/8 scale: the full-size bitmap is never held
        cap = MAX_DECODED_JPEG if src.format == "JPEG" else MAX_DECODED_PIXELS
        if src.width * src.height > cap:   # a PNG / WebP cannot be drafted: refuse before decoding
            raise RenderError("source image too large to decode")
        src = src.convert("RGB")
    except RenderError:
        raise
    except Exception:
        raise RenderError("not an image") from None
    return ImageOps.fit(src, (w, h), Image.LANCZOS, centering=(0.5, 0.5))


def _scrim(canvas: Image.Image, tpl: Template) -> None:
    if tpl.scrim_path is not None:
        with Image.open(tpl.scrim_path) as layer:
            layer = layer.convert("RGBA")
            canvas.paste(layer.convert("RGB"), (0, 0), layer.getchannel("A"))
        return
    band = tpl.data.get("scrim_band")
    if not band:
        return
    w, h = canvas.size
    y0, y1 = int(h * band["top"]), int(h * band["solid"])
    peak = 255 * band["opacity"]
    ramp = max(1, y1 - y0)

    def alpha(y):   # one smooth curve: flat where it starts (no seam), steep through the title, full at `solid`
        # (`solid` past 1.0 = never flat: still darkening under the sub-line, no solid band)
        x = min(1.0, y / ramp)
        return int(round(peak * (x * x * (3 - 2 * x)) ** 0.6))
    column = [alpha(y) for y in range(h - y0)]
    mask = Image.new("L", (1, h - y0))
    mask.putdata(column)
    mask = mask.resize((w, h - y0))
    canvas.paste(_rgb(band["colour"]), (0, y0, w, h), mask)


def _draw_lines(canvas, font, lines, size, tracking, colour, opacity, shadow, line_h):
    """Text (and its soft shadow) through an L mask cut to the text band only."""
    if not lines:
        return
    pad = int((shadow or {}).get("blur", 0) * 2 + abs((shadow or {}).get("dy", 0)) + 4)
    asc, desc = font.getmetrics()
    y0 = max(0, int(lines[0].top) - pad)
    y1 = min(canvas.height, int(max(lines[-1].top + line_h, (lines[-1].base or 0) + desc)) + pad)
    mask = Image.new("L", (canvas.width, y1 - y0), 0)
    d = ImageDraw.Draw(mask)
    for ln in lines:
        base = (ln.base if ln.base is not None else ln.top + (line_h - (asc + desc)) / 2 + asc) - y0
        if not tracking:
            d.text((ln.x, base), ln.text, font=font, fill=255, anchor="ls")
            continue
        x = ln.x
        for ch in ln.text:
            d.text((x, base), ch, font=font, fill=255, anchor="ls")
            x += font.getlength(ch) + tracking * size
    if shadow and shadow.get("opacity"):
        soft = mask.filter(ImageFilter.GaussianBlur(max(0.1, shadow["blur"] / 2)))
        soft = soft.point(lambda v, k=shadow["opacity"]: int(v * k))
        canvas.paste(_rgb(shadow["colour"]), (0, y0 + int(shadow["dy"])), soft)
        del soft
    if opacity < 1:
        mask = mask.point(lambda v, k=opacity: int(v * k))
    canvas.paste(_rgb(colour), (0, y0), mask)


def render(tpl: Template, art: bytes, title: str, sub: str = "") -> bytes:
    """One poster as JPEG bytes. Raises RenderError when `art` is not an image."""
    w, h = tpl.width, tpl.height
    canvas = _cover(art, w, h)
    _scrim(canvas, tpl)
    t = tpl.data["title"]
    lay = layout_title(tpl, title)
    if lay.lines:
        _draw_lines(canvas, _font(tpl, lay.size, t["weight"]), lay.lines, lay.size, float(t.get("tracking") or 0),
                    t["colour"], 1.0, t.get("shadow"), lay.size * float(t["line_height"]))
    box = rule_box(tpl, lay)
    if box:
        ImageDraw.Draw(canvas).rectangle((round(box[0]), round(box[1]), round(box[2]) - 1, round(box[3]) - 1),
                                         fill=_rgb(tpl.data["accent_rule"]["colour"]))
    s = tpl.data["sub"]
    if sub:
        size = int(s["size"])
        font = _font(tpl, size, s["weight"])
        tracking = float(s.get("tracking") or 0)
        room = w * (1 - 2 * t["margin_x"])
        text = sub if _width(font, sub, tracking, size) <= room else _ellipsise(font, sub, room, tracking, size)
        sw = _width(font, text, tracking, size)
        line = Line(text, (w - sw) / 2, sub_top(tpl, lay), sw)
        _draw_lines(canvas, font, [line], size, tracking, s["colour"], float(s.get("opacity", 1)), s.get("shadow"),
                    size * 1.2)
    if tpl.frame_path is not None:
        with Image.open(tpl.frame_path) as layer:
            layer = layer.convert("RGBA")
            canvas.paste(layer.convert("RGB"), (0, 0), layer.getchannel("A"))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


# ---- preview CLI ----

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hub.media_posters_render",
                                 description="Render one preview poster from a template kit (no network).")
    ap.add_argument("--template", default=str(STARTER), help="the kit folder (default: the starter kit)")
    ap.add_argument("--art", help="a poster image file (default: a grey placeholder)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--sub", default="", help='the sub-line, e.g. "2019" or "Seasons 1–5 · 2019–2024"')
    ap.add_argument("--out", required=True, help="the JPEG to write")
    ns = ap.parse_args(argv)
    try:
        tpl = load_template(ns.template)
    except TemplateError as exc:
        print("FAIL", exc)
        return 1
    data = Path(ns.art).read_bytes() if ns.art else _placeholder(tpl.width, tpl.height)
    Path(ns.out).write_bytes(render(tpl, data, ns.title, ns.sub))
    print(f"PASS wrote {ns.out} (template {tpl.version})")
    return 0


def _placeholder(w: int, h: int) -> bytes:
    """A plain two-tone placeholder poster (no network)."""
    im = Image.new("RGB", (w, h), (70, 78, 92))
    ImageDraw.Draw(im).rectangle((0, h // 2, w, h), fill=(48, 54, 66))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
