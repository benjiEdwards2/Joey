"""E1 (2026-10-13): media.db readers are one kept connection per thread, reused across every read (a Media page used
to open 5-10). close() keeps it; a new file (MEDIA_DB_PATH, a restored backup) or reset() replaces it; writes keep
their own fresh connection and are seen by the next read at once."""
import sqlite3
import threading
from collections import Counter
from contextlib import closing

from hub import media_db, media_store
from tests.hub.helpers import env  # noqa: F401  (env fixture)


def make_db():
    media_db.set_rating("tmdb:1", 8, "movie", "One")


def test_a_thread_reuses_one_reader_and_close_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "m.db"))
    make_db()
    a = media_store.reader()
    with closing(a):
        assert a.execute("SELECT COUNT(*) FROM rating").fetchone()[0] == 1
    b = media_store.reader()
    assert b is a and b.execute("SELECT 1").fetchone()[0] == 1          # still open after closing()
    other = []
    t = threading.Thread(target=lambda: other.append(media_store.reader()))
    t.start()
    t.join()
    assert other[0] is not a                                            # another thread: its own


def test_a_write_is_seen_by_the_kept_reader_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "m.db"))
    make_db()
    assert media_db.get_ratings(["tmdb:1", "tmdb:2"]) == {"tmdb:1": 8}
    media_db.set_rating("tmdb:2", 6, "movie", "Two")                   # connect(): its own connection
    assert media_db.get_ratings(["tmdb:1", "tmdb:2"]) == {"tmdb:1": 8, "tmdb:2": 6}


def test_a_new_file_gets_a_new_reader_and_reset_closes_them(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "a.db"))
    make_db()
    a = media_store.reader()
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "b.db"))
    assert media_store.reader() is None                                 # no file yet: reads never create it
    make_db()
    b = media_store.reader()
    assert b is not a and a.shut
    media_store.reset()
    assert b.shut
    try:
        b.execute("SELECT 1")
        raise AssertionError("a reset reader still answers")
    except sqlite3.ProgrammingError:
        pass
    c = media_store.reader()
    assert c is not b and c.execute("SELECT COUNT(*) FROM rating").fetchone()[0] == 1


def test_a_media_home_render_opens_at_most_one_connection_per_thread(env, monkeypatch, tmp_path):
    client, _ = env()
    make_db()                                                           # production: media.db always exists
    media_store.reset()
    opens = Counter()
    real = sqlite3.connect

    def counting(*a, **k):
        opens[threading.get_ident()] += 1
        return real(*a, **k)
    monkeypatch.setattr(media_store.sqlite3, "connect", counting)
    with client:
        for _ in range(3):
            assert client.get("/a/alpha").status_code == 200
            assert client.get("/media/item/mov1").status_code == 200
    assert opens and max(opens.values()) == 1, opens
