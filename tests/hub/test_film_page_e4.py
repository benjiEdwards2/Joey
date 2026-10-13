"""E4 (U5-U7, 2026-10-13, B.): the film page's hero order and its one action row.

Phone order: poster > title > tagline / facts > status line (+ upgrade note, flashes) > ONE action row > "More" >
makers (Directed by / Created by) > the rest. The row holds at most four md (36 px) controls - Play (white; Request when
not on the server) · Trailer · watchlist · Seerr; Mark watched / Reset progress / Mark unwatched / Request beside Play /
Search now sit under a "More" <details class="fold"> with the inline .confirm panel. The IMDb / TMDB / Letterboxd pills
are in the Scores strip; item / title pages draw no sub-tab row. Jellyfin and Jellyseerr are faked (tests/hub/helpers).
"""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub import media_nav
from tests.hub.conftest import main_of
from tests.hub.film_page import whole
from tests.hub.helpers import ITEMS, SHOW, env  # noqa: F401  (env: the film-page fixture)

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
ROW = '<div class="hero-detail-btns">'
MORE = '<details class="fold heromore">'


def hero(b):
    return b.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


def row_of(h):
    """The action row's markup (up to the More fold, or the row's own closing tag)."""
    rest = h.split(ROW, 1)[1]
    return rest.split(MORE, 1)[0] if MORE in rest else rest.split("\n        </div>", 1)[0]


def more_of(h):
    return h.split(MORE, 1)[1].split("\n        </details>", 1)[0] if MORE in h else ""


def controls(row):
    return re.findall(r'<(?:a|button)[^>]*class="(btn [^"]*)"', row)


def order(h, *marks):
    at = [h.index(m) for m in marks]
    return at == sorted(at)


def set_ud(monkeypatch, item="mov1", **ud):
    monkeypatch.setitem(ITEMS[item], "UserData", {"Played": False, "PlaybackPositionTicks": 0, **ud})


# ---- U5: the order of the hero blocks (one DOM: the phone reads it top to bottom) ----

def test_film_hero_reads_poster_title_facts_status_row_more_makers(env, monkeypatch):
    monkeypatch.setenv("RADARR_URL", "http://radarr.secret-host.invalid:7878")
    monkeypatch.setenv("RADARR_API_KEY", "r-SECRET")
    client, _ = env()
    with client:
        whole(client, "/media/title/movie/603")                       # caches the title body: the tagline draws inline
        h = hero(main_of(whole(client, "/media/item/mov1")))
    assert order(h, "hero-detail-poster", '<h1 class="hero-detail-title">', '<p class="tagline">Come home</p>',
                 'class="facts-line"', 'id="status-line"', ROW, MORE, '<div class="makers">')


def test_show_and_episode_heroes_keep_the_same_order(env):
    client, _ = env()
    with client:
        show = hero(main_of(whole(client, "/media/item/ser1")))
        ep = hero(main_of(whole(client, "/media/item/ep3")))
    assert order(show, '<h1 class="hero-detail-title">', 'class="facts-line"', 'id="status-line"', ROW,
                 '<div class="makers">', 'class="followform"')
    assert "Created by" in show.split(ROW, 1)[1]
    # an episode: its code / name leads the title; its overview is "the rest", under the row and the makers
    assert order(ep, "S04E03 · Penny for Your Thoughts", '<h1 class="hero-detail-title">', 'id="status-line"', ROW,
                 '<div class="makers">', "Coins go missing.")


def test_title_not_on_the_server_has_request_first_then_makers(env):
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/title/movie/701")))
    assert order(h, '<h1 class="hero-detail-title">', 'id="status-line"', ROW)
    assert 'id="request-block"' in row_of(h)


# ---- U7: ONE action row, at most four md controls ----

@pytest.mark.parametrize("path", ["/media/item/mov1", "/media/item/ser1", "/media/item/ep3", "/media/title/movie/603",
                                  "/media/title/movie/701", "/media/title/tv/100"])
def test_one_action_row_of_at_most_four_md_controls(env, monkeypatch, path):
    set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)       # resume: Mark watched + Reset exist (under More)
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, path)))
    assert h.count(ROW) == 1
    found = controls(row_of(h))
    assert 1 <= len(found) <= 4, found
    assert not [c for c in found if "btn-sm" in c]                     # all md (36 px): no sm beside them
    assert found[0].split()[1] == "btn-white" and sum("btn-white" in c for c in found) == 1
    rest = [c.split()[1] for c in found[1:]]
    assert set(rest) <= {"btn-glass", "btn-icon"}, rest                 # Trailer, then square icon buttons


def test_more_holds_the_resume_pair_and_search_now_with_their_forms_intact(env, monkeypatch):
    monkeypatch.setenv("RADARR_URL", "http://radarr.secret-host.invalid:7878")
    monkeypatch.setenv("RADARR_API_KEY", "r-SECRET")
    set_ud(monkeypatch, PlaybackPositionTicks=80 * 600_000_000)
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/item/mov1")))
    row, more = row_of(h), more_of(h)
    assert "<summary>More</summary>" in more and '<div class="confirm heromore-acts">' in more
    for act in ("watched", "reset"):
        assert f'action="/media/resume/mov1/{act}"' in more and f"/media/resume/mov1/{act}" not in row
        form = more.split(f'action="/media/resume/mov1/{act}"', 1)[0].rsplit("<form", 1)[1]
        assert 'method="post" hx-swap="innerHTML show:none"' in form      # E2's scroll-keeping swap stays
    assert '<span id="arr-search" hidden hx-get="/media/title/movie/603/arr?' in more and "arr-search" not in row
    assert "Search now" not in row and "Mark watched" not in row and "Reset progress" not in row


def test_more_holds_mark_unwatched_on_a_watched_film_and_episode(env, monkeypatch):
    set_ud(monkeypatch, Played=True)
    client, _ = env()
    with client:
        film = hero(main_of(whole(client, "/media/item/mov1")))
        ep = hero(main_of(whole(client, "/media/item/ep3")))
    for h, jf in ((film, "mov1"), (ep, "ep3")):
        assert re.search(rf'action="/media/resume/{jf}/(un)?watched"', more_of(h)), jf
        assert "/media/resume/" not in row_of(h)


def test_request_beside_play_waits_under_more(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "mediaInfo": {"status": 4}}   # partly available: Request + Play
    with client:
        first = hero(main_of(whole(client, "/media/item/ser1")))          # the deferred part lands in fp-actions-more
        again = hero(main_of(client.get("/media/item/ser1").text))         # cached: drawn inline
    for h in (first, again):
        assert 'id="request-block"' in more_of(h) and 'id="request-block"' not in row_of(h)
        assert 'class="btn btn-secondary" href="/media/title/tv/100?step=confirm"' in more_of(h)
        assert controls(row_of(h))[0].startswith("btn btn-white") and "Next to watch" in row_of(h)


def test_the_part_response_fills_the_more_slot_only_beside_play(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "mediaInfo": {"status": 4}}
    with client:
        client.get("/media/item/ser1")                                   # a part reads the item the page has cached
        show = client.get("/media/item/ser1/part/all?p=actions").text
        title = client.get("/media/title/movie/701/part/all?p=actions").text
    assert 'id="fp-actions-more" hx-swap-oob="true"' in show and 'id="fp-actions-more"' not in title
    assert 'id="request-block"' in show.split('id="fp-actions-more"', 1)[1]
    assert 'id="request-block"' in title and 'class="btn btn-white"' in title   # off the server: the row's primary


def test_no_more_fold_when_there_is_nothing_to_fold(env):
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/title/movie/701")))        # not on the server, no Radarr
    assert MORE not in h


# ---- U5: the site pills live in the Scores strip ----

def test_site_pills_sit_in_the_scores_strip_not_the_hero(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/movie/603"))
    assert "sitepill" not in hero(b)
    strip = b.split('<div class="stats numbers">', 1)[1].split('<div class="filmbody">', 1)[0]
    scores = strip.split('<div class="scorepills sitepills">', 1)
    assert len(scores) == 2 and "sp-tmdb" in scores[0]                     # after the score pills, in the same stat
    assert re.findall(r'class="scorepill sitepill"[^>]*>.*?</a>', scores[1]) and ">Letterboxd</a>" in scores[1]


def test_site_pills_fall_back_to_a_details_row_without_a_scores_strip():
    from hub.shell import templates
    film = {"title": "Bare", "year": 2001, "kind": "movie", "tmdb": 9, "pending": set(), "numbers": {}, "facts": {},
            "logos": {"imdb": "/i.svg", "tmdb": "/t.svg", "lbxd": "/l.svg"}, "rating": None, "watch_count": 0}
    src = templates.env.get_template("media_film.html")
    block = src.blocks["content"]
    ctx = src.new_context({"film": film, "request": SimpleNamespace(url=SimpleNamespace(path="/media/title/movie/9")),
                           "img_letters": lambda s: s, "status_of": lambda w: {"cls": ""}})
    html = "".join(block(ctx))
    assert '<div class="stats numbers">' not in html
    assert '<div class="kv"><dt>Links</dt><dd class="sitepills">' in html and ">TMDB</a>" in html


# ---- U5: no sub-tab row on item / title pages ----

@pytest.mark.parametrize("path, section", [("/media/item/mov1", "Movies"), ("/media/item/ser1", "TV shows"),
                                           ("/media/item/ep3", "TV shows"), ("/media/title/movie/603", "Movies"),
                                           ("/media/title/movie/701", "Discover")])
def test_item_and_title_pages_have_no_sub_tab_row(env, path, section):
    client, _ = env()
    with client:
        html = client.get(path).text
    assert 'class="sectabs sub"' not in html
    assert f'aria-current="page">{section}' in html.split('<nav class="sectabs sectabs-page" aria-label="Media sections">', 1)[1]


def test_nav_context_drops_the_tabs_for_a_forced_section_only_when_no_tab_matches():
    def req(path, forced=None):
        return SimpleNamespace(url=SimpleNamespace(path=path), state=SimpleNamespace(media_section=forced))
    item = media_nav.nav_context(req("/media/item/x", "movies"), None, {})
    assert item["section"]["id"] == "movies" and item["tabs"] == [] and item["title"] == "Movies"
    listing = media_nav.nav_context(req("/media/movies"), None, {})
    assert [t["label"] for t in listing["tabs"] if t["on"]] == ["My films"]


# ---- CSS: one dated tail block ----

def test_e4_css_is_one_tail_block_with_the_phone_poster_cap():
    head, tail = CSS.split("/* ---- E4 film page (2026-10-13) ---- */", 1)
    assert "@media (max-width: 639px) { .hero-detail-poster { width: 50%; max-width: 200px; } }" in tail
    assert ".hero-detail-poster { width: 62%; max-width: 260px;" in head                  # the base rule is unchanged
    assert "@media (min-width: 640px) {\n  .hero-detail-in { flex-direction: row;" in head  # desktop: poster beside
    assert ".heromore:not(:has(.heromore-acts :is(form, a, button, p))) { display: none; }" in tail
    assert "heromore" not in head
