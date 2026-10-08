"""media-ux4 item 4 (2026-10-08): director / creators more prominent. The hero's inline "Director Guy Ritchie" text is a
"Directed by" block of headshot cards (TMDB profile through the /img proxy, initials when none) with the name larger,
each card ONE link to /media/person/{id} (a Discover search when TMDB gives no id); TV shows say "Created by" with up to
four cards; on a phone the cards are a sideways row."""
import re
from pathlib import Path

from hub import media_film
from tests.hub.test_media_film import FILM, SHOW, env, main_of  # noqa: F401  (env is a fixture)

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def hero(b):
    return b.split("</header>", 1)[0]


def cards(h):
    block = h.split('<div class="makers">', 1)[1].split('<div class="credits sitepills">', 1)[0]
    label = re.search(r'<div class="microlabel">([^<]+)</div>', block).group(1)
    found = re.findall(r'<a class="makercard" href="([^"]+)">(<img class="makerpic" src="([^"]+)"[^>]*>|<span class="makerpic '
                       r'initials" aria-hidden="true">([^<]*)</span>)<span class="makername">([^<]+)</span></a>', block)
    return label, [(href, src or None, initials or None, name) for href, _, src, initials, name in found]


def test_film_hero_has_a_directed_by_card_with_headshot_and_person_link(env):
    client, both = env()
    both.seerr.table["/api/v1/movie/603"] = {**FILM, "credits": {**FILM["credits"], "crew": [
        {"id": 77, "name": "Guy Ritchie", "job": "Director", "profilePath": "/guy.jpg"}]}}
    with client:
        h = hero(main_of(client.get("/media/title/movie/603").text))
    label, found = cards(h)
    assert label == "Directed by"
    assert found == [("/media/person/77", f"/img/tmdb:/guy.jpg?h={media_film.MAKER_H}", None, "Guy Ritchie")]
    assert 'width="52" height="52"' in h and "Director</span>" not in h and "<span>Director</span>" not in h


def test_no_tmdb_id_or_photo_falls_back_to_search_and_initials(env):
    client, _ = env()                                   # FILM's director has neither id nor profilePath
    with client:
        _, found = cards(hero(main_of(client.get("/media/title/movie/603").text)))
    assert found == [("/media/discover?q=Dee%20Director", None, "DD", "Dee Director")]


def test_series_says_created_by_with_up_to_four_cards(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "createdBy": [
        {"id": 10 + i, "name": f"Maker {chr(65 + i)} Person", "profilePath": f"/m{i}.jpg" if i % 2 == 0 else None}
        for i in range(5)]}
    with client:
        label, found = cards(hero(main_of(client.get("/media/title/tv/100").text)))
    assert label == "Created by" and len(found) == 4
    assert found[0] == ("/media/person/10", f"/img/tmdb:/m0.jpg?h={media_film.MAKER_H}", None, "Maker A Person")
    assert found[1] == ("/media/person/11", None, "MB", "Maker B Person")       # initials of the first two words


def test_jellyfin_director_without_jellyseerr_still_gets_a_card(env, monkeypatch):
    import tests.hub.test_media_item as tmi
    monkeypatch.setitem(tmi.ITEMS["mov1"], "People", [
        {"Name": "Ada Actor", "Type": "Actor", "Role": "Pilot"},
        {"Name": "Dee Director", "Type": "Director", "Id": "p77", "PrimaryImageTag": "t"}])
    client, both = env()
    both.fail_seerr = True
    with client:
        label, found = cards(hero(main_of(client.get("/media/item/mov1").text)))
    assert label == "Directed by"
    assert found == [("/media/discover?q=Dee%20Director", f"/img/jf:p77?h={media_film.MAKER_H}", None, "Dee Director")]


def test_cards_sit_before_the_site_pills_and_status(env):
    client, _ = env()
    with client:
        h = hero(main_of(client.get("/media/title/movie/603").text))
    assert h.index('<div class="makers">') < h.index('<div class="credits sitepills">') < h.index('id="status-line"')
    assert h.index('class="facts-line"') < h.index('<div class="makers">')


def test_maker_headshot_size_is_a_proxy_size():
    from hub import images
    assert media_film.MAKER_H in images.SIZES and media_film.MAKERS_MAX == 4


def test_phone_row_scrolls_sideways_and_wraps_from_640():
    row = CSS.split(".makerrow {", 1)[1].split("}", 1)[0]
    assert "display: flex" in row and "overflow-x: auto" in row and "flex-wrap" not in row
    wide = CSS.split("@media (min-width: 640px) {\n  .hero-detail-in", 1)[1].split("\n}", 1)[0]
    assert ".makerrow { flex-wrap: wrap; overflow: visible; }" in wide
    assert ".makername { font-size: 16px; font-weight: 600;" in CSS and ".makerpic { width: 52px; height: 52px;" in CSS
