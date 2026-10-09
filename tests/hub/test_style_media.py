"""MediaHub restyle, Phase 3 of 4 (2026-10-06): the Media app is built from the guide's recipes (docs/style-guide.md
§4-§9). Pins: no retired class in any Media template, the row recipe on rendered lists, .empty for empty states,
the film page's detail hero, no literal colours outside :root, and no per-area --accent on Media."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_db
from tests.hub import test_shell
from tests.hub.test_media_downloads import env as dl_env  # noqa: F401  (fixture)
from tests.hub.test_media_frame import env as frame_env  # noqa: F401  (fixture)
from tests.hub.helpers import env as film_env, LINKED  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.test_media_library_pages import jelly
from tests.hub.test_media_watchlist import REQS

TEMPLATES = Path(__file__).resolve().parents[2] / "hub" / "templates"
PARTIALS = ["_library_row.html", "_diary_row.html", "_rated_row.html", "_rate_picker.html", "_rate.html",
            "_watchlist_btn.html", "_library_page.html", "_discover_item.html", "_discover_results.html",
            "_search_results.html", "_season_episodes.html", "_file_strip.html", "_detail_foot.html",
            "_request_block.html", "_year_list.html", "_waiting.html", "_media_tabs.html", "_rows.html",
            "_poster.html", "area_shelves.html"]
MEDIA = sorted(TEMPLATES.glob("media_*.html")) + [TEMPLATES / p for p in PARTIALS]
RETIRED = {"glassbtn", "hero", "shelfhead", "uprow", "waitchip", "libctl", "actbtn", "ratebox"}


def class_tokens(src):
    """Every word that can end up in a class attribute, including Jinja literals inside it."""
    out = set()
    for value in re.findall(r'class="([^"]*)"', src):
        out |= set(re.findall(r"[a-z][a-z0-9-]*", value))
    return out


def main_of(html):
    return html.split("<main", 1)[1]


# (a) no retired class anywhere in the Media templates
def test_media_templates_use_no_retired_class():
    assert len(MEDIA) > 30
    hits = {f.name: sorted(class_tokens(f.read_text(encoding="utf-8")) & RETIRED) for f in MEDIA}
    assert not {k: v for k, v in hits.items() if v}, hits


# (b) rows are the guide's row recipe, the score on the right graded or "—"
def test_rows_render_the_row_recipe_with_a_graded_or_missing_score(dl_env):
    media_db.set_rating("jf:ser1", 8, "tv", "Quiet Show")
    with dl_env(jellyfin=LINKED) as client:
        for path in ("/media/history", "/media/playing"):
            body = main_of(client.get(path).text)
            assert '<div class="listbox">' in body and re.search(r'<(a|div) class="row[ "]', body), path
            assert '<div class="row-title">' in body and '<div class="row-meta">' in body, path
            scores = re.findall(r'class="row-score (score-\d|score-none)', body)
            assert scores, path
    assert "score-8" in scores or "score-none" in scores


# (c) empty states are one sentence in .empty
def test_empty_watchlist_and_empty_diary_use_the_empty_box(frame_env):
    main = frame_env(jellyfin=jelly(), jellyseerr=REQS)
    with TestClient(main.app) as client:
        watch = main_of(client.get("/media/movies/watchlist").text)
    assert '<p class="empty">Nothing on the watchlist.</p>' in watch
    main = frame_env()
    with TestClient(main.app) as client:
        diary = main_of(client.get("/media/diary").text)
    assert '<p class="empty">Nothing in the diary yet.</p>' in diary


# (d) the film page is the detail hero: poster leads, facts line, ONE white primary
def test_film_page_renders_the_detail_hero(film_env):
    client, _ = film_env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    hero = re.search(r'<header class="pagehead hero-detail">.*?</header>', b, re.S).group(0)
    assert 'class="hero-detail-bd"' in hero and 'class="poster hero-detail-poster' in hero
    assert hero.index("hero-detail-poster") < hero.index('<h1 class="hero-detail-title">')   # the poster leads
    assert 'class="facts-line"' in hero and 'id="status-line"' in hero
    assert hero.count("btn-white") == 1 and "btn-icon" in hero
    assert 'class="scorepill sitepill"' in hero and '<nav class="sectabs"' in hero  # media-ux4 (2026-10-08, B.): one pill style (site links)
    assert '<div class="stats numbers">' in b


# (e) tokens only: no literal colour in the stylesheet outside :root, none in the Media templates
def test_no_literal_colour_outside_root_and_none_in_media_templates():
    test_shell.test_no_literal_colour_outside_the_token_block()
    for f in MEDIA:
        src = f.read_text(encoding="utf-8")
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b(?![^{]*\}\})", " ".join(re.findall(r'style="([^"]*)"', src))), f.name
        assert "rgb(" not in src and "rgba(" not in src, f.name


# (f) Media drops the per-area --accent (guide 1.2: colour is kept for meaning)
def test_no_accent_injection_on_media(frame_env):
    for f in MEDIA:
        code = re.sub(r"\{#.*?#\}", "", f.read_text(encoding="utf-8"), flags=re.S)   # comments may name it
        assert "--accent" not in code, f.name
    main = frame_env()
    with TestClient(main.app) as client:
        for path in ("/a/alpha", "/media/diary", "/media/playing", "/media/movies", "/media/movies/watchlist"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert "--accent" not in main_of(r.text), path
