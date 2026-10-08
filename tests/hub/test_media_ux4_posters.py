"""media-ux4 item 1 (2026-10-08): the TV Shows list, the To rate rows and every Diary list use the SAME poster size
as the Movies list (media-ux2: `.listbox.libposters`, 55 px phone / 66 px from 640 px, fetched at h=240)."""
import re
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_db
from tests.hub.test_media_frame import env as frame_env  # noqa: F401  (fixture)
from tests.hub.test_media_library_pages import MOVIES, SHOWS, jelly, body
from tests.hub.test_media_rate import HX, env, main_of  # noqa: F401  (env fixture)

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def boxes(html):
    """{class attribute: [listbox inner html]} for every .listbox on the page."""
    out = {}
    for cls, inner in re.findall(r'<div (?:id="[^"]+" )?class="(listbox[^"]*)">(.*?)</div>\s*(?:</section>|$)', html, re.S):
        out.setdefault(cls, []).append(inner)
    return out


def posters(html):
    return re.findall(r'<img class="poster row-poster[^"]*" src="/img/[^"?]+\?h=(\d+)&amp;', html)


def test_tv_list_uses_the_movies_list_poster(frame_env):
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, mv = body(c, "/media/movies")
        _, tv = body(c, "/media/tv")
    for page, items in ((mv, MOVIES), (tv, SHOWS)):
        rows = "".join(boxes(page).get("listbox libposters", []))
        assert posters(rows) == ["240"] * len(items)


def test_to_rate_rows_use_the_movies_list_poster(env):
    build, _ = env
    with build() as client:
        hist = main_of(client.get("/media/history").text)
    inbox = hist.split(">To rate</div>", 1)[1].split("</section>", 1)[0]
    assert '<div class="listbox libposters">' in inbox
    assert posters(inbox) and set(posters(inbox)) == {"240"}


def test_every_diary_list_uses_the_movies_list_poster(env):
    build, _ = env
    media_db.add_manual_watch("tmdb:1", "movie", "Heat", watched_on="2025-03-01")
    with build() as client:
        diary = main_of(client.get("/media/diary").text)
        logged = client.post("/media/log", headers=HX, data={
            "pick": '{"item_key": "tmdb:603", "kind": "movie", "title": "The Matrix", "year": 1999}',
            "watched_on": date.today().isoformat(), "place": "", "note": ""}).text
    otd = diary.split(">On this day</div>", 1)[1].split("</section>", 1)[0]
    assert '<div class="listbox libposters">' in otd and set(posters(otd)) == {"240"}
    assert '<div id="diary-new" class="listbox libposters"></div>' in diary       # htmx-logged rows land here
    months = diary.split('<div id="diary-new"', 1)[1]
    assert months.count('<div class="listbox libposters">') >= 1 and '<div class="listbox">' not in months
    assert posters(months) and set(posters(months)) == {"240"}
    assert set(posters(logged)) == {"240"}                                          # the logged row partial too


def test_recently_watched_on_history_keeps_the_small_poster(env):
    build, _ = env
    with build() as client:
        hist = main_of(client.get("/media/history").text)
    recent = hist.split(">Recently watched</div>", 1)[1].split("</section>", 1)[0]
    assert "libposters" not in recent and set(posters(recent)) == {"120"}


def test_a_picker_under_a_big_poster_row_lines_up_with_the_title():
    assert ".listbox.libposters .row .ratepick, .listbox.libposters .row .rated { padding-left: 69px; }" in CSS
    assert re.search(r"@media \(min-width: 640px\) \{ \.listbox\.libposters \.row \.ratepick, "
                     r"\.listbox\.libposters \.row \.rated \{ padding-left: 84px; \} \}", CSS)
