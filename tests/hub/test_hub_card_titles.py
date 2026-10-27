"""JY-233 (B., 2026-10-24, round 2 B): each summary tile shows its area icon in a solid chip filled with the area's colour,
right before a bigger title. The colour is config (`tone:` in areas.yaml, a token name, validated by hub/registry.py) and
reaches the markup as --tone; an area with no tone keeps the neutral chip. Registry parsing, rendered markup, stylesheet pins."""
import importlib
import re
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.helpers import AREAS_YAML, make_area, write_envelope, write_registry
from tests.hub.test_hub_page import SAMPLE_DATA, cards_of, hub  # noqa: F401  (fixture: hub(view=..., **data))
from tests.hub.test_first_screens_e3 import rules
from tests.hub.tv_css import design_px

HUB = Path(__file__).resolve().parents[2] / "hub"
CSS = (HUB / "static" / "control-surface.css").read_text(encoding="utf-8")
TV_CSS = design_px((HUB / "static" / "tv.css").read_text(encoding="utf-8"))


# 1. The registry ----------------------------------------------------------------------------------------------------

def test_tone_is_parsed_from_the_registry_and_defaults_to_none(tmp_path):
    toned = make_area("a1")
    toned["tone"] = "teal"
    reg = load_registry(write_registry(tmp_path, toned, make_area("a2")))
    assert [a.tone for a in reg.areas] == ["teal", None]


def test_a_tone_that_is_not_a_known_token_is_refused(tmp_path):
    bad = make_area("a1")
    bad["tone"] = "#ff0000"
    with pytest.raises(ValueError, match="tone"):
        load_registry(write_registry(tmp_path, bad))


def test_real_registry_gives_every_hub_card_area_a_tone_token_that_exists():
    reg = load_registry(AREAS_YAML)
    css = CSS
    shown = [a for a in reg.visible_areas]
    assert shown and all(a.tone for a in shown)
    assert len({a.tone for a in shown}) == len(shown)                       # one colour per area
    for a in shown:
        assert re.search(rf"--{a.tone}:\s*#", css), a.tone                   # an existing :root token, not a new one


# 2. The markup ------------------------------------------------------------------------------------------------------

def test_every_hub_card_carries_its_tone_and_the_chip_comes_right_before_the_title(hub):
    main, body = hub()
    cards = cards_of(body)
    for a in main.shell.registry.visible_areas:
        card = cards[f"/a/{a.id}"]
        tag = re.search(rf'<(?:a|div) class="panel tile[^"]*"[^>]*href="/a/{a.id}"[^>]*>', body)             or re.search(rf'<div class="panel tile split[^"]*"[^>]*>\s*<a class="tile-body" href="/a/{a.id}"', body)
        assert tag, a.id
        assert f'data-tone="{a.tone}"' in tag.group(0) and f'style="--tone: var(--{a.tone})"' in tag.group(0), a.id
        assert re.search(r'<span class="tile-icon"><svg.*?</svg></span>\s*<div class="tile-main">\s*'
                         rf'<div class="microlabel">{a.name}</div>', card, re.S), a.id


def test_an_area_without_a_tone_renders_the_neutral_chip(tmp_path, monkeypatch):
    cfg = tmp_path / "areas.yaml"
    cfg.write_text(textwrap.dedent("""
        areas:
          - id: desk
            name: Desk
            icon: desk
            summary_tile: files
            tiles:
              - {id: files, label: NAS files, tier: embed, owner: you, snapshot: nas_stats,
                 stale_after_minutes: 120, detail: /weather, setup_note: x}
    """), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(cfg))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    write_envelope(tmp_path / "snaps", "nas_stats", age_minutes=1, data=SAMPLE_DATA["nas_stats"])
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        body = client.get("/").text
        area = client.get("/a/desk").text
    for html in (body, area):
        assert '<span class="tile-icon">' in html
        assert "data-tone" not in html and "--tone" not in html.split("<main", 1)[1]


def test_area_page_tiles_carry_the_same_tone(hub):
    main, _ = hub()
    a = next(a for a in main.shell.registry.visible_areas if a.layout == "grid")
    with TestClient(main.app) as client:
        html = client.get(f"/a/{a.id}").text
    k = re.search(r'<section class="tiles areatiles.*?</section>', html, re.S).group(0)
    assert k.count(f'style="--tone: var(--{a.tone})"') == k.count('panel tile') >= 1


# 3. The stylesheets -------------------------------------------------------------------------------------------------

def test_chip_title_and_tv_size_are_pinned():
    r = rules(CSS)
    assert re.search(r"\.tile-icon \{[^}]*width: 44px; height: 44px;[^}]*background: var\(--tone, var\(--soft\)\)", r)
    assert re.search(r"\.tile\[data-tone\] \.tile-icon \{ color: var\(--zinc-950\); \}", r)         # dark glyph on the colour
    assert re.search(r"\.tile-main \.microlabel \{[^}]*font-size: 17px; font-weight: 600; text-transform: none;", r)
    tv = rules(TV_CSS)
    assert "html.tv .tile-icon { width: 60px; height: 60px;" in tv
    assert "html.tv .tile-main .microlabel { font-size: 26px; }" in tv


def test_the_root_token_block_gained_no_tone_token():
    root = re.search(r":root \{.*?\n\}", CSS, re.S).group(0)
    assert "--tone" not in root
