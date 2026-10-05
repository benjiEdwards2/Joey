"""Make the repo root importable so tests can `import hub.*` from anywhere."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import pytest


@pytest.fixture(autouse=True)
def _isolated_media_paths(tmp_path, monkeypatch):
    """Every test gets its own media.db / backup dir / snapshot dir unless it sets them
    itself (2026-10-06): the defaults are absolute /data/... paths, which on Windows
    resolve to C:\data\... — a test that touched the DB without MEDIA_DB_PATH created a
    real file there and flipped the apps page's backup row for every later test."""
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "isolated-media.db"))
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "isolated-backups"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "isolated-snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    monkeypatch.setenv("MEDIA_BACKUP", "off")
