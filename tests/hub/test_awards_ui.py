"""Awards UI (awards-ui, 2026-10-09): the visual pass on Movies / TV Shows > Awards, poster winner badges, the podium
and the film / person Awards sections. Item 1: the self-drawn ceremony marks (currentColor, labelled or aria-hidden
beside words, an override logo in hub/static/awards/ wins)."""
import re
from pathlib import Path

import jinja2
import pytest

from hub import media_awards_icons as icons

TEMPLATES = Path(__file__).resolve().parents[2] / "hub" / "templates"
ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True)


def icon(*args, **kw):
    t = ENV.from_string('{% from "_award_icons.html" import award_icon %}{{ award_icon(*a, **k) }}')
    return t.render(a=args, k=kw)


@pytest.mark.parametrize("name", icons.SHAPES)
def test_every_mark_is_a_labelled_current_colour_svg(name):
    out = icon(name, 20)
    assert out.startswith(f'<svg class="awic awic-{name}" viewBox="0 0 24 24" width="20" height="20" fill="currentColor"')
    assert re.search(r'role="img" aria-label="[^"]+"', out)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", out)                  # tints from the parent's colour only
    assert "<path" in out or "<circle" in out


def test_ceremony_marks_are_distinct_drawings():
    bodies = {n: re.sub(r'<svg[^>]*>', "", icon(n)) for n in icons.BODY_IDS}
    assert len(set(bodies.values())) == len(icons.BODY_IDS)
    assert re.sub(r'<svg[^>]*>', "", icon("trophy")) not in bodies.values()   # none falls back to the trophy


def test_names_labels_and_decorative_use():
    assert 'aria-label="Oscars"' in icon("oscars") and 'aria-label="Critics&#39; Choice"' in icon("critics")
    assert 'aria-label="Best Picture"' in icon("trophy", label="Best Picture")
    deco = icon("laurel", deco=True)
    assert 'aria-hidden="true"' in deco and "aria-label" not in deco and "role=" not in deco
    assert 'aria-label="Award"' in icon("no-such-mark")                        # unknown -> trophy, still labelled


def test_override_logo_wins_and_keeps_the_name_as_alt(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "OVERRIDE_DIR", tmp_path)
    icons.override.cache_clear()
    try:
        assert icons.override("oscars") is None
        (tmp_path / "oscars.svg").write_text("<svg/>", encoding="utf-8")
        assert icons.override("oscars") is None                               # cached per process (deploy-only folder)
        icons.override.cache_clear()
        assert icons.override("oscars") == "/static/awards/oscars.svg"
        assert icons.override("../etc") is None and icons.override("trophy") is None
    finally:
        icons.override.cache_clear()
    out = icon("oscars", 24, src="/static/awards/oscars.svg")
    assert out == '<img class="awic awlogo" src="/static/awards/oscars.svg" width="24" height="24" alt="Oscars">'
    assert 'alt=""' in icon("oscars", src="/x.svg", deco=True)


def test_shipped_override_folder_has_only_its_readme():
    files = sorted(p.name for p in icons.OVERRIDE_DIR.iterdir())
    assert files == ["README.md"]                                              # Joey ships no brand files


@pytest.mark.parametrize("name, shape", [
    ("Best Picture", "reel"), ("Outstanding Drama Series", "reel"), ("Palme d'Or", "reel"),
    ("Best Director", "clapper"), ("Outstanding Directing – Feature Film", "clapper"),
    ("Best Actor", "person"), ("Best Actress in a Supporting Role", "person"),
    ("Outstanding Performance by a Cast in a Motion Picture", "person"),
    ("Best Original Screenplay", "nib"), ("Outstanding Writing for a Drama Series", "nib"),
    ("Best Original Score", "trophy"), (None, "trophy")])
def test_category_icons(name, shape):
    assert icons.cat_icon(name) == shape


def test_icon_css_is_a_token_free_recipe():
    css = (TEMPLATES.parent / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert re.search(r"\.awic \{[^}]*flex-shrink: 0", css)
