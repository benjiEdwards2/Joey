"""media.db backups (2026-10-05): whole-or-nothing gzip dumps, the prune rules, the
status thresholds, the hub scheduler, and the surfaces (/media/apps row, warning line).
Page text is asserted inside <main>."""
import gzip
import importlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_backup as mb
from tests.hub.test_media_shelves import shelf_area
from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope
from tests.hub.conftest import main_raw as main_of

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE rating(item_key TEXT PRIMARY KEY, score INT)")
        c.execute("INSERT INTO rating VALUES ('tmdb:1', 8)")
    return path


def dump_name(dt):
    return f"media-{dt.strftime('%Y-%m-%d_%H%M')}.db.gz"


def touch_dump(dest, dt, size=10):
    p = dest / dump_name(dt)
    p.write_bytes(b"x" * size)
    return p


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    db = tmp_path / "sqlite" / "media.db"
    dest = tmp_path / "backups"
    dest.mkdir()
    monkeypatch.setenv("MEDIA_DB_PATH", str(db))
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(dest))
    monkeypatch.delenv("MEDIA_BACKUP", raising=False)
    return db, dest


# --- backup_now ---------------------------------------------------------------

def test_backup_is_a_gzip_of_a_db_that_passes_integrity(paths, tmp_path):
    db, dest = paths
    make_db(db)
    out = mb.backup_now(db, dest, NOW)
    assert out.name == "media-2026-10-05_1200.db.gz"
    assert [p.name for p in dest.iterdir()] == [out.name]       # no temp files left
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(out.read_bytes()))
    with sqlite3.connect(restored) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT score FROM rating").fetchone()[0] == 8


def test_failed_integrity_leaves_nothing(paths, monkeypatch):
    db, dest = paths
    make_db(db)
    monkeypatch.setattr(mb, "_integrity", lambda conn: "*** page 2 is never used")
    with pytest.raises(ValueError):
        mb.backup_now(db, dest, NOW)
    assert list(dest.iterdir()) == []


def test_missing_db_raises_and_leaves_nothing(paths):
    db, dest = paths
    with pytest.raises(FileNotFoundError):
        mb.backup_now(db, dest, NOW)
    assert list(dest.iterdir()) == [] and not db.exists()


# --- prune --------------------------------------------------------------------

def test_prune_rules(tmp_path):
    keep = [NOW - timedelta(days=d) for d in (0, 1, 10, 29)]          # inside 30 days
    keep += [datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),          # first of August
             datetime(2026, 1, 3, 9, 0, tzinfo=timezone.utc),          # first of January
             datetime(2024, 11, 1, 9, 0, tzinfo=timezone.utc)]         # first of month, 23 months back
    drop = [datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),           # second in August
            datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc),
            datetime(2024, 9, 1, 9, 0, tzinfo=timezone.utc),           # over 24 months
            datetime(2023, 3, 1, 9, 0, tzinfo=timezone.utc)]
    for dt in keep + drop:
        touch_dump(tmp_path, dt)
    (tmp_path / "notes.txt").write_text("not a dump")
    (tmp_path / ".media-abc.db.tmp").write_text("temp")
    removed = mb.prune(tmp_path, NOW)
    assert sorted(p.name for p in removed) == sorted(dump_name(d) for d in drop)
    left = {p.name for p in tmp_path.iterdir()}
    assert left == {dump_name(d) for d in keep} | {"notes.txt", ".media-abc.db.tmp"}


# --- newest / status ----------------------------------------------------------

def test_newest_parses_the_filename(tmp_path):
    assert mb.newest(tmp_path, NOW) is None
    touch_dump(tmp_path, NOW - timedelta(days=3))
    touch_dump(tmp_path, NOW - timedelta(hours=3), size=12 * 1024)
    n = mb.newest(tmp_path, NOW)
    assert n["taken_at"] == NOW - timedelta(hours=3)
    assert n["age_seconds"] == 3 * 3600 and n["size_bytes"] == 12 * 1024


def test_status_thresholds(paths):
    db, dest = paths
    assert mb.status(db, dest, NOW)["state"] == "nodb"
    make_db(db)
    st = mb.status(db, dest, NOW)
    assert st["state"] == "none" and st["warning"] == "Media backup: none yet"
    p = touch_dump(dest, NOW - timedelta(hours=3), size=12 * 1024)
    st = mb.status(db, dest, NOW)
    assert (st["state"], st["age_text"], st["size_text"], st["warning"]) == ("ok", "3h ago", "12 KB", None)
    p.unlink()
    touch_dump(dest, NOW - timedelta(hours=36))
    assert mb.status(db, dest, NOW)["state"] == "ok"                  # 36 h exactly is not stale yet
    for f in dest.iterdir():
        f.unlink()
    touch_dump(dest, NOW - timedelta(hours=40))
    st = mb.status(db, dest, NOW)
    assert st["state"] == "stale" and st["warning"] == "Media backup: none in 40 hours"
    for f in dest.iterdir():
        f.unlink()
    touch_dump(dest, NOW - timedelta(days=2, hours=1))
    st = mb.status(db, dest, NOW)
    assert st["age_text"] == "2d ago" and st["warning"] == "Media backup: none in 2 days"


def test_status_off_when_dir_unset_or_missing(paths, tmp_path):
    db, _ = paths
    make_db(db)
    st = mb.status(db, "", NOW)
    assert st["state"] == "off" and st["note"] == "no backup folder set"
    st = mb.status(db, tmp_path / "nope", NOW)
    assert st["state"] == "off" and st["note"] == "backup folder missing" and st["warning"] is None


def test_current_status_honours_media_backup_off(paths, monkeypatch):
    db, _ = paths
    make_db(db)
    monkeypatch.setenv("MEDIA_BACKUP", "off")
    st = mb.current_status(NOW)
    assert st["state"] == "off" and st["warning"] is None


# --- run_backup / maybe_backup ------------------------------------------------

def test_run_backup_backs_up_then_prunes(paths):
    db, dest = paths
    make_db(db)
    old = touch_dump(dest, datetime(2023, 1, 1, tzinfo=timezone.utc))
    assert mb.run_backup(NOW) is True
    assert not old.exists() and (dest / dump_name(NOW)).is_file()


def test_run_backup_never_raises_and_does_not_prune_on_failure(paths, monkeypatch):
    db, dest = paths
    make_db(db)
    old = touch_dump(dest, datetime(2023, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(mb, "_integrity", lambda conn: "bad")
    assert mb.run_backup(NOW) is False
    assert old.exists() and [p.name for p in dest.iterdir()] == [old.name]


def test_run_backup_skips_without_db_or_dir(paths, monkeypatch, tmp_path):
    db, dest = paths
    assert mb.run_backup(NOW) is False and list(dest.iterdir()) == []
    make_db(db)
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "missing"))
    assert mb.run_backup(NOW) is False and not (tmp_path / "missing").exists()


def test_maybe_backup_skips_when_recent(paths):
    db, dest = paths
    make_db(db)
    touch_dump(dest, NOW - timedelta(hours=19))
    assert mb.maybe_backup(NOW) is False and len(list(dest.iterdir())) == 1
    assert mb.maybe_backup(NOW + timedelta(hours=2)) is True       # newest now 21 h old
    assert len(list(dest.iterdir())) == 2


# --- hub scheduler ------------------------------------------------------------

@pytest.fixture()
def hub_env(tmp_path, monkeypatch, paths):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "1 of 1 up", "apps": [
        {"id": "j", "name": "Jellyfin", "href": "http://a.invalid", "up": True, "status_text": "Up", "note": None}]})
    import hub.main
    importlib.reload(hub.main)
    return hub.main, paths


def test_scheduler_runs_maybe_backup_and_stops_cleanly(hub_env, monkeypatch):
    main, _ = hub_env
    calls = []
    monkeypatch.setattr(main.tasks, "BACKUP_FIRST_DELAY_S", 0)
    monkeypatch.setattr(main.media_backup, "maybe_backup", lambda: calls.append(1) or True)
    with TestClient(main.app) as client:
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.02)
        assert client.get("/healthz").status_code == 200
    assert calls == [1]


def test_scheduler_survives_a_crashing_backup(hub_env, monkeypatch):
    main, _ = hub_env
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(main.tasks, "BACKUP_FIRST_DELAY_S", 0)
    monkeypatch.setattr(main.media_backup, "maybe_backup", boom)
    with TestClient(main.app) as client:
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.05)
        assert calls and client.get("/healthz").status_code == 200


def test_media_backup_off_starts_no_task(hub_env, monkeypatch):
    main, _ = hub_env
    calls = []
    monkeypatch.setenv("MEDIA_BACKUP", "off")
    monkeypatch.setattr(main.tasks, "BACKUP_FIRST_DELAY_S", 0)
    monkeypatch.setattr(main.media_backup, "maybe_backup", lambda: calls.append(1))
    with TestClient(main.app) as client:
        time.sleep(0.2)
        client.get("/healthz")
    assert calls == []


# --- surfaces -----------------------------------------------------------------


def apps_main(main):
    with TestClient(main.app) as client:
        return main_of(client.get("/media/apps").text)


def test_apps_page_backup_row(hub_env):
    main, (db, dest) = hub_env
    assert "Joey media backup" not in apps_main(main)                 # nodb: nothing
    make_db(db)
    body = apps_main(main)
    assert "Joey media backup" in body and '<span class="st-warn">None yet</span>' in body
    touch_dump(dest, datetime.now(timezone.utc) - timedelta(hours=3, minutes=5), size=12 * 1024)
    body = apps_main(main)
    row = body.split('backuprow">', 1)[1].split("</div>\n</div>", 1)[0]
    assert '<span class="st-good">Backed up</span>' in row and '3h ago<span class="sep"> · </span>12 KB' in row
    assert "is-down" not in body.split("Joey media backup")[0][-400:] and "<a " not in row
    assert body.index("Jellyfin") < body.index("Joey media backup")   # the final row


def test_apps_page_backup_row_stale_and_off(hub_env, monkeypatch, tmp_path):
    main, (db, dest) = hub_env
    make_db(db)
    touch_dump(dest, datetime.now(timezone.utc) - timedelta(days=2, hours=2))
    body = apps_main(main)
    row = body.split('backuprow">', 1)[1].split("</div>\n</div>", 1)[0]
    assert '<span class="st-warn">Stale</span>' in row and "2d ago" in row and 'class="row is-down backuprow"' in body
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "missing"))
    row = apps_main(main).split('backuprow">', 1)[1].split("</div>\n</div>", 1)[0]
    assert '<span>Off</span>' in row and "backup folder missing" in row


def test_warning_only_when_stale_or_none(hub_env, monkeypatch, tmp_path):
    main, (db, dest) = hub_env

    def get(path):
        with TestClient(main.app) as client:
            return client.get(path)

    def pages():
        return main_of(get("/").text), main_of(get("/a/alpha").text)

    for body in pages():                                               # nodb
        assert "Media backup:" not in body
    make_db(db)
    hub, area = pages()                                                # none
    assert '<span class="st-warn">Media backup: none yet</span>' in hub
    assert "Media backup: none yet" in area.split('<p class="metaline">', 1)[1].split("</p>", 1)[0]
    touch_dump(dest, datetime.now(timezone.utc) - timedelta(days=2, hours=1))
    for body in pages():                                               # stale
        assert "Media backup: none in 2 days" in body
    touch_dump(dest, datetime.now(timezone.utc) - timedelta(hours=2))
    for body in pages():                                               # ok: silent
        assert "Media backup:" not in body
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "missing"))
    for path in ("/", "/a/alpha"):                                     # off: renders, no warning
        resp = get(path)
        assert resp.status_code == 200 and "Media backup:" not in main_of(resp.text)
