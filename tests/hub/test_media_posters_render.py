"""JY-260 phase 1 - the poster renderer and the template kit (spec docs/specs/JY-260-posters.md).

Layout maths (title top at title_anchor, 6 % margins, centred, shrink then a balanced 2-line wrap, then an ellipsis),
the sub-line words (Q7A: a film's year; a series' "Seasons a-b · yyyy-yyyy" only behind the phase-2 switch),
template.json validation (the starter passes; a bad kit is refused naming every problem) and a real render
(JPEG at the canvas size, the scrim darkens the lower third, the title is drawn there). No network."""
import io
import json
import shutil

import pytest
from PIL import Image

from hub import media_posters_render as r

LONG = "The Assassination of Jesse James by the Coward"     # 46 characters
TA, SA, GAP, LIMIT = 0.75, 0.84, 0.02, 0.62   # B.'s Canva layout (2026-10-28) in the starter kit
VERY_LONG = "Night of the Day of the Dawn of the Son of the Bride of the Return of the Revenge of the Terror"


@pytest.fixture()
def tpl():
    return r.load_template(r.STARTER)


def kit(tmp_path, **changes):
    """A copy of the starter kit in tmp_path with template.json changed (dotted keys, None deletes)."""
    folder = tmp_path / "kit"
    shutil.copytree(r.STARTER, folder)
    data = json.loads((folder / "template.json").read_text(encoding="utf-8"))
    for key, value in changes.items():
        *path, last = key.split(".")
        node = data
        for p in path:
            node = node[p]
        if value is None:
            node.pop(last, None)
        else:
            node[last] = value
    (folder / "template.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def art(w=2000, h=3000, colour=(120, 130, 140), fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, fmt)
    return buf.getvalue()


# ---- the starter kit ----

def test_starter_kit_is_layout_2_with_layout_3_text_positions(tpl):
    assert (tpl.width, tpl.height) == (1000, 1500)
    t, s = tpl.data["title"], tpl.data["sub"]
    assert (t["title_anchor"], s["sub_anchor"], t["margin_x"]) == (TA, SA, 0.06)
    assert (t["weight"], s["weight"], t["uppercase"]) == (900, 500, True)   # B.'s friend's look: Geist Black, Medium
    assert (t["title_fill"], t["max_size"], t["max_cap_height"], t["line_height"], t["tracking"], s["tracking"]) == (
        0.88, 400, 0.14, 0.92, 0.02, 0.08)
    assert tpl.data["accent_rule"] == {"colour": "#E0B04A", "width": 0.09, "height": 6, "gap": 24}
    assert t["shadow"]["opacity"] <= 0.35 and s["shadow"]["opacity"] <= 0.35   # only a very soft shadow
    assert s["opacity"] == 1.0 and s["colour"] == "#FFFFFF"
    assert tpl.data["frame"] is None                      # layout 2: no frame, no border
    band = tpl.data["scrim_band"]
    assert 0.48 <= band["top"] <= 0.56 and band["solid"] > 1.0           # one gradient over the lower half, never flat
    assert (t["max_lines"], t["min_size"]) == (3, 40)
    assert (t["title_anchor_mode"], t["title_gap"]) == ("bottom", GAP)   # taller titles grow upward
    assert tpl.font_path.name == "GeistVF.woff2"
    assert r.validate(tpl.data, r.STARTER) == []


# ---- layout maths ----

def _inside(lay, tpl):
    left, right = tpl.width * 0.06, tpl.width * (1 - 0.06)
    for ln in lay.lines:
        assert left - 0.5 <= ln.x and ln.x + ln.width <= right + 0.5, ln
        assert abs((ln.x + ln.width / 2) - tpl.width / 2) <= 1, ln     # centred


ROOM, FILL = 880, 0.88   # the safe width (6 % margins on 1000 px) and the starter's title_fill


def _fill(lay):
    return max(ln.width for ln in lay.lines) / ROOM


def test_short_title_one_line_at_max_size_grows_up_from_the_anchor(tpl):
    """B. 2026-10-28: "Posters bigger is better." "UP" is held by the sanity cap (its glyphs at most 14 % of the
    canvas height); at that size its real ink is taller than the room under the anchor, so the block rises
    (bottom-anchored), its ink bottom on the gap above the sub-line."""
    lay = r.layout_title(tpl, "Up")
    font = r._font(tpl, lay.size, 900)
    ink = font.getbbox("H", anchor="ls")                                     # the capital height
    assert [ln.text for ln in lay.lines] == ["UP"] and (ink[3] - ink[1]) <= 0.14 * 1500 + 1
    assert (ink[3] - ink[1]) >= 0.13 * 1500                                  # at the cap, not under it
    assert lay.bottom == pytest.approx((SA - GAP) * 1500) and LIMIT * 1500 <= lay.top < TA * 1500
    _inside(lay, tpl)


@pytest.mark.parametrize("title,n,lo,hi", [("The Bear", 1, 0.85, FILL), ("Everything Everywhere", 2, 0.85, FILL),
                                           ("Eternal Sunshine of the Spotless Mind", 3, 0.85, FILL),
                                           ("The Assassination of Jesse James by the Coward Robert Ford", 3, 0.85,
                                            FILL)])
def test_titles_fill_about_title_fill_of_the_safe_width(tpl, title, n, lo, hi):
    """Short (that are not capped), medium and long titles: the widest line fills 85-88 % of the safe width."""
    lay = r.layout_title(tpl, title)
    assert len(lay.lines) == n and lo <= _fill(lay) <= hi + 0.005, (lay.size, _fill(lay))
    assert " ".join(ln.text for ln in lay.lines) == title.upper()
    _inside(lay, tpl)


def test_short_titles_are_larger_than_long_ones(tpl):
    sizes = [r.layout_title(tpl, t).size for t in ("Up", "The Bear", "Everything Everywhere", LONG)]
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > 250 and sizes[-1] >= 40


@pytest.mark.parametrize("title", ["War", "Silo", "Troy", "Suits"])
def test_short_titles_fill_about_088_of_the_width(tpl, title):
    """The review of #260: short titles filled ~45 % at the old 190 px cap; now about 0.85-0.9, like B.'s reference."""
    lay = r.layout_title(tpl, title)
    assert len(lay.lines) == 1 and 0.83 <= _fill(lay) <= 0.885, (title, lay.size, _fill(lay))


def test_a_two_letter_title_is_held_by_the_cap_height(tpl):
    lay = r.layout_title(tpl, "It")
    ink = r._font(tpl, lay.size, 900).getbbox("H", anchor="ls")
    assert ink[3] - ink[1] <= 0.14 * 1500 + 1 and _fill(lay) < 0.85


def test_a_medium_title_shrinks_to_wrap_at_then_wraps(tpl):
    lay = r.layout_title(tpl, "Everything Everywhere")
    assert len(lay.lines) == 2 and lay.size >= 96                       # one line would be under wrap_at (96)
    a, b = (ln.width for ln in lay.lines)
    assert min(a, b) / max(a, b) > 0.5
    assert lay.lines[1].top == pytest.approx(lay.lines[0].top + lay.size * 0.92)   # line height 0.92
    _inside(lay, tpl)


def test_fill_1_is_the_phase_1_behaviour(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.title_fill": None}))
    assert _fill(r.layout_title(t, "Everything Everywhere")) > 0.9


@pytest.mark.parametrize("title,n", [("Up", 1), ("Everything Everywhere", 2),
                                     ("The Assassination of Jesse James by the Coward Robert Ford", 3),
                                     ("The Lord of the Rings The Return of the King Extended Edition Part Two", 3)])
def test_title_box_never_meets_the_sub_line_box(tpl, title, n):
    lay = r.layout_title(tpl, title)
    assert len(lay.lines) == n
    sub_top = SA * 1500
    sub_bottom = sub_top + 50 * 1.2                                       # the sub-line's line box
    assert lay.bottom <= sub_top - GAP * 1500 + 0.5                     # the fixed gap above the sub-line
    assert lay.bottom <= sub_top or lay.top >= sub_bottom                 # the boxes never intersect
    assert lay.top >= LIMIT * 1500 - 0.5                                   # grows upward, no higher than the limit


@pytest.mark.parametrize("title", ["Up", "It", "Heat", "Troy", "Silo", "War", "Close"])
def test_no_overlap_at_max_size_with_the_real_ink_height(tpl, title):
    """A tall single line at the new max (the cap height): its real glyphs end above the gap, the rule sits under
    them, the sub-line under the rule (measured on the drawn pixels, not on boxes)."""
    lay = r.layout_title(tpl, title)
    assert lay.size >= 200
    font = r._font(tpl, lay.size, 900)
    ink = font.getbbox(lay.lines[0].text, anchor="ls")
    assert lay.lines[0].base + ink[3] <= (SA - GAP) * 1500 + 0.5           # the glyphs, not a nominal line box
    left, top, right, bottom = r.rule_box(tpl, lay)
    assert top == pytest.approx(lay.bottom + 24) and bottom - top == 6 and right - left == pytest.approx(90)
    assert abs((left + right) / 2 - 500) < 0.5                               # centred
    assert r.sub_top(tpl, lay) >= bottom + 24 and r.sub_top(tpl, lay) + 50 * 1.2 <= 1500
    out = Image.open(io.BytesIO(r.render(tpl, art(colour=(20, 20, 20)), title, "2024"))).convert("RGB")
    rows = [y for y in range(900, 1500) if any(out.getpixel((x, y))[0] > 150 for x in range(60, 940, 3))]
    runs, start = [], rows[0]
    for a, b in zip(rows, rows[1:]):
        if b != a + 1:
            runs.append((start, a))
            start = b
    runs.append((start, rows[-1]))
    assert len(runs) == 3, runs                                          # title, rule, sub-line: three separate bands


def test_the_title_ink_never_reaches_the_sub_line(tmp_path):
    """Pixels, not boxes: render the 3-line title with no sub-line (and no rule), and nothing bright reaches the gap."""
    tpl = r.load_template(kit(tmp_path, accent_rule=None))
    out = Image.open(io.BytesIO(r.render(tpl, art(colour=(20, 20, 20)),
                                         "The Assassination of Jesse James by the Coward Robert Ford", ""))).convert("L")
    gap = out.crop((0, int(SA * 1500 - 0.015 * 1500), 1000, int(SA * 1500) + 60))
    assert max(gap.tobytes()) < 120


def test_top_mode_still_hangs_from_the_anchor(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.title_anchor_mode": "top", "title.title_top_limit": None,
                                         "title.max_lines": 2}))
    lay = r.layout_title(t, "The Assassination of Jesse James by the Coward Robert Ford")
    assert lay.top == pytest.approx(TA * 1500) and lay.bottom <= (SA - GAP) * 1500 + 0.5


def test_bad_anchor_mode_is_refused(tmp_path):
    with pytest.raises(r.TemplateError, match="title_anchor_mode"):
        r.load_template(kit(tmp_path, **{"title.title_anchor_mode": "middle"}))


def test_two_lines_stay_above_the_sub_line(tpl):
    lay = r.layout_title(tpl, LONG)
    assert lay.bottom <= SA * 1500


def test_a_59_character_title_is_never_cut(tpl):
    title = "The Assassination of Jesse James by the Coward Robert Ford"
    lay = r.layout_title(tpl, title)
    assert not lay.truncated and len(lay.lines) <= 3
    assert " ".join(ln.text for ln in lay.lines) == title.upper()         # every word kept
    assert lay.bottom <= SA * 1500 + 0.5
    _inside(lay, tpl)


def test_three_lines_fit_between_the_anchors(tpl):
    lay = r.layout_title(tpl, "The Lord of the Rings The Return of the King Extended Edition Part Two")
    assert len(lay.lines) == 3 and 40 <= lay.size <= 95
    assert lay.bottom <= (SA - GAP) * 1500 + 0.5 and lay.top >= LIMIT * 1500 - 0.5 and not lay.truncated
    _inside(lay, tpl)


def test_only_past_the_hard_floor_is_a_title_ellipsised_and_flagged(tpl):
    lay = r.layout_title(tpl, VERY_LONG * 2)
    assert len(lay.lines) == 3 and lay.size == 40 and lay.truncated
    assert lay.lines[-1].text.endswith("…")
    _inside(lay, tpl)
    assert not r.layout_title(tpl, VERY_LONG).truncated


def test_one_huge_word_shrinks_then_ellipsises(tpl):
    lay = r.layout_title(tpl, "Supercalifragilisticexpialidociousnessly")
    assert len(lay.lines) == 1 and lay.lines[0].text.endswith("…") and lay.truncated
    _inside(lay, tpl)


def test_max_lines_one_never_wraps(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.max_lines": 1}))
    lay = r.layout_title(t, LONG)
    assert len(lay.lines) == 1


def test_moving_the_anchor_moves_the_title(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.title_anchor": 0.5, "title.title_top_limit": 0.4,
                                         "sub.sub_anchor": 0.7}))
    assert r.layout_title(t, "Up").top == pytest.approx(750)


# ---- the sub-line ----

def test_sub_line_words():
    assert r.sub_line("movie", year=2019) == "2019"                     # Q7A
    assert r.sub_line("movie") == ""
    assert r.sub_line("tv", year=2019, seasons=[1, 2, 3, 4]) == "Seasons 1–4"   # no years (B. 2026-10-28)
    assert r.sub_line("tv", seasons=[1]) == "Season 1"                  # one season
    assert r.sub_line("tv", seasons=[0, 1]) == "Season 1"               # specials never count
    assert r.sub_line("tv", seasons=[2, 0, 3]) == "Seasons 2–3"
    assert r.sub_line("tv", seasons=[]) == "" and r.sub_line("tv", seasons=[0]) == ""
    assert r.sub_line("season", season=2) == "Season 2"                 # a season item
    assert r.sub_line("season", season=0) == ""


# ---- validation ----

def test_bad_template_is_refused_naming_every_problem(tmp_path):
    folder = kit(tmp_path, **{"title.title_anchor": 1.4, "canvas": [1000, 1000], "title.colour": "red",
                              "font.file": "Nope.ttf", "scrim": "scrim.png", "sub.sub_anchor": None,
                              "title.min_size": 200})
    with pytest.raises(r.TemplateError) as exc:
        r.load_template(folder)
    text = str(exc.value)
    for words in ("title.title_anchor", "canvas", "title.colour", "Nope.ttf", "scrim.png", "sub.sub_anchor",
                  "title.min_size"):
        assert words in text, words
    assert len(exc.value.problems) >= 7


def test_title_that_would_run_into_the_sub_line_is_refused(tmp_path):
    with pytest.raises(r.TemplateError, match="sub.sub_anchor"):
        r.load_template(kit(tmp_path, **{"sub.sub_anchor": 0.66}))


def test_not_json_is_a_clear_error(tmp_path):
    folder = kit(tmp_path)
    (folder / "template.json").write_text("{ nope", encoding="utf-8")
    with pytest.raises(r.TemplateError, match="template.json is not valid JSON"):
        r.load_template(folder)


def test_missing_template_json_is_a_clear_error(tmp_path):
    with pytest.raises(r.TemplateError, match="no template.json"):
        r.load_template(tmp_path)


def test_layer_png_must_match_the_canvas_and_have_alpha(tmp_path):
    folder = kit(tmp_path, scrim="scrim.png", frame="frame.png")
    Image.new("RGB", (1000, 1500)).save(folder / "scrim.png")             # no transparency
    Image.new("RGBA", (500, 750)).save(folder / "frame.png")              # wrong size
    with pytest.raises(r.TemplateError) as exc:
        r.load_template(folder)
    text = str(exc.value)
    assert "scrim.png" in text and "transparent" in text
    assert "frame.png" in text and "1000 × 1500" in text


def test_version_changes_when_any_kit_file_changes(tmp_path):
    folder = kit(tmp_path, scrim="scrim.png")
    Image.new("RGBA", (1000, 1500), (0, 0, 0, 0)).save(folder / "scrim.png")
    v1 = r.load_template(folder).version
    Image.new("RGBA", (1000, 1500), (0, 0, 0, 40)).save(folder / "scrim.png")
    assert r.load_template(folder).version != v1


# ---- the render ----

def test_render_is_a_jpeg_at_the_canvas_size_with_the_scrim_low(tpl):
    out = r.render(tpl, art(1500, 1500, (150, 150, 150)), "", "")       # square art: cover-cropped
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and im.size == (1000, 1500)
    top, low = im.getpixel((500, 300)), im.getpixel((20, 1450))
    assert abs(top[0] - 150) <= 3                                       # untouched above the band
    assert low[0] < 60                                                  # dark under the lower third


def test_the_accent_rule_can_be_turned_off_and_the_sub_line_then_stays_at_its_anchor(tmp_path):
    tpl = r.load_template(kit(tmp_path, accent_rule=None))
    lay = r.layout_title(tpl, "Up")
    assert r.rule_box(tpl, lay) is None and r.sub_top(tpl, lay) == pytest.approx(SA * 1500)


def test_a_bad_accent_rule_is_refused(tmp_path):
    with pytest.raises(r.TemplateError) as e:
        r.load_template(kit(tmp_path, accent_rule={"colour": "gold", "width": 2, "height": 0, "gap": 18}))
    assert all(w in str(e.value) for w in ("accent_rule.colour", "accent_rule.width", "accent_rule.height"))


def test_the_new_look_is_a_new_template_version(tpl, tmp_path, monkeypatch):
    """B. 2026-10-28: every stored poster re-renders. The drawing code bumped RENDER_VERSION (3, "bigger") and the
    starter kit's template.json changed, and either alone gives a new version."""
    assert r.RENDER_VERSION == 3
    monkeypatch.setattr(r, "RENDER_VERSION", 2)
    assert r.load_template(r.STARTER).version != tpl.version


def test_scrim_is_one_smooth_gradient_with_no_seam(tpl):
    im = Image.open(io.BytesIO(r.render(tpl, art(1000, 1500, colour=(200, 200, 200), fmt="PNG"), "", ""))).convert("L")
    col = [im.getpixel((500, y)) for y in range(0, 1500, 10)]
    assert col[0] >= 195 and col[-1] < 60                               # untouched top, dark bottom
    assert all(b <= a + 2 for a, b in zip(col, col[1:]))                 # only ever darker going down
    steps = [a - b for a, b in zip(col, col[1:])]
    assert max(steps) <= 12                                              # no hard edge anywhere
    assert col[-1] < col[-5] - 1                                         # still fading under the sub-line: no flat band
    start = next(i for i, v in enumerate(col) if v < 195) * 10
    assert 0.48 * 1500 <= start <= 0.55 * 1500


def test_render_draws_the_title_in_the_lower_third(tpl):
    plain = Image.open(io.BytesIO(r.render(tpl, art(colour=(40, 40, 40)), "", ""))).convert("L")
    titled = Image.open(io.BytesIO(r.render(tpl, art(colour=(40, 40, 40)), "The Bear", "2022"))).convert("L")
    lay = r.layout_title(tpl, "The Bear")
    box = (int(lay.lines[0].x), int(lay.top), int(lay.lines[0].x + lay.lines[0].width), int(lay.bottom))
    assert max(titled.crop(box).tobytes()) > 200 > max(plain.crop(box).tobytes())
    upper = (0, 0, 1000, 700)
    assert max(titled.crop(upper).tobytes()) < 80                        # nothing drawn in the top two thirds


def test_render_uses_a_frame_png_on_top(tmp_path):
    folder = kit(tmp_path, frame="frame.png")
    frame = Image.new("RGBA", (1000, 1500), (0, 0, 0, 0))
    frame.paste((255, 0, 0, 255), (0, 0, 1000, 20))
    frame.save(folder / "frame.png")
    im = Image.open(io.BytesIO(r.render(r.load_template(folder), art(), "Up", "")))
    px = im.getpixel((500, 5))
    assert px[0] > 200 and px[1] < 60


def test_render_rejects_bytes_that_are_not_an_image(tpl):
    with pytest.raises(r.RenderError):
        r.render(tpl, b"not an image", "Up", "")


# ---- hardening (review round, 2026-10-28) ----

def test_a_large_png_is_refused_before_it_is_decoded(tpl, monkeypatch):
    big = art(2600, 3900, fmt="PNG")                                     # 10.1 M pixels: ~40 MB as RGBA
    loads = []
    real = Image.Image.load
    monkeypatch.setattr(Image.Image, "load", lambda self: loads.append(self.size) or real(self))
    with pytest.raises(r.RenderError, match="too large"):
        r.render(tpl, big, "Up", "")
    assert (2600, 3900) not in loads                                     # never decoded at full size


def test_a_png_under_the_cap_renders(tpl):
    assert Image.open(io.BytesIO(r.render(tpl, art(1600, 2400, fmt="PNG"), "Up", ""))).size == (1000, 1500)


def test_a_large_jpeg_decodes_at_reduced_scale(tpl, monkeypatch):
    big = art(4000, 6000)                                                # 24 M pixels as a JPEG
    sizes = []
    real = Image.Image.convert
    monkeypatch.setattr(Image.Image, "convert", lambda self, *a, **k: sizes.append(self.size) or real(self, *a, **k))
    Image.open(io.BytesIO(r.render(tpl, big, "Up", "")))
    assert sizes and max(w * h for w, h in sizes) <= r.MAX_DECODED_JPEG
    assert sizes[0] == (1000, 1500)                                      # drafted at 1/4


def test_a_huge_header_is_refused(tpl):
    buf = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buf, "PNG")                        # 81 M pixels, tiny file
    with pytest.raises(r.RenderError, match="too large"):
        r.render(tpl, buf.getvalue(), "Up", "")


def test_a_600_word_title_is_capped_fast_and_flagged(tpl):
    import time
    start = time.perf_counter()
    lay = r.layout_title(tpl, " ".join(["word"] * 600))
    assert time.perf_counter() - start < 1.0
    assert lay.truncated and len(" ".join(ln.text for ln in lay.lines)) <= r.MAX_TITLE_CHARS


def test_121_characters_is_flagged_120_is_not_cut_by_the_cap(tpl):
    t120 = ("Abc " * 30)[:120].strip()
    assert len(r.layout_title(tpl, "A" * 3 + " " + "b" * 117).lines) >= 1
    lay = r.layout_title(tpl, t120 + "xyz")
    assert lay.truncated and lay.lines[-1].text.endswith("…")


def test_template_file_size_caps(tmp_path):
    folder = kit(tmp_path)
    (folder / "template.json").write_text(json.loads(json.dumps(" ")) * 70_000 + (folder / "template.json")
                                          .read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(r.TemplateError, match="over 64 KB"):
        r.load_template(folder)
    folder = kit(tmp_path / "png", scrim="scrim.png")
    Image.new("RGBA", (1000, 1500), (0, 0, 0, 0)).save(folder / "scrim.png")
    with open(folder / "scrim.png", "ab") as fh:
        fh.write(b"\0" * (10 * 1024 * 1024))
    with pytest.raises(r.TemplateError, match="scrim: scrim.png is over 10 MB"):
        r.load_template(folder)
    folder = kit(tmp_path / "font", **{"font.file": "Big.ttf"})
    (folder / "Big.ttf").write_bytes((r.HUB_FONTS / "GeistVF.woff2").read_bytes() + b"\0" * (5 * 1024 * 1024))
    with pytest.raises(r.TemplateError, match="Big.ttf is over 5 MB"):
        r.load_template(folder)
