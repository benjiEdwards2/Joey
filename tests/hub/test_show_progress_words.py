"""E5 (M2, 2026-10-13): show progress in words — "4 left · ~3h 10m" on Continue watching cards and the My shows
rows / cards. The hours come from the recorded plays' average episode runtime and drop out when it is unknown; a
show with no counts says nothing (never a guess)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_home, media_plays_db
from hub.media_text import progress_words
from tests.hub.test_media_frame import env  # noqa: F401
from tests.hub.test_media_library_pages import body, jelly


def test_progress_words():
    assert progress_words(4, 10, 47.5) == "4 left · ~3h 10m"
    assert progress_words(4, 10, None) == "4 left"
    assert progress_words(1, 10, 0) == "1 left"
    assert progress_words(0, 10, 45) == "All watched"
    assert progress_words(0, 0, 45) is None                  # no episodes is not "all watched"
    assert progress_words(None, 10, 45) is None and progress_words(3, None, 45) is None
    assert progress_words(True, 10, 45) is None and progress_words(-1, 10, 45) is None


def _play(show_key, runtime, jf):
    media_plays_db.record_sighting({"user_name": "b", "owner": "you", "jf_id": jf, "kind": "episode",
                                    "show_key": show_key, "runtime_min": runtime, "position_pct": 95},
                                   datetime.now(timezone.utc))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))


def test_show_runtimes_average_per_show(db):
    assert media_plays_db.show_runtimes(["jf:a"]) == {}                       # no file: reads never create it
    _play("jf:a", 40, "e1")
    _play("jf:a", 50, "e2")
    _play("jf:b", None, "e3")
    assert media_plays_db.show_runtimes(["jf:a", "jf:b", "jf:c", None]) == {"jf:a": 45.0}


def test_continue_progress_uses_the_view_owners_counts(db):
    _play("jf:s1", 30, "e1")
    data = {"shows": [{"jf_id": "s1", "unplayed": 4, "episodes": 10}, {"jf_id": "s2", "unplayed": 0, "episodes": 8}],
            "her": {"shows": [{"jf_id": "s1", "unplayed": 9, "episodes": 10}]}}
    rows = [{"show_key": "jf:s1"}, {"show_key": "jf:s2"}, {"show_key": None}]
    assert media_home.continue_progress(data, "you", rows) == {"jf:s1": "4 left · ~2h"}   # s2: never "All watched"
    assert media_home.continue_progress(data, "her", rows) == {"jf:s1": "9 left · ~4h 30m"}
    assert media_home.continue_progress({"shows": data["shows"]}, "her", rows) == {}    # her view, no list of hers


def test_continue_watching_card_says_progress(env, monkeypatch):
    up = {"title": "Echo Show · S02E05 · Five", "remaining_text": "Next episode", "poster": None, "kind": "episode",
          "item_key": "jf:jtmdb-21", "show_key": "jf:jtmdb-21", "jf_id": "ep5"}
    main = env(jellyfin=jelly(up_next=[up]))
    _play("jf:jtmdb-21", 30, "e1")
    with TestClient(main.app) as c:
        _, b = body(c, "/a/alpha")
    assert '<span class="row-meta">Next episode · 6 left · ~3h</span>' in b


def test_my_shows_rows_and_watching_cards_say_progress(env):
    main = env(jellyfin=jelly())
    _play("jf:jtmdb-21", 45, "e1")
    with TestClient(main.app) as c:
        _, rows = body(c, "/media/tv?view=list")
        _, grid = body(c, "/media/tv?view=grid")
    assert "26 episodes · 6 left · ~4h 30m" in rows and "10 episodes · 10 left" in rows
    assert "8 episodes · All watched" in rows
    assert grid.count('class="row-meta card-progress"') == 1                    # only the show being watched
    assert '<span class="row-meta card-progress">6 left · ~4h 30m</span>' in grid


def test_progress_words_is_a_template_global():
    assert media_home.shell.templates.env.globals["progress_words"] is progress_words
