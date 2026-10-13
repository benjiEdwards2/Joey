"""Make the repo root importable so tests can `import hub.*` from anywhere."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import pytest


def _reset_media_readers():
    """E1 (2026-10-13): hub.media_store keeps one reader connection per thread; close them all so a test's media.db is
    never read through the previous test's connection (and Windows can delete the temp file). Only when the hub is
    loaded - the connector tests never import it."""
    store = sys.modules.get("hub.media_store")
    if store is not None:
        store.reset()


@pytest.fixture(autouse=True)
def _isolated_media_paths(tmp_path, monkeypatch):
    r"""Every test gets its own media.db / backup dir / snapshot dir unless it sets them
    itself (2026-10-06): the defaults are absolute /data/... paths, which on Windows
    resolve to C:\data\... — a test that touched the DB without MEDIA_DB_PATH created a
    real file there and flipped the apps page's backup row for every later test."""
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "isolated-media.db"))
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "isolated-backups"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "isolated-snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    monkeypatch.setenv("MEDIA_BACKUP", "off")
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "isolated-meta"))  # media-speed: long Jellyseerr cache
    monkeypatch.setenv("MEDIA_WARMUP", "off")  # media-speed: no background warm-up thread in tests
    monkeypatch.delenv("OMDB_API_KEY", raising=False)  # media-ux4: no Metacritic lookups unless a test sets a key
    monkeypatch.setenv("MEDIA_AWARDS", "off")  # Awards: no background awards loop in tests
    monkeypatch.delenv("AWARDS_CONTACT", raising=False)  # Awards: without a contact the sync never calls out
    _reset_media_readers()
    yield
    _reset_media_readers()
