"""JY-277 option A (2026-11-03, with JY-278 and JY-305): the web Home keeps every shelf, all on the poster-tile shelf,
one tile per show (a Sonarr season row never repeats the Jellyfin show tile) on the show's Jellyfin poster, and a hero
of about two thirds of the screen on desktop / iPad. Phone and TV keep their heights."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_home
from tests.hub.helpers import ARR, JELLY
from tests.hub.test_media_shelves import env, main_html, shelves_for  # noqa: F401

CSS = Path("hub/static/control-surface.css").read_text(encoding="utf-8")
SHOW = "jf:" + "b1" * 16


def billions(**extra):
    jelly = {**JELLY, "latest": [{"title": "Billions", "type": "Series", "poster": SHOW, "item_key": "tmdb:62852",
                                  "jf_id": "b1" * 16, "added_at": "2026-11-01T10:00:00.0000000Z"}],
             "shows": [{"title": "Billions", "poster": SHOW, "jf_id": "b1" * 16, "item_key": "tmdb:62852"}], **extra}
    arr = {**ARR, "arrived": [{"title": "Billions · S07 · 3 episodes", "kind": "show", "item_key": "tvdb:259552",
                               "poster": "sonarr:12", "when": "today"},
                              {"title": "Billions · S06 · 12 episodes", "kind": "show", "item_key": "tvdb:259552",
                               "poster": "sonarr:12", "when": "today"},
                              {"title": "Other Show · S01 · 2 episodes", "kind": "show", "item_key": "tvdb:1",
                               "poster": "sonarr:13", "when": "today"}]}
    return jelly, arr


def test_show_name_folds_the_season_suffix():
    assert media_home.show_name("Billions · S07 · 3 episodes") == media_home.show_name("billions") == "billions"
    assert media_home.show_name(None) == ""


def test_one_tile_per_show_in_recently_added(env):
    jelly, arr = billions()
    added = next(s for s in shelves_for(env(jellyfin=jelly, arr=arr))["shelves"] if s["id"] == "added")
    names = [media_home.show_name(i["title"]) for i in added["items"]]
    assert names.count("billions") == 1 and "other show" in names
    tile = next(i for i in added["items"] if media_home.show_name(i["title"]) == "billions")
    assert tile["title"] == "Billions" and tile["poster"] == SHOW   # the Jellyfin row (custom poster) wins


def test_library_posters_swaps_only_non_jellyfin_posters():
    jelly = {"shows": [{"title": "Billions", "poster": SHOW}], "movies": [{"title": "Film", "poster": "jf:f"}]}
    shelves = [{"items": [{"title": "Billions · S07 · 3 episodes", "poster": "sonarr:12", "row_kind": "show"},
                          {"title": "Film", "poster": None, "row_kind": "movie"},
                          {"title": "Film", "poster": "jf:own", "row_kind": "movie"},
                          {"title": "Unknown", "poster": "radarr:9", "row_kind": "movie"},
                          {"title": "Billions", "poster": "radarr:7", "row_kind": "movie"},   # a film named like the show
                          {"title": "Film", "poster": "x:1"}]}]                                 # unknown kind: never matched
    media_home.library_posters(jelly, shelves)
    assert [i["poster"] for i in shelves[0]["items"]] == [SHOW, "jf:f", "jf:own", "radarr:9", "radarr:7", "x:1"]


def test_a_film_and_a_show_with_the_same_title_stay_two_tiles(env):
    jelly, arr = billions()
    arr["arrived"].append({"title": "Billions", "kind": "movie", "item_key": "tmdb:999", "poster": "radarr:5",
                           "when": "today"})
    added = next(s for s in shelves_for(env(jellyfin=jelly, arr=arr))["shelves"] if s["id"] == "added")
    tiles = [i for i in added["items"] if media_home.show_name(i["title"]) == "billions"]
    assert len(tiles) == 2 and {t["poster"] for t in tiles} == {SHOW, "radarr:5"}


def test_home_markup_hero_class_and_poster_tile_shelves(env):
    jelly, arr = billions()
    with TestClient(env(jellyfin=jelly, arr=arr).app) as client:
        body = main_html(client.get("/a/alpha").text)
    secs = re.findall(r'<section class="([^"]*)"[^>]*>\s*<div class="sechead">', body)
    assert secs and all("home-shelf" in c.split() for c in secs)
    assert body.count(f"/img/{SHOW}") >= 1 and "sonarr%3A12" not in body and "sonarr:12" not in body


def test_home_hero_class_only_on_home(env):
    jelly, arr = billions()
    with TestClient(env(jellyfin=jelly, arr=arr).app) as client:
        home = client.get("/a/alpha").text
        other = client.get("/a/beta").text
    assert '<header class="pagehead home-hero">' in home
    assert "home-hero" not in other


def test_hero_height_rules_desktop_ipad_and_not_phone_or_tv():
    rules = re.findall(r"([^{};]*\.home-hero)\s*\{\s*min-height:\s*([^;]+);", CSS)
    assert all(sel.strip().startswith("html:not(.tv)") for sel, _ in rules)   # TV untouched
    assert sorted(h for _, h in rules) == ["min(58vh, 600px)", "min(67vh, 960px)"]
    block = CSS.split("/* JY-277 option A", 1)[1]
    assert "@media (min-width: 640px)" in block and "@media (min-width: 1025px)" in block   # phone (<640) unchanged
