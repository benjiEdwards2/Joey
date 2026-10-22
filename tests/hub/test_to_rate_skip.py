"""E5 (M3, 2026-10-13): To rate Skip / Skip show. media.db v4 adds `rating_skip`; POST /media/rate/skip (this entry),
/skip-show (every season and episode of the show, later ones too) and /unskip; the inbox and its amber counts leave
skipped keys out; a "Skipped" group at the foot of the To rate pages lists them with Unskip. Owner-scoped."""
import sqlite3
from contextlib import closing

from hub import media_db, media_home, media_store
from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.test_media_rate import TV, env, jelly_data, recent_row, tv_row  # noqa: F401
from tests.hub.test_media_to_rate_pages import section, subtabs


def post(client, path, **form):
    return client.post(path, data=form, follow_redirects=False)


# ---- media.db v4 ----

def test_v3_file_is_migrated_to_v4_with_the_skip_table_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    media_db.set_rating("tmdb:1", 8, "movie", "Heat")                   # a current file …
    with closing(sqlite3.connect(path)) as db:
        db.execute("DROP TABLE rating_skip")
        db.execute("PRAGMA user_version = 3")                            # … taken back to v3
        db.commit()
    media_store.forget()
    media_store.reset()
    assert media_db.skips("you") == []                                    # a read brings it up to v4
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 5
        cols = [r[1] for r in db.execute("PRAGMA table_info(rating_skip)")]
        assert cols == ["owner", "key", "kind", "forever", "created_at", "title", "poster"]
        media_db.migrate_skip(db)                                         # idempotent
    assert media_db.get_ratings(["tmdb:1"]) == {"tmdb:1": 8}


def test_skip_is_owner_scoped_and_a_later_skip_show_widens_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    media_db.skip("you", "jf:s1", "episode", "Quiet Show")
    media_db.skip("you", "jf:s1", "tv", "Quiet Show", forever=True)
    assert [(s["key"], s["kind"], s["forever"]) for s in media_db.skips("you")] == [("jf:s1", "tv", 1)]
    assert media_db.skips("her") == []
    media_db.unskip("you", "jf:s1")
    assert media_db.skips("you") == []


def test_inbox_leaves_out_skipped_keys_and_shows_skipped_forever(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    rows = TV + [recent_row("tmdb:2", "Dune", 1)]
    r = media_home.Ratings()
    r.owner, r.level = "you", "episode"
    assert len(media_home._to_rate(rows, r)) == 5
    media_db.skip("you", "tmdb:2", "movie", "Dune")
    media_db.skip("you", "jf:cfae8", "tv", "Colin from Accounts · S01E08 · High Needs People")
    r = media_home.Ratings()
    r.owner, r.level = "you", "episode"
    assert [x["item_key"] for x in media_home._to_rate(rows, r)] == ["jf:cfae7", "jf:cfae9", "tmdb:1"]
    media_db.skip("you", "jf:cfa", "tv", "Colin from Accounts", forever=True)
    r = media_home.Ratings()
    r.owner, r.level = "you", "episode"
    assert [x["item_key"] for x in media_home._to_rate(rows, r)] == ["tmdb:1"]
    her = media_home.Ratings()
    her.owner, her.level = "her", "episode"
    assert len(media_home._to_rate(rows, her)) == 5                         # her inbox: none of your skips


# ---- the pages ----

def test_rows_offer_skip_and_skip_show_as_scroll_keeping_forms(env):
    build, _ = env
    with build() as client:
        films = section(client.get("/media/movies/to-rate").text)
        tv = section(client.get("/media/tv/to-rate").text)
    assert films.count('action="/media/rate/skip"') == 2 and "/media/rate/skip-show" not in films   # Heat, Already Rated
    assert 'hx-swap="innerHTML show:none"' in films and ">Skip</button>" in films
    # show level: the row IS the show, so only Skip show
    assert "/media/rate/skip-show" in tv and 'action="/media/rate/skip"' not in tv and ">Skip show</button>" in tv


def test_skip_a_film_drops_it_and_the_count_then_unskip_brings_it_back(env):
    build, _ = env
    with build() as client:
        assert subtabs(client.get("/media/movies").text)[1][3] == (2, "to rate")   # nav-tidy: My films · To rate · Awards
        r = post(client, "/media/rate/skip", item_key="tmdb:1", kind="movie", title="Heat", poster="jf:p-1",
                 back="/media/movies/to-rate")
        assert r.status_code == 303 and r.headers["location"] == "/media/movies/to-rate?skip=item"
        html = client.get("/media/movies/to-rate?skip=item").text
        body = main_of(html)
        assert '<p class="metaline st-good" role="status">Skipped</p>' in body
        assert subtabs(html)[1][3] == (1, "to rate")                            # the amber count drops
        inbox = section(html).split('<section class="sec skipped">', 1)[0]
        assert "Heat" not in inbox
        skipped = body.split('<section class="sec skipped">', 1)[1]
        assert ">Skipped<span class=\"sep\"> · </span>1</h2>" in skipped and "Heat" in skipped
        assert 'action="/media/rate/unskip"' in skipped and ">Unskip</button>" in skipped
        assert "Skipped" in skipped.split('class="row-meta"', 1)[1]
        r = post(client, "/media/rate/unskip", key="tmdb:1", back="/media/movies/to-rate")
        assert r.headers["location"] == "/media/movies/to-rate?skip=unskip"
        html = client.get("/media/movies/to-rate").text
    assert "Heat" in section(html) and 'class="sec skipped"' not in html


def test_skip_show_hides_every_episode_and_later_ones(env):
    build, _ = env
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        assert section(client.get("/media/tv/to-rate").text).count('class="ratepick"') == 3
        r = post(client, "/media/rate/skip-show", item_key="jf:cfa", kind="tv", title="Colin from Accounts",
                 back="/media/tv/to-rate")
        assert r.headers["location"] == "/media/tv/to-rate?skip=show"
        html = client.get("/media/tv/to-rate").text
        assert section(html) is None and "Whole show" in html
    later = TV + [tv_row("cfa", "cfas3", 3, "cfae20", 1, "New Season", 0)]
    with build(jelly_data(later)) as client:
        assert section(client.get("/media/tv/to-rate").text) is None             # a later episode stays skipped
        diary = client.get("/media/history").text.split(">To rate</h2>", 1)[1]
        assert "Colin from Accounts" not in diary.split('<section class="sec skipped">', 1)[0]


def test_diary_to_rate_page_lists_skipped_too(env):
    build, _ = env
    with build() as client:
        post(client, "/media/rate/skip", item_key="tmdb:1", kind="movie", title="Heat")
        html = client.get("/media/history?skip=item").text
    assert '<section class="sec skipped">' in html and "Skipped</p>" in html


def test_bad_skips_are_refused(env):
    build, _ = env
    with build() as client:
        assert post(client, "/media/rate/skip", item_key="http://x", kind="movie", title="X").status_code == 422
        assert post(client, "/media/rate/skip-show", item_key="tmdb:1", kind="movie", title="X").status_code == 422
        assert post(client, "/media/rate/unskip", key="nope").status_code == 422
        r = client.post("/media/rate/skip", data={"item_key": "tmdb:1", "kind": "movie", "title": "Heat"},
                        headers={"Origin": "https://evil.example"}, follow_redirects=False)
        assert r.status_code == 403
        r = post(client, "/media/rate/skip", item_key="tmdb:1", kind="movie", title="Heat", back="https://evil.example")
        assert r.headers["location"] == "/media/history?skip=item"               # back is a fixed list
