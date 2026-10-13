"""Month in Review (WP E6, 2026-10-13; review_features M1): the Diary page opens with ONE .panel — "This month" (the
home-time month), a stats strip (films · episodes · hours · days watched · average score), ONE sentence in words and
"All of <year> →" to the Wrapped page. While the month has nothing yet it shows the month before ("October · nothing yet"
then "September: …"). Hours: recorded plays, else the diary's film runtimes, else dropped (never guessed)."""
from datetime import date

from hub import media_db, media_store, media_wrapped
from tests.hub.conftest import main_of
from tests.hub.test_media_rate import env  # noqa: F401  (env: the Diary fixture, under wrap)
from tests.hub.test_wrapped import diary, eps, jelly, local, play, seed_year, wrap  # noqa: F401  (wrap: fixture)


def card(b):
    return b.split('<section class="panel monthcard"', 1)[1].split("</section>", 1)[0]


def diary_page(client, **q):
    r = client.get("/media/diary", params=q)
    assert r.status_code == 200
    return main_of(r.text)


def test_card_leads_the_diary_above_the_filters(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        b = diary_page(client)
    assert b.index('class="panel monthcard"') < b.index('class="metaline"') < b.index('class="toolbar"')
    c = card(b)
    assert '<h2 class="seclabel" id="monthcard-h">This month</h2>' in c
    assert '<a href="/media/diary/year/2026">All of 2026 →</a>' in c


def test_card_strip_and_sentence(wrap):
    build, _ = wrap
    with build() as client:
        seed_year()
        c = card(diary_page(client))
    for label, value in (("Films", 2), ("Episodes", 2), ("Days watched", 3)):
        assert f'<div class="microlabel">{label}</div><div class="stat-number">{value}</div>' in c
    # October: plays 130 + 45 + 45 min; Anora 9 is the month's only rated film
    assert '<div class="microlabel">Hours</div><div class="stat-word">3h 40m</div>' in c
    assert '<div class="microlabel">Average score</div><div class="stat-number">9</div>' in c
    assert '<p class="monthline">2 films · 2 episodes · 3h 40m · mostly Sunday nights · best: Anora 9</p>' in c


def test_empty_month_shows_the_month_before(wrap, monkeypatch):
    build, _ = wrap
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(date(2026, 11, 3), 9))
    with build() as client:
        seed_year()
        c = card(diary_page(client))
    assert '<h2 class="seclabel" id="monthcard-h">November · nothing yet</h2>' in c
    assert '<p class="monthline">October: 2 films · 2 episodes · 3h 40m · mostly Sunday nights · best: Anora 9</p>' in c


def test_january_falls_back_to_last_december_and_its_year(wrap, monkeypatch):
    build, _ = wrap
    monkeypatch.setattr(media_wrapped, "_now", lambda: local(date(2027, 1, 2), 9))
    with build() as client:
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-12-20")
        c = card(diary_page(client))
    assert "January · nothing yet" in c and '<p class="monthline">December: 1 film · 1h 40m</p>' in c
    assert '<a href="/media/diary/year/2026">All of 2026 →</a>' in c


def test_nothing_at_all_is_a_label_and_the_link(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        c = card(diary_page(client))
    assert "October · nothing yet" in c and 'class="stats"' not in c and "monthline" not in c
    assert "All of 2026 →" in c


def test_no_hours_source_is_a_dash_and_left_out_of_the_sentence(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        diary("tmdb:3", "movie", "Mid Film", "2026-10-02")                     # the snapshot has no runtime for it
        eps("jf:ser1", "Quiet Show", ["2026-10-03"])
        c = card(diary_page(client))
    assert '<div class="microlabel">Hours</div><div class="stat-word blank">—</div>' in c
    assert '<p class="monthline">1 film · 1 episode</p>' in c
    assert '<div class="microlabel">Average score</div><div class="stat-number blank">—</div>' in c


def test_film_runtimes_stand_in_before_the_recorder(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-10-02")
        c = card(diary_page(client))
    assert '<div class="stat-word">1h 40m</div><div class="row-meta">Films only</div>' in c


def test_card_is_owner_scoped(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-10-02", owner="her")
        media_db.set_rating("tmdb:2", 6, "movie", "Old Film", owner="her")
        you = card(diary_page(client, owner_view="you"))
        her = card(diary_page(client, owner_view="her"))
        both = card(diary_page(client, owner_view="both"))
    assert "October · nothing yet" in you
    assert '<p class="monthline">1 film · 1h 40m · best: Old Film 6</p>' in her
    assert '<p class="monthline">1 film · 1h 40m</p>' in both            # the both view reads B.'s scores (none)


def test_both_view_counts_a_watch_together_once(wrap):
    build, _ = wrap
    with build() as client:
        media_store.connect().close()
        diary("tmdb:2", "movie", "Old Film", "2026-10-07")
        diary("tmdb:2", "movie", "Old Film", "2026-10-07", owner="her")
        play("old1", "movie", "Old Film", local(date(2026, 10, 7), 20), 100, runtime=100, item_key="tmdb:2")
        play("old1", "movie", "Old Film", local(date(2026, 10, 7), 20), 98, runtime=100, item_key="tmdb:2", owner="her")
        c = card(diary_page(client, owner_view="both"))
    # two profiles, one sitting: one film, 100 minutes once (the longer play), one day
    assert '<p class="monthline">1 film · 1h 40m</p>' in c
    assert '<div class="microlabel">Days watched</div><div class="stat-number">1</div>' in c
