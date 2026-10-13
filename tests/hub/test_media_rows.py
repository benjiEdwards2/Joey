"""Whole-row links across the Media pages (B., 2026-10-06): "In Server I cannot select the full
thing. Plus the text does not match up." A row whose title resolves is ONE <a class="row ...">
with the title as plain .row-title text; a row with nothing to resolve stays a <div class="row">.
Rows holding a 1-10 picker (a form) use an a.rowlink overlay instead. Asserted inside <main>.
Restyle Phase 3 (2026-10-06): the MediaHub row recipe (.row / .row-title) replaced .uprow / .uptitle."""
import re
from datetime import timedelta
from pathlib import Path

from hub import media_plays_db
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_downloads import ARR, QB, env  # noqa: F401  (env is a fixture)
from tests.hub.helpers import LINKED, NOW

TEMPLATES = Path(__file__).resolve().parents[2] / "hub" / "templates"


def between(body, start, end=None):
    part = body.split(start, 1)[1]
    return part.split(end, 1)[0] if end else part


def row_of(html, title):
    """The row element (a or div) that holds `title`."""
    m = re.search(r'<(a|div) class="row(?: [^"]*)?"[^>]*>(?:(?!</?(?:a|div) class="row[ "]).)*?'
                  + re.escape(title), html, re.S)
    assert m, title
    return m.group(0)


def test_live_up_next_and_latest_rows_are_whole_row_links(env):
    jelly = {**LINKED,
             "up_next": LINKED["up_next"] + [{"title": "Keyless Ep", "remaining_text": "5 min left", "poster": None}],
             "latest": LINKED["latest"] + [{"title": "Keyless Film", "type": "Movie", "poster": None,
                                            "added_at": NOW.isoformat()}]}
    with env(jellyfin=jelly) as client:
        body = main_of(client.get("/media/playing").text)
    up = between(body, ">Up next<", ">Latest additions<")
    row = row_of(up, "Dust and Daylight")
    assert row.startswith('<a class="row" href="/media/item/resume-id">')
    assert '<div class="row-title">Dust and Daylight</div>' in up and "31 min left" in up
    assert row_of(up, "Keyless Ep").startswith('<div class="row">')
    latest = between(body, ">Latest additions<")
    assert row_of(latest, "Fresh Film").startswith('<a class="row" href="/media/item/new-id">')
    assert '<div class="row-title">Fresh Film</div>' in latest
    assert row_of(latest, "Keyless Film").startswith('<div class="row">')


def test_server_history_rows_are_whole_row_links(env):
    client = env()
    for jf, kind, title, show, key in (("e1", "episode", "Pilot", "Quiet", "jf:ser1"),
                                       (None, "movie", "Title Page Film", None, "tmdb:77"),
                                       (None, "movie", "Keyless Film", None, None)):
        for pos in (1, 100):
            media_plays_db.record_sighting({
                "user_name": "u", "owner": "you", "jf_id": jf, "item_key": key,
                "show_key": "jf:ser1" if show else None, "title": title, "show_title": show, "kind": kind,
                "runtime_min": 30, "position_pct": pos, "poster": None},
                NOW - timedelta(minutes=30 if pos == 1 else 0))
    with client:
        body = main_of(client.get("/media/server/history?w=all").text)
    shows = between(body, ">Top shows<", ">Top films<")
    assert row_of(shows, "Quiet").startswith('<a class="row" href="/media/item/ser1">')
    assert '<div class="row-title">Quiet</div>' in shows
    films = between(body, ">Top films<", ">By hour of day<")
    assert row_of(films, "Title Page Film").startswith(
        '<a class="row" href="/media/title/movie/77">')
    assert row_of(films, "Keyless Film").startswith('<div class="row">')


def test_downloads_rows_link_through_their_arr_row(env):
    with env(qbittorrent=QB, arr=ARR) as client:
        body = main_of(client.get("/media/downloads").text)
    row = row_of(body, "Midnight Harbour 2021 1080p")
    assert row.startswith('<a class="row" href="/media/title/movie/603">')  # arr tmdb key, not on server
    assert '<div class="row-title">Midnight Harbour 2021 1080p</div>' in body and "4.2 GB" in row_of(body, "4.2 GB")
    assert row_of(body, "Some Show S01").startswith('<div class="row">')  # no arr row claims it
    assert row_of(body, "Linux ISO").startswith('<div class="row">')


def test_library_downloading_rows_link_like_the_other_library_rows(env):
    with env(arr=ARR, qbittorrent=QB, jellyfin={"summary": "x"}) as client:
        body = main_of(client.get("/media/library").text)
    dl = between(body, ">Downloading<", ">Disk<")
    assert row_of(dl, "Midnight Harbour").startswith(
        '<a class="row" href="/media/title/movie/603">')
    assert row_of(dl, "Linux ISO").startswith('<div class="row">')  # qBittorrent-only: no key
    assert '<a class="uprow' not in between(body, ">Disk<")  # disk rows are not titles


def test_watched_rows_are_whole_row_links_and_rateable_rows_use_the_overlay(env):
    with env(jellyfin=LINKED) as client:
        body = main_of(client.get("/media/history").text)
    recent = between(body, ">Recently watched<")
    assert row_of(recent, "Quiet Show").startswith('<a class="row" href="/media/item/e2">')
    to_rate = between(body, ">To rate<", ">Recently watched<")   # E3; sentence case since nav-tidy (2026-10-13)
    assert "row has-form" in to_rate  # the inbox row carries the picker form
    assert '<a class="rowlink" href="/media/item/e2">' in to_rate and "<form" in to_rate
    assert not re.search(r'<a class="rowlink"[^>]*>(?:(?!</a>).)*<form', to_rate, re.S)  # form never inside


def test_apps_rows_carry_the_row_link_look():
    src = (TEMPLATES / "media_apps.html").read_text(encoding="utf-8")
    assert """<a class="row{{ ' is-down' if not a.up }}" href="{{ a.href }}" target="_blank" rel="noopener">""" in src


def test_no_inline_anchor_inside_a_row_title():
    """The title is plain text in every Media row: no <a> nested inside the .row-title."""
    files = sorted(TEMPLATES.glob("media_*.html")) + [TEMPLATES / "_library_row.html", TEMPLATES / "_diary_row.html"]
    assert TEMPLATES / "media_watchlist.html" in files
    offenders = []
    for f in files:
        for m in re.finditer(r'<(?:span|div|p) class="row-title"[^>]*>(.*?)</(?:span|div|p)>', f.read_text(encoding="utf-8"), re.S):
            if "<a " in m.group(1):
                offenders.append(f"{f.name}: {m.group(0)[:80]}")
    assert files and not offenders, offenders


def test_diary_on_this_day_rows_are_whole_row_links(env):
    otd = [{"title": "Old Film", "kind": "movie", "years_ago": 2, "poster": None, "item_key": "tmdb:12", "jf_id": "of1"},
           {"title": "Old Show · S01E01 · Pilot", "kind": "episode", "years_ago": 1, "poster": None,
            "item_key": "jf:ser7", "jf_id": "ep1"},
           {"title": "Keyless Thing", "kind": "movie", "years_ago": 3, "poster": None, "item_key": None}]
    with env(jellyfin={**LINKED, "history": {**LINKED["history"], "on_this_day": otd}}) as client:
        body = main_of(client.get("/media/diary").text)
    day = between(body, ">On this day<", 'id="diary-new"')
    assert row_of(day, "Old Film").startswith('<a class="row" href="/media/title/movie/12">')
    assert row_of(day, "Old Show").startswith('<a class="row" href="/media/item/ser7">')
    assert row_of(day, "Keyless Thing").startswith('<div class="row">')
    assert '<div class="row-title">Old Film</div>' in day


def test_tonight_cards_are_whole_card_links():
    """Tonight (Movies/TV): the card itself is the <a>; no separate poster + title anchors."""
    src = (TEMPLATES / "media_tonight.html").read_text(encoding="utf-8")
    assert '<{{ "a" if r.href else "div" }} class="card-poster tcard"' in src and src.count("<a ") == 1  # 'Deal again' only
