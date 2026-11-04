"""JY-279 (2026-11-03, option B): the Movies / TV Shows List view as columns - Title, Year, Your score, Average,
Upgrade?, Director (Creator for a show), Added - under a header of sort links. One test (or more) per acceptance
check 1-9 in docs/specs/JY-279-row-view-columns.md, plus the TV (check 10)."""
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_directors, media_library
from tests.hub.guest_pages import TV_UA
from tests.hub.test_media_frame import env as frame_env  # noqa: F401  (fixture)
from tests.hub.test_media_library_pages import MOVIES, body, jelly
from tests.hub.test_media_upgrades_pages import FILM_NOTE, site  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def heads(html):
    head = html.split('<div class="colhead" role="row">', 1)[1].split("</div>", 1)[0]
    return re.findall(r'<span class="col col-(\w+)[^"]*" role="columnheader"( aria-sort="(\w+)")?><a href="([^"]+)"[^>]*>(?:<span class="lab-long">)?([^<]+)', head)


def titles(html):
    box = html.split('<div class="listbox libposters">', 1)[1]
    return re.findall(r'<span class="row-title">([^<]+)</span>', box)


def no_fill(monkeypatch):
    monkeypatch.setattr(media_directors, "later", lambda rows, kind, have, fetch=None: None)


# 1 + 2: a header row and the default column set in the List view; Grid is unchanged
def test_1_2_list_view_has_a_header_and_the_default_columns_grid_has_none(frame_env, monkeypatch):
    no_fill(monkeypatch)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, lst = body(c, "/media/movies?view=list")
        _, grid = body(c, "/media/movies?view=grid")
        _, tvl = body(c, "/media/tv?view=list")
    assert 'role="table"' in lst
    assert [(k, label.strip()) for k, _, _, _, label in heads(lst)] == [
        ("title", "Title"), ("year", "Year"), ("score", "Your score"), ("rating", "Average"), ("upgrade", "Upgrade?"),
        ("director", "Director"), ("added", "Added")]
    assert [label.strip() for *_, label in heads(tvl)][5] == "Creator"     # a show's "director" is its creator
    assert "colhead" not in grid and 'class="poster-grid libgrid"' in grid
    assert lst.count('class="col col-year"') == len(MOVIES) + 1                   # the rows + the header


# 3: a header click sorts, a second click reverses; marked by arrow + words + aria-sort; the select stays in step
def test_3_header_sort_toggles_and_is_marked(frame_env, monkeypatch):
    no_fill(monkeypatch)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, first = body(c, "/media/movies?view=list&sort=year")
        h = {k: (aria, href) for k, _, aria, href, _ in heads(first)}
        assert h["year"][0] == "descending" and h["title"][0] == ""
        assert titles(first) == ["Delta Film", "Bravo Film", "Alpha Film", "Charlie Film"]
        assert '<span class="vh">sorted, high to low</span>' in first and "↓" in first
        _, again = body(c, h["year"][1].replace("&amp;", "&"))
    assert "dir=asc" in h["year"][1]
    assert titles(again) == ["Charlie Film", "Alpha Film", "Bravo Film", "Delta Film"]
    assert dict((k, a) for k, _, a, _, _ in heads(again))["year"] == "ascending"
    assert '<option value="year" selected>' in again                    # the toolbar select agrees


# 4: the sort is a link that keeps the search and the filter chip
def test_4_header_links_keep_search_and_filter(frame_env, monkeypatch):
    no_fill(monkeypatch)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, page = body(c, "/media/movies?view=list&q=film&f=unwatched")
    hs = heads(page)
    assert len(hs) == 7
    for _k, _, _, href, _ in hs:
        assert href.startswith("/media/movies?") and "q=film" in href and "f=unwatched" in href and "sort=" in href


# 5: Upgrade? says Yes plus the note, else a dash; sorting puts Yes first
def test_5_upgrade_cell_and_sort(site, monkeypatch):
    no_fill(monkeypatch)
    from tests.hub.upgrade_kept import keep
    keep("radarr", 7)   # JY-275 (2026-11-04): only a checked, viable row is flagged
    with site() as c:
        html = c.get("/media/movies?view=list&sort=upgrade").text
    assert titles(html)[0] == "Alpha Film"
    cells = re.findall(r'<div class="col col-upgrade">(.*?)</div>\s*<div class="col col-director', html, re.S)
    assert cells[0].startswith(f'<span class="col-up" title="{FILM_NOTE}">Upgrade</span>')   # JY-275: was "Yes · Below cutoff" and cells[1] == "—"
    assert '<div class="vh"><div class="upnote">' in cells[0]            # the full words stay for screen readers
    rows = [{"title": "B", "upgrade": ""}, {"title": "A", "upgrade": "Below cutoff"}, {"title": "C", "upgrade": "x"}]
    for d in ("asc", "desc"):
        assert [r["title"] for r in media_library.sort_column(rows, "upgrade", d)] == ["A", "C", "B"]


# 6: blanks show a dash and sort last both ways (score, year, director, rating, added)
def test_6_blanks_sort_last_both_ways():
    rows = [{"title": "Has", "year": 2020, "score": 7, "director": "Zed", "community": 6.0, "added_at": "2024-01-01T00:00:00Z"},
            {"title": "Blank", "year": None, "score": None, "director": "", "community": None, "added_at": None},
            {"title": "Also", "year": 2010, "score": 9, "director": "Amy", "community": 8.0, "added_at": "2025-01-01T00:00:00Z"}]
    for col in ("score", "year", "director", "rating", "added"):
        for d in ("asc", "desc"):
            assert media_library.sort_column(rows, col, d)[-1]["title"] == "Blank", (col, d)
    assert [r["title"] for r in media_library.sort_column(rows, "director", "asc")] == ["Also", "Has", "Blank"]
    assert [r["title"] for r in media_library.sort_column(rows, "director", "desc")] == ["Has", "Also", "Blank"]
    assert [r["title"] for r in media_library.sort_column(rows, "score", "asc")] == ["Has", "Also", "Blank"]


def test_6_blank_cells_render_a_dash(frame_env, monkeypatch):
    no_fill(monkeypatch)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, page = body(c, "/media/movies?view=list")
    assert '<div class="col col-director col-opt">—</div>' in page                 # no director cached yet
    assert '<div class="col col-rating col-opt" title="TMDB average">—</div>' in page  # Charlie Film has no rating
    assert "row-score score-none" in page


# 7: phone shows Title, Year, Your score, Upgrade? only - the rest hidden by CSS, still in the page
def test_7_phone_hides_the_optional_columns_by_css(frame_env, monkeypatch):
    no_fill(monkeypatch)
    assert ".libcols .col-opt { display: none; }" in CSS
    assert ".libcols .colhead .col { white-space: nowrap; }" in CSS                # no header wraps on a phone
    assert ".libcols .colhead .lab-long { display: none; }" in CSS                 # "Score" below 640 px
    assert re.search(r"@media \(min-width: 640px\) \{[^@]*\.libcols \.col-opt \{ display: block; \}", CSS)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, page = body(c, "/media/movies?view=list")
    opt = {k for k, *_ in heads(page) if f'col-{k} col-opt" role="columnheader"' in page}
    assert opt == {"rating", "director", "added"}
    assert page.count("col-director col-opt") == len(MOVIES) + 1                  # rendered, not removed


# 8: the director fill never runs on the request path; a cached name shows on the next load
def test_8_director_fill_is_background_and_cached(frame_env, monkeypatch):
    calls = []
    body_of = {"/api/v1/movie/11": {"credits": {"crew": [{"job": "Director", "name": "Ann Lee"},
                                                         {"job": "Writer", "name": "Bo"}]}},
               "/api/v1/movie/12": {"credits": {"crew": []}}}

    def fetch(path):
        calls.append(path)
        return (body_of.get(path), 200 if path in body_of else 404)
    monkeypatch.setattr(media_directors, "_fetch", fetch)
    monkeypatch.setattr(media_directors, "PAUSE", 0)
    real_attach = media_directors.attach
    seen = []
    monkeypatch.setattr(media_directors, "attach", lambda rows, kind: (seen.append(list(calls)), real_attach(rows, kind))[1])
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        t0 = time.perf_counter()
        _, first = body(c, "/media/movies?view=list")
        took = time.perf_counter() - t0
        _, second = body(c, "/media/movies?view=list")
    assert seen[0] == []                                   # nothing read before the first render
    assert took < 3                                        # in budget with an empty cache
    assert "Ann Lee" not in first and "Ann Lee" in second
    assert sorted(calls) == ["/api/v1/movie/11", "/api/v1/movie/12", "/api/v1/movie/14"]   # jf:13 has no TMDB id
    assert media_directors.cached("movie")[12][0] == ""    # none known: stored blank, not asked again


def test_8_names_fill_and_stop_on_429(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    assert media_directors.names({"createdBy": [{"name": "Vince"}, {"name": "Vince"}]}, "tv") == "Vince"
    assert media_directors.names({"credits": {"crew": [{"job": "Director", "name": "A"}, {"job": "Director", "name": "B"},
                                                       {"job": "Director", "name": "C"}]}}, "movie") == "A, B"
    assert media_directors.cached("movie") == {}           # no table yet: blank, no error
    answers = iter([({"createdBy": [{"name": "Vince"}]}, 200), (None, 429), ({"createdBy": []}, 200)])
    got = []
    n = media_directors.fill([1, 2, 3], "tv", fetch=lambda p: (got.append(p), next(answers))[1], pause=0)
    assert n == 1 and got == ["/api/v1/tv/1", "/api/v1/tv/2"]
    assert media_directors.cached("tv")[1][0] == "Vince"
    rows = [{"item_key": "tmdb:1"}, {"item_key": "tmdb:2"}, {"item_key": "jf:x"}]
    have = media_directors.attach(rows, "tv")
    assert [r["director"] for r in rows] == ["Vince", "", ""]
    assert media_directors.todo(rows, "tv", have) == [2]


# 9: tokens only - the new CSS adds no :root values and no hand-rolled colours
def test_9_css_uses_tokens_only():
    block = CSS.split("/* JY-279", 1)[1].split("  .libcols .col-opt { display: block; }", 1)[0]
    assert ".libcols .row" in block
    assert ":root" not in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)


# 10 (Q5 A): the TV list view is unchanged - no columns, no new sort chips (the TV front: guest client + TV UA)
def test_10_tv_list_view_is_unchanged(monkeypatch, tmp_path):
    from tests.hub.guest_pages import guest_client, sign_in
    from tests.hub.test_tv_library_filters import FRIEND_ID, MOVIES as TV_MOVIES, SHOWS as TV_SHOWS
    no_fill(monkeypatch)
    jelly_tv = {"server_id": "srv-1", "summary": "x", "library": {"movies": 2, "episodes": 8},
                "movies": TV_MOVIES, "shows": TV_SHOWS}
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly_tv})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        html = c.get("/media/movies?view=list", headers={"User-Agent": TV_UA}).text
    assert "tv-libchips" in html                                            # it is the TV page
    assert "colhead" not in html and "Upgrade available" not in html and "Director A-Z" not in html


def test_grid_drops_the_column_only_sorts(frame_env, monkeypatch):
    no_fill(monkeypatch)
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, grid = body(c, "/media/movies?view=grid&sort=director")
        _, lst = body(c, "/media/movies?view=list&sort=director")
    assert 'value="director"' not in grid and '<option value="score" selected>' in grid
    assert '<option value="director" selected>' in lst


def test_background_jobs_run_each_even_when_one_fails():
    from hub import media_pages
    ran = []
    media_pages._run_each([lambda: 1 / 0, lambda: ran.append(1)])
    assert ran == [1]
