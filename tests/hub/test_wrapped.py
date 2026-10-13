"""Wrapped (WP E6, 2026-10-13; review_features M1): GET /media/diary/year/{year} — Numbers, Top rated, Most watched
shows, Firsts and lasts, Rewatches, Award winners you saw, then the data sources in one quiet line. A summary, never a
ranking UI (By-year rankings deleted 2026-10-09). Pure reads of media.db + the jellyfin snapshot; nothing fabricated:
hours from recorded plays, else the diary's film runtimes, else "—"; busiest weekday / hour from the recorder only."""
import re
from contextlib import closing
from datetime import date, datetime, timedelta

import pytest

from hub import media_db, media_nav, media_plays_db, media_store, media_wrapped
from hub.ids import home_now
from tests.hub.conftest import main_of
from tests.hub.test_media_rate import JELLY, env  # noqa: F401  (env: the Diary fixture)

NOW = datetime(2026, 10, 13, 20, 0)


def local(day: date, hour=20, minute=0) -> datetime:
    return media_wrapped._local(day) + timedelta(hours=hour, minutes=minute)


def diary(key, kind, title, day, owner="you", source="jellyfin", year=None, poster=None, show_key=None,
          show_title=None, season=None, episode=None):
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO diary(item_key, kind, title, year, poster, watched_on, source, owner, created_at, show_key,"
                   " season, episode, show_title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (key, kind, title, year, poster, day, source, owner, "2026-01-01T00:00:00", show_key, season,
                    episode, show_title))


def play(jf_id, kind, title, start: datetime, minutes, runtime=None, owner="you", item_key=None, show_key=None,
         show_title=None):
    end = start + timedelta(minutes=minutes)
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO play(user_name, owner, jf_id, item_key, show_key, title, show_title, kind, runtime_min,"
                   " started_at, last_seen_at, position_pct, finished) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("u", owner, jf_id, item_key, show_key, title, show_title, kind, runtime,
                    media_plays_db._iso(start), media_plays_db._iso(end), 100, 1))


def eps(show_key, show_title, days, start_ep=1, owner="you"):
    for i, d in enumerate(days):
        diary(f"{show_key}e{start_ep + i}", "tv", show_title, d, owner=owner, show_key=show_key, show_title=show_title,
              season=1, episode=start_ep + i, poster=f"jf:{show_key[3:]}")


MOVIES = [{"item_key": "tmdb:1", "jf_id": "anora1", "title": "Anora", "year": 2024, "poster": "jf:anora1", "runtime_min": 139},
          {"item_key": "tmdb:2", "jf_id": "old1", "title": "Old Film", "year": 1959, "poster": "jf:old1", "runtime_min": 100},
          {"item_key": "tmdb:3", "jf_id": "mid1", "title": "Mid Film", "year": 2001, "poster": "jf:mid1"}]
SHOWS = [{"item_key": "tmdb:100", "jf_id": "ser1", "title": "Quiet Show", "episodes": 26, "unplayed": 6,
          "poster": "jf:ser1"},
         {"item_key": "tmdb:200", "jf_id": "ser2", "title": "Done Show", "episodes": 4, "unplayed": 0, "poster": "jf:ser2"}]


def jelly(movies=MOVIES, shows=SHOWS):
    return {**JELLY, "history": {**JELLY["history"], "recent": []}, "movies": movies, "shows": shows}


@pytest.fixture()
def wrap(env, monkeypatch):
    """(client builder, db file) with "today" pinned to Tue 13 Oct 2026, 20:00 at home."""
    build, db_file = env
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(NOW.date(), 20))
    media_wrapped.clear()

    def client(**kw):
        return build(jelly=jelly(**kw))
    return client, db_file


def seed_year():
    """2026: Anora (rated 9, a rewatch), Old Film (rated 7), Mid Film (no runtime, rated 10); Quiet Show x5 episodes,
    Done Show x2; one hand-logged film; plays from 6 Oct (the recorder's start) on Sunday nights."""
    media_store.connect().close()
    diary("tmdb:1", "movie", "Anora", "2025-12-30")                                 # last year: makes 2026's a rewatch
    diary("tmdb:2", "movie", "Old Film", "2026-01-02", poster="jf:old1")
    diary("tmdb:3", "movie", "Mid Film", "2026-03-10")
    diary("tmdb:1", "movie", "Anora", "2026-10-06", poster="jf:anora1")                # the play below covers it
    diary("tmdb:9", "movie", "Hand Logged", "2026-10-12", source="manual", year=2026)
    eps("jf:ser1", "Quiet Show", ["2026-03-10", "2026-03-11", "2026-03-12", "2026-10-11", "2026-10-12"])
    eps("jf:ser2", "Done Show", ["2026-03-14", "2026-03-15"])
    media_db.set_rating("tmdb:1", 9, "movie", "Anora")
    media_db.set_rating("tmdb:2", 7, "movie", "Old Film")
    media_db.set_rating("tmdb:3", 10, "movie", "Mid Film")
    play("anora1", "movie", "Anora", local(date(2026, 10, 6), 21), 130, runtime=139, item_key="tmdb:1")
    play("ep4", "episode", "Quiet Show · S01E04", local(date(2026, 10, 11), 21), 45, runtime=45, item_key="jf:ep4",
         show_key="jf:ser1", show_title="Quiet Show")
    play("ep5", "episode", "Quiet Show · S01E05", local(date(2026, 10, 11), 22), 45, runtime=45, item_key="jf:ep5",
         show_key="jf:ser1", show_title="Quiet Show")


def page(client, year=2026, **q):
    r = client.get(f"/media/diary/year/{year}", params=q)
    assert r.status_code == 200
    return r, main_of(r.text)


def sec(b, label):
    return b.split(f'<h2 class="seclabel">{label}', 1)[1].split("</section>", 1)[0]


# ---- the summary (media_wrapped) ----

def test_numbers_count_the_diary_once_per_title_and_day(wrap):
    build, _ = wrap
    with build():
        seed_year()
        diary("tmdb:1", "movie", "Anora", "2026-10-06", source="manual")          # synced AND logged: one watch
        w = media_wrapped.summary("you", jelly(), 2026)
    assert (w["films"], w["episodes"]) == (4, 7)
    # days: 2 Jan, 10-12 Mar + 14-15 Mar, 6 Oct (a play), 11-12 Oct
    assert w["days"] == 9 and w["streak"] == 3
    assert w["busiest_month"] == {"text": "March", "note": "6 watches"}


def test_hours_are_plays_from_the_recorder_on_plus_film_runtimes_before(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
    # plays 130 + 45 + 45 = 220 min; + Old Film 100 min (no play covers it); Mid Film has no runtime: adds nothing;
    # Anora on 6 Oct is covered by its play (not counted twice)
    assert w["minutes"] == pytest.approx(320) and w["hours_text"] == "5h 20m"
    assert w["hours_note"] == "Plays since 6 Oct + film runtimes"


def test_a_film_the_recorder_missed_adds_its_runtime_once(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        play("x", "movie", "Other", local(date(2026, 10, 1), 20), 60, runtime=60, item_key="tmdb:50")
        diary("tmdb:2", "movie", "Old Film", "2026-10-08")                       # no play of it: 100 min from the snapshot
        diary("tmdb:1", "movie", "Anora", "2026-10-09")
        play("anora1", "movie", "Anora", local(date(2026, 10, 8), 23), 139, runtime=139)   # by jf id, a day apart
        w = media_wrapped.summary("you", jelly(), 2026, 10)
    assert w["minutes"] == pytest.approx(60 + 100 + 139) and w["hours_note"] == "Plays + film runtimes"


def test_no_plays_and_no_runtimes_means_no_hours(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        diary("tmdb:3", "movie", "Mid Film", "2026-03-10")
        w = media_wrapped.summary("you", jelly(), 2026)
        assert w["minutes"] is None and w["hours_text"] == "—" and "h" not in w["sentence"]
        diary("tmdb:2", "movie", "Old Film", "2026-03-11")
        media_wrapped.clear()
        w = media_wrapped.summary("you", jelly(), 2026)
    assert w["hours_text"] == "1h 40m" and w["hours_note"] == "Films only"


def test_busiest_weekday_and_hour_come_from_the_recorder_only(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-03-11")
        w = media_wrapped.summary("you", jelly(), 2026)
        assert w["busiest_weekday"] is None and w["busiest_hour"] is None and w["mostly"] is None
        seed_year()
        media_wrapped.clear()
        w = media_wrapped.summary("you", jelly(), 2026)
    assert w["busiest_weekday"] == {"text": "Sunday", "note": "2 plays"}
    assert w["busiest_hour"] == {"text": "21:00", "note": "2 plays"}
    assert w["mostly"] == "Sunday nights"


def test_mostly_needs_three_plays(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        play("a", "movie", "A", local(date(2026, 10, 11), 21), 60)
        play("b", "movie", "B", local(date(2026, 10, 4), 21), 60)
        assert media_wrapped.summary("you", jelly(), 2026)["mostly"] is None
        play("c", "movie", "C", local(date(2026, 10, 7), 9), 60)
        media_wrapped.clear()
        assert media_wrapped.summary("you", jelly(), 2026)["mostly"] == "Sunday nights"


def test_owner_scoped_and_both_counts_a_shared_watch_once(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-03-11")
        diary("tmdb:2", "movie", "Old Film", "2026-03-11", owner="her")
        diary("tmdb:3", "movie", "Mid Film", "2026-03-12", owner="her")
        you, her, both = (media_wrapped.summary(v, jelly(), 2026) for v in ("you", "her", "both"))
    assert (you["films"], her["films"], both["films"]) == (1, 2, 2)


def test_top_rated_is_nines_and_tens_and_the_average(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
    assert [(r["title"], r["score"]) for r in w["top_rated"]] == [("Mid Film", 10), ("Anora", 9)]
    assert (w["rated"], w["average_text"]) == (3, "8.7")
    assert w["best"] == {"title": "Mid Film", "score": 10}


def test_top_rated_keeps_twelve(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        for i in range(15):
            diary(f"tmdb:{500 + i}", "movie", f"Film {i:02d}", f"2026-02-{i + 1:02d}")
            media_db.set_rating(f"tmdb:{500 + i}", 9, "movie", f"Film {i:02d}")
        w = media_wrapped.summary("you", jelly(), 2026)
    assert len(w["top_rated"]) == media_wrapped.TOP_RATED_MAX == 12 and w["rated"] == 15


def test_most_watched_shows_with_progress_while_going(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
    shows = [(g["title"], g["episodes"], g["progress"]) for g in w["shows"]]
    # Quiet Show: 6 left x 45 min (the recorded plays' runtime); Done Show is all watched: no words
    assert shows == [("Quiet Show", 5, "6 left · ~4h 30m"), ("Done Show", 2, None)]
    assert w["shows"][0]["href"] == "/media/item/ser1"


def test_most_watched_shows_keeps_eight(wrap):
    build, _ = wrap
    with build():
        media_store.connect().close()
        for i in range(10):
            eps(f"jf:sx{i}", f"Show {i}", ["2026-05-01"])
        w = media_wrapped.summary("you", jelly(), 2026)
    assert len(w["shows"]) == media_wrapped.SHOWS_MAX == 8


def test_firsts_and_lasts(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
    got = [(f["label"], f["title"], f["note"]) for f in w["firsts"]]
    # the diary's own year is empty for Jellyfin rows: the snapshot's year is used; Hand Logged carries its own
    assert got == [("First watch", "Old Film", "2 Jan"), ("Last watch", "Quiet Show", "12 Oct"),
                   ("Oldest film", "Old Film", "1959"), ("Newest film", "Hand Logged", "2026")]


def test_rewatches(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
    assert w["rewatches"]["count"] == 1 and [r["title"] for r in w["rewatches"]["rows"]] == ["Anora"]


def seed_awards():
    """An Oscars edition held in 2026 (Anora won Best Picture; Unseen Film won Best Director) and one held in 2025
    (Mid Film won) — only a 2026 winner the viewer saw belongs on 2026's page."""
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO award_edition(body_id, ordinal, year, state) VALUES('oscars', 98, 2026, 'done')")
        db.execute("INSERT INTO award_edition(body_id, ordinal, year, state) VALUES('oscars', 97, 2025, 'done')")
        for key, name, rank in (("picture", "Best Picture", 1), ("director", "Best Director", 2)):
            db.execute("INSERT OR IGNORE INTO award_category(body_id, cat_key, name, kind, grp, rank, lead)"
                       " VALUES('oscars', ?, ?, 'film', 'core', ?, 'work')", (key, name, rank))
        for qid, label, tmdb in (("Q1", "Anora", 1), ("Q2", "Unseen Film", 77), ("Q3", "Mid Film", 3)):
            db.execute("INSERT INTO award_entity(qid, kind, label, tmdb_movie) VALUES(?, 'film', ?, ?)", (qid, label, tmdb))
        for ordinal, cat, qid, title in ((98, "picture", "Q1", "Anora"), (98, "director", "Q2", "Unseen Film"),
                                         (97, "picture", "Q3", "Mid Film")):
            db.execute("INSERT INTO award_nomination(body_id, ordinal, cat_key, work_qid, work_title, won, pos)"
                       " VALUES('oscars', ?, ?, ?, ?, 1, 1)", (ordinal, cat, qid, title))


def test_award_winners_you_saw_are_that_years_ceremonies(wrap):
    build, _ = wrap
    with build():
        seed_year()
        seed_awards()
        w = media_wrapped.summary("you", jelly(), 2026)
    assert [(r["title"], r["award"]["label"]) for r in w["winners"]] == [("Anora", "Won Best Picture · Oscars 2026")]
    assert w["winners"][0]["href"] == "/media/item/anora1"


def test_sources_line_names_the_recorder_start_from_the_first_play(wrap):
    build, _ = wrap
    with build():
        seed_year()
        w = media_wrapped.summary("you", jelly(), 2026)
        assert w["sources"] == "Plays recorded by Joey since 6 Oct 2026 · Jellyfin history · Diary"
        play("x", "movie", "Earlier", local(date(2026, 9, 1), 20), 30)
        media_wrapped.clear()
        assert media_wrapped.summary("you", jelly(), 2026)["sources"].startswith("Plays recorded by Joey since 1 Sep 2026")


def test_summary_is_kept_until_media_db_changes(wrap):
    build, _ = wrap
    with build():
        seed_year()
        a = media_wrapped.summary("you", jelly(), 2026, stamp="s1")
        assert media_wrapped.summary("you", jelly(), 2026, stamp="s1") is a
        diary("tmdb:2", "movie", "Old Film", "2026-04-01")
        b = media_wrapped.summary("you", jelly(), 2026, stamp="s1")
    assert b is not a and b["films"] == a["films"] + 1


def test_no_media_db_is_an_empty_summary(wrap):
    build, db_file = wrap
    with build():
        w = media_wrapped.summary("you", jelly(), 2026)
    assert not db_file.exists() and w["empty"] and w["hours_text"] == "—" and w["sentence"] == ""


# ---- the page ----

def test_page_sections_in_order_and_title(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        seed_awards()
        r, b = page(client)
    assert "<title>2026 · Joey</title>" in r.text and "<h1>2026</h1>" in r.text
    labels = re.findall(r'<h2 class="seclabel">([^<]+)</h2>', b)
    assert labels == ["Numbers", "Top rated", "Most watched shows", "Firsts and lasts", "Rewatches · 1",
                      "Award winners you saw · 1"]
    assert '<p class="metaline wrapfoot">Plays recorded by Joey since 6 Oct 2026 · Jellyfin history · Diary</p>' in b


def test_page_numbers_are_stats(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        _, b = page(client)
    n = sec(b, "Numbers")
    for label in ("Films", "Episodes", "Hours", "Days watched", "Longest streak", "Busiest month",   # E6 eyes-on: fits 375 px
                  "Busiest weekday", "Busiest hour"):
        assert f'<div class="stat"><div class="microlabel">{label}</div>' in n
    assert '<div class="stat-word">5h 20m</div><div class="row-meta">Plays since 6 Oct + film runtimes</div>' in n
    assert '<div class="stat-word">3 days</div>' in n and '<div class="stat-word">March</div>' in n
    assert '<div class="stat-word">Sunday</div>' in n and '<div class="stat-number">21:00</div>' in n


def test_page_top_rated_shows_and_winners(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        seed_awards()
        _, b = page(client)
    top = sec(b, "Top rated")
    assert "3 films rated · average 8.7" in top and 'class="carousel"' in top
    assert top.index(">Mid Film<") < top.index(">Anora<") and "Old Film" not in top
    assert "gold-glow" in top                                                       # a perfect 10 keeps its glow
    shows = sec(b, "Most watched shows")
    assert "5 episodes · 6 left · ~4h 30m" in shows and "2 episodes" in shows and "All watched" not in shows
    won = sec(b, "Award winners you saw")
    assert 'class="card-pic is-won"' in won and 'class="awbadge"' in won and "Won Best Picture · Oscars 2026" in won
    assert "Unseen Film" not in won and "Mid Film" not in won


def test_page_is_a_summary_not_a_ranking(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        seed_awards()
        _, b = page(client)
    assert "row-rank" not in b and "podium" not in b.lower()
    assert not re.search(r"\b(Rank|Place)\b", b)


def test_empty_year_says_nothing_watched_without_a_full_stop(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        _, b = page(client, 2019)
    assert '<p class="empty">Nothing watched in 2019</p>' in b and "Numbers" not in b


def test_bad_years_are_404(wrap):
    build, _ = wrap
    with build() as client:
        assert client.get("/media/diary/year/abc").status_code == 404
        assert client.get("/media/diary/year/1800").status_code == 404


def test_stepper_moves_between_years_with_data_and_this_year(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        diary("tmdb:2", "movie", "Old Film", "2022-05-01")
        s26 = page(client, 2026)[1].split('<nav class="wrapstep"', 1)[1].split("</nav>", 1)[0]
        s25 = page(client, 2025)[1].split('<nav class="wrapstep"', 1)[1].split("</nav>", 1)[0]
        s24 = page(client, 2024)[1].split('<nav class="wrapstep"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/media/diary/year/2025"' in s26 and 'aria-disabled="true">›<' in s26
    assert 'href="/media/diary/year/2022"' in s25 and 'href="/media/diary/year/2026"' in s25
    assert 'href="/media/diary/year/2022"' in s24 and 'href="/media/diary/year/2025"' in s24


def test_page_is_owner_scoped(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        diary("tmdb:3", "movie", "Mid Film", "2026-03-12", owner="her")
        _, you = page(client, owner_view="you")
        _, her = page(client, owner_view="her")
    assert "Nothing watched in 2026" in you and "Mid Film" in her


# ---- navigation ----

def test_diary_tabs_gain_year_pointing_at_this_years_wrapped():
    tabs = {s["id"]: [label for label, _ in s["tabs"]] for s in media_nav.SECTIONS}
    assert tabs["diary"] == ["Diary", "To Rate", "Year"]            # deliberate pin (E6): the Year tab is last
    assert media_nav.tab_href(media_nav.YEAR_TAB) == f"/media/diary/year/{home_now().year}"
    assert media_nav.tab_href("/media/diary") == "/media/diary"


def test_year_tab_is_lit_on_any_wrapped_page(wrap):
    build, _ = wrap
    with build() as client:
        b = client.get("/media/diary/year/2024").text
        d = client.get("/media/diary").text
    sub = b.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]
    assert f'<a href="/media/diary/year/{home_now().year}" aria-current="page">Year</a>' in sub
    assert '<a href="/media/diary" aria-current="page">' in d.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]


def test_year_without_a_number_goes_to_this_year(wrap):
    build, _ = wrap
    with build() as client:
        r = client.get("/media/diary/year", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/media/diary/year/2026"


def test_hub_gets_no_wrapped_card(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        assert "/media/diary/year" not in client.get("/").text


def test_css_tail_block_uses_tokens_only():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    block = css.split("/* ---- E6 wrapped (2026-10-13) ---- */", 1)[1]
    assert ".monthcard" in block and ".wrapstep" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block)
