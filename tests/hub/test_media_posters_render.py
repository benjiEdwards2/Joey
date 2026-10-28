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
    assert (t["title_anchor"], s["sub_anchor"], t["margin_x"]) == (0.74, 0.88, 0.06)
    assert tpl.data["frame"] is None                      # layout 2: no frame, no border
    band = tpl.data["scrim_band"]
    assert band["top"] == pytest.approx(0.60) and band["solid"] > band["top"]   # the bottom ~40 %, fading upward
    assert tpl.font_path.name == "GeistVF.woff2"
    assert r.validate(tpl.data, r.STARTER) == []


# ---- layout maths ----

def _inside(lay, tpl):
    left, right = tpl.width * 0.06, tpl.width * (1 - 0.06)
    for ln in lay.lines:
        assert left - 0.5 <= ln.x and ln.x + ln.width <= right + 0.5, ln
        assert abs((ln.x + ln.width / 2) - tpl.width / 2) <= 1, ln     # centred


def test_short_title_one_line_at_max_size_on_the_anchor(tpl):
    lay = r.layout_title(tpl, "Up")
    assert [ln.text for ln in lay.lines] == ["UP"]                     # uppercase per the kit
    assert lay.size == 95
    assert lay.top == pytest.approx(0.74 * 1500)
    assert lay.lines[0].top == pytest.approx(0.74 * 1500)
    _inside(lay, tpl)


def test_second_short_title_also_fits_at_max(tpl):
    lay = r.layout_title(tpl, "The Bear")
    assert len(lay.lines) == 1 and lay.size == 95
    _inside(lay, tpl)


def test_medium_title_shrinks_before_it_wraps(tpl):
    lay = r.layout_title(tpl, "Everything Everywhere")
    assert len(lay.lines) == 1
    assert 52 <= lay.size < 95
    _inside(lay, tpl)


def test_long_title_wraps_to_two_balanced_lines(tpl):
    lay = r.layout_title(tpl, LONG)
    assert len(lay.lines) == 2
    assert lay.size >= 52
    a, b = (ln.width for ln in lay.lines)
    assert min(a, b) / max(a, b) > 0.6                                  # balanced, not one word on line 2
    assert lay.lines[1].top == pytest.approx(lay.lines[0].top + lay.size * 1.05)
    assert " ".join(ln.text for ln in lay.lines) == LONG.upper()
    _inside(lay, tpl)


def test_two_lines_stay_above_the_sub_line(tpl):
    lay = r.layout_title(tpl, LONG)
    assert lay.bottom <= 0.88 * 1500


def test_very_long_title_is_capped_at_max_lines_with_an_ellipsis(tpl):
    lay = r.layout_title(tpl, VERY_LONG)
    assert len(lay.lines) == 2 and lay.size == 52
    assert lay.lines[-1].text.endswith("…")
    _inside(lay, tpl)


def test_one_huge_word_shrinks_then_ellipsises(tpl):
    lay = r.layout_title(tpl, "Supercalifragilisticexpialidociousnessly")
    assert len(lay.lines) == 1 and lay.lines[0].text.endswith("…")
    _inside(lay, tpl)


def test_max_lines_one_never_wraps(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.max_lines": 1}))
    lay = r.layout_title(t, LONG)
    assert len(lay.lines) == 1


def test_moving_the_anchor_moves_the_title(tmp_path):
    t = r.load_template(kit(tmp_path, **{"title.title_anchor": 0.5, "sub.sub_anchor": 0.7}))
    assert r.layout_title(t, "Up").top == pytest.approx(750)


# ---- the sub-line ----

def test_sub_line_words():
    assert r.sub_line("movie", year=2019) == "2019"                     # Q7A
    assert r.sub_line("movie") == ""
    assert r.sub_line("tv", year=2019, seasons=(1, 5), years=(2019, 2024)) == ""   # phase-2 switch off by default
    on = dict(series_sub=True)
    assert r.sub_line("tv", seasons=(1, 5), years=(2019, 2024), **on) == "Seasons 1–5 · 2019–2024"
    assert r.sub_line("tv", seasons=(1, 1), years=(2022, 2022), **on) == "Season 1 · 2022"
    assert r.sub_line("tv", seasons=(1, 3), years=(2021, None), **on) == "Seasons 1–3 · 2021–"
    assert r.sub_line("tv", year=2021, **on) == "2021"


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
        r.load_template(kit(tmp_path, **{"sub.sub_anchor": 0.78}))


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


def test_render_draws_the_title_in_the_lower_third(tpl):
    plain = Image.open(io.BytesIO(r.render(tpl, art(colour=(40, 40, 40)), "", ""))).convert("L")
    titled = Image.open(io.BytesIO(r.render(tpl, art(colour=(40, 40, 40)), "The Bear", "2022"))).convert("L")
    lay = r.layout_title(tpl, "The Bear")
    box = (int(lay.lines[0].x), int(lay.top), int(lay.lines[0].x + lay.lines[0].width), int(lay.bottom))
    assert max(titled.crop(box).tobytes()) > 200 > max(plain.crop(box).tobytes())
    upper = (0, 0, 1000, 1000)
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
