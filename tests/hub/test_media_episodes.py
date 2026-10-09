"""Episode list on TV pages (2026-10-08): the tiny numbered squares became a readable list — per season a
collapsible <details> (the page's / next episode's season open) with "Season 4 · 3 of 6 watched"; per episode one
whole-row link with a 16:9 still, "E3 · Name", air date · runtime, a state word + colour and the Play / Resume deep
link beside it. And the Seasons section sits directly under Overview on TV pages. Jellyfin + Jellyseerr faked."""
import re
from pathlib import Path

from hub import media_film
from tests.hub import helpers as tmi
from tests.hub.helpers import deep, env, ep, SHOW, TICKS  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.conftest import main_of  # noqa: F401

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def timed(monkeypatch):
    """The fixture episodes with runtimes (45 min) — ep4 is 5 min in, so 40 min left."""
    eps = [{**e, "RunTimeTicks": 45 * TICKS} for e in tmi.EPISODES]
    monkeypatch.setattr(tmi, "EPISODES", eps)
    return eps


def section(body, label):
    return body.split(f'<div class="seclabel">{label}</div>', 1)[1].split('<section class="sec', 1)[0]


def ep_row(body, n):
    return body.split(f'id="ep-ep{n}">', 1)[1].split('<div class="row has-form epline', 1)[0]


def test_each_episode_is_a_big_whole_row_link_with_still_state_and_play(env, monkeypatch):
    timed(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    seasons = section(b, "Seasons")
    assert "Season 4 · 3 of 6 watched" in re.sub(r"<[^>]+>", "", seasons)
    four = ep_row(seasons, 4)
    link = four.split('<a class="rowlink" href="/media/item/ep4">', 1)[1].split("</a>", 1)[0]
    assert '<img class="epstill" src="/img/jf:ep4?h=240&amp;t=FO"' in link
    assert ">E4 · Four</div>" in link and "45m" in link
    assert '<div class="epstate st-progress">In progress · 40m left</div>' in link
    assert "<a " not in link and "Resume" not in link                     # the deep link is beside the row
    after = four.split("</a>", 1)[1]
    assert f'href="{deep("ep4")}" target="_blank" rel="noopener">Resume ▶ · 40m left</a>' in after
    assert '<div class="epstate st-good">Watched</div>' in ep_row(seasons, 1) and "Play again ▶" in ep_row(seasons, 1)
    assert '<div class="epstate st-todo">Not watched</div>' in ep_row(seasons, 5) and ">Play ▶</a>" in ep_row(seasons, 5)
    six = ep_row(seasons, 6)
    assert '<div class="epstate st-off">Not aired</div>' in six and "▶" not in six   # nothing to play yet
    assert re.search(r"E1 · One</div>\s*<div class=\"row-meta\">\d{1,2} \w{3} \d{4} · 45m</div>", seasons)


def test_squares_and_their_legend_are_gone(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert "Squares in order" not in b and 'class="epmap"' not in b and '<a class="ep' not in b
    assert ".epmap" not in CSS


def test_the_next_episodes_season_is_open_by_default(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert '<details class="seasonbox epseason" id="season-4" open>' in b   # media-ux3: each season has an anchor


def test_no_anchor_inside_a_row_title(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    for title in re.findall(r'<div class="row-title">(.*?)</div>', section(b, "Seasons"), re.S):
        assert "<a" not in title


def test_episode_list_open_rules():
    eps = [{"jf_id": "a", "played": True, "in_progress": False, "aired": True}]
    seasons = [{"number": 1, "name": "Season 1", "episodes": eps, "watched_text": "1 of 1 watched"},
               {"number": 2, "name": "Season 2", "episodes": eps, "watched_text": "1 of 1 watched"},
               {"number": 3, "name": "Season 3", "episodes": eps, "watched_text": "1 of 1 watched"}]
    opened = lambda out: [s["n"] for s in out if s["open"]]
    assert opened(media_film.episode_list(seasons, None, None, {"season": 2})) == [2]      # next episode's season
    assert opened(media_film.episode_list(seasons, None, 1, {"season": 2})) == [1]         # the page's episode wins
    assert opened(media_film.episode_list(seasons, None, None, None)) == [3]               # all watched: the latest
    assert media_film.episode_list([], None) == []
    out = media_film.episode_list(seasons, lambda i: f"deep:{i}")
    assert out[0]["episodes"][0]["play"] == {"href": "deep:a", "label": "Play again ▶"}
    assert "open" not in seasons[0] and "play" not in eps[0]                               # the cache is never touched


def test_episode_state_words():
    s = media_film.episode_state
    assert s({"played": True})["word"] == "Watched"
    assert s({"in_progress": True, "left_min": 23})["word"] == "In progress · 23m left"
    assert s({"in_progress": True})["word"] == "In progress"
    assert s({"aired": False})["word"] == "Not aired"
    assert s({"aired": True})["word"] == "Not watched"


def test_rows_are_tall_and_phone_friendly():
    assert re.search(r"\.epline \{ min-height: 64px; \}", CSS)
    assert "aspect-ratio: 16 / 9" in CSS.split(".epline .epstill", 1)[1].split("}", 1)[0]
    phone = CSS.split("@media (max-width: 480px) {\n  .epline .epstill", 1)
    assert len(phone) == 2 and "width: 96px" in phone[1].split("}", 1)[0]


# ---- Item E: Seasons directly under Overview on TV pages ----

def test_tv_page_order_overview_seasons_then_where_to_watch(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "overview": "A quiet show.",
                                         "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Stan"}]}],
                                         "credits": {"cast": [{"name": "Ada Actor", "character": "Lead"}]}}
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    idx = {k: b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "Seasons", "Cast", "Where to watch")}
    assert idx["Overview"] < idx["Seasons"] < idx["Cast"] < idx["Where to watch"]
    between = b[idx["Overview"]:idx["Seasons"]]
    assert '<div class="seclabel">' not in between.split("</div>", 1)[1]               # nothing in between


def test_off_server_tv_title_keeps_seasons_under_overview(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/555"] = {**SHOW, "id": 555, "name": "Far Show", "overview": "Far away.",
                                         "mediaInfo": {"status": 1},
                                         "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Stan"}]}]}
    with client:
        b = main_of(client.get("/media/title/tv/555").text)
    o, s, w = (b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "Seasons", "Where to watch"))
    assert o < s < w


def test_film_page_order_is_unchanged(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert '<div class="seclabel">Seasons</div>' not in b
    o, f, w = (b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "File", "Where to watch"))
    assert o < f < w
