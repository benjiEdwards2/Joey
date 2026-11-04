"""JY-304 option C (every .carousel shelf off the TV: edge fade, half-card peek, round prev / next buttons from 768 px)
and JY-305 option B (the Home carousel's "cinema" height), both picked by B. on 2026-11-04. Static pins on the
stylesheet and joey.js: the rules exist, stay off the TV (html.tv) and use tokens, not literal colours."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "hub" / "static"
CSS = (STATIC / "control-surface.css").read_text(encoding="utf-8")
JS = (STATIC / "joey.js").read_text(encoding="utf-8")
TV_CSS = (STATIC / "tv.css").read_text(encoding="utf-8")


def block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i) + len(end)]


CUE = block(CSS, "/* JY-304 option C", "@media (max-width: 767px) { html:not(.tv) .cue-arrow { display: none; } }")
HERO = block(CSS, '/* JY-305 option B "cinema"', "2400px); } }")
CUE_JS = block(JS, "/* JY-304 option C", "})();")


def test_fade_rules_follow_the_scroll_classes_off_the_tv():
    for cls in (".carousel.cue-more", ".carousel.cue-back.cue-more", ".carousel.cue-back:not(.cue-more)"):
        assert f"html:not(.tv) {cls} {{" in CUE, cls
    assert CUE.count("mask-image") >= 6   # -webkit- and plain, three states


def test_half_card_peek_on_every_width():
    for n, bp in ((3.5, None), (5.5, 640), (7.5, 1200), (9.5, 1920), (11.5, 3000)):
        rule = f"/ {n}); width:"
        assert rule in CUE, n
        if bp:
            assert f"@media (min-width: {bp}px) {{ html:not(.tv) .carousel:not(.prov-row) > * {{ flex-basis: calc((100% - {int(n - .5)} * 12px) / {n})" in CUE
    # the old fixed 184 / 216 px row cards are gone (they would win over the peek on wide screens)
    assert ".carousel:not(.prov-row) > *, html:not(.tv) .moresec .carousel > * { flex-basis: 184px" not in CSS


def test_arrows_from_768_hidden_at_the_ends_and_never_on_tv():
    assert "@media (max-width: 767px) { html:not(.tv) .cue-arrow { display: none; } }" in CUE
    assert "html:not(.tv) .cue-arrow[hidden] { display: none; }" in CUE and "html.tv" not in CUE
    assert "html:not(.tv) .cue-arrow:focus-visible" in CUE
    assert "cue-arrow" not in TV_CSS


def test_script_builds_labelled_buttons_on_every_carousel_but_not_on_tv():
    assert "classList.contains('tv')) return;" in CUE_JS
    assert "querySelectorAll('.carousel')" in CUE_JS
    assert "'Scroll left'" in CUE_JS and "'Scroll right'" in CUE_JS and "aria-label" in CUE_JS
    assert "b.type = 'button'" in CUE_JS            # a real button: keyboard focusable
    assert "btn.prev.hidden = !back" in CUE_JS and "btn.next.hidden = !more" in CUE_JS
    assert "classList.toggle('cue-more', more)" in CUE_JS and "classList.toggle('cue-back', back)" in CUE_JS
    assert "htmx:load" in CUE_JS


def test_home_carousel_cinema_height():
    assert "@media (min-width: 768px) { html:not(.tv) .homecar { --slide-w: min(86vw, calc(min(55vh, 600px) * 16 / 9)); } }" in HERO
    assert "@media (min-width: 1100px) { html:not(.tv) .homecar { --slide-w: min(86vw, calc(min(75vh, 800px) * 16 / 9), 1800px); } }" in HERO
    # from 1920 never shorter than the old 58vh slide
    assert "max(calc(min(75vh, 800px) * 16 / 9), calc(58vh * 16 / 9))" in HERO
    assert "aspect-ratio: 16 / 9" in CSS   # slides stay 16:9


def test_no_literal_colours_in_the_new_rules():
    for src in (CUE, HERO):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|\bblack\b|\bwhite\b", src)
