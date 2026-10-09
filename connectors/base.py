"""base.Connector — the one contract every feed obeys (WP22).

Rules, all of them from DECISIONS.md:
  * The envelope schema is FROZEN (D13). This module consumes it, never edits it.
  * A run NEVER raises. Success writes a fresh envelope; failure re-writes one
    that keeps the previous `data` and `updated_at` byte-for-byte, flips status
    to error, bumps consecutive_failures and refreshes fetched_at only.
  * Writes are atomic: dump to `<path>.tmp`, then os.replace.
  * CONNECTOR_MODE=fixture reads canned bytes off disk, touches no network, and
    PINS both timestamps to FIXTURE_TIMESTAMP so snapshots are byte-reproducible.
  * CONNECTOR_MODE=live (the box default) fails fast naming the exact missing
    environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("connectors")

SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT_DIR = "/data/snapshots"

# Pinned fixture clock — makes fixture-mode output byte-reproducible (WP22 step 4,
# relied on by WP23's committed config/sample_snapshots/).
FIXTURE_TIMESTAMP = "2026-01-01T00:00:00+00:00"

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def snapshot_dir() -> Path:
    return Path(os.environ.get("SNAPSHOT_DIR", DEFAULT_SNAPSHOT_DIR))


def mode() -> str:
    """'fixture' or 'live'. Live is the box default — fixture must be asked for."""
    return os.environ.get("CONNECTOR_MODE", "live").strip().lower()


DEFAULT_HOME_TZ = "Australia/Melbourne"  # the hub's HOME_TZ_NAME (hub/main.py)


def home_tz():
    """The household's zone for "today" / "this week" / "on this day" (C-08): `TZ`, else
    Australia/Melbourne (always the default in fixture mode, so samples never depend on the
    machine); UTC if zoneinfo cannot load either."""
    from zoneinfo import ZoneInfo

    names = (DEFAULT_HOME_TZ,) if mode() == "fixture" else (os.environ.get("TZ"), DEFAULT_HOME_TZ)
    for name in names:
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except Exception:  # unknown name, or no tz database in the image
            continue
    return timezone.utc


def _now_iso() -> str:
    if mode() == "fixture":
        return FIXTURE_TIMESTAMP
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_URL_RE = re.compile(r"https?://\S+")


def mask_urls(text: str) -> str:
    """Defence in depth (C-06): no URL — with its host, query or token — reaches an
    envelope, `_runner.json`, the history or the log, even from an unwrapped call."""
    return _URL_RE.sub("<url>", text)


def partial_note(data: dict[str, Any], source: str, reason: str) -> dict[str, Any]:
    """The one partial-failure convention (C-10): the feed is ok but `source` failed this
    sweep, so `data["partial_errors"][source] = reason` (type/status only, never a URL).
    Additive — feeds keep their older keys (gcal `feed_errors`, arr `app_errors`)."""
    data.setdefault("partial_errors", {})[source] = reason
    return data


class MissingCredential(RuntimeError):
    """Live mode started without an env var the connector needs."""


class Connector:
    """Subclass and supply `id`, `fetch()` and `transform(raw)`."""

    id: str = ""
    # Env vars that must be set before a LIVE fetch is even attempted.
    requires_env: tuple[str, ...] = ()

    # ---- the two methods subclasses implement -------------------------------

    def fetch(self) -> Any:
        """Live fetch. Never called in fixture mode."""
        raise NotImplementedError

    def transform(self, raw: Any) -> dict[str, Any]:
        """Raw payload -> the envelope's `data` block."""
        raise NotImplementedError

    # ---- fixture side -------------------------------------------------------

    @property
    def fixture_dir(self) -> Path:
        return FIXTURES_DIR / self.id

    def fetch_fixture(self) -> Any:
        """Read `fixtures/{id}/raw.*` with zero network.

        One `raw.*` file -> its parsed content. Several (gcal, jellyfin) -> a
        dict keyed by file stem, e.g. {'raw_you': ..., 'raw_her': ...}.
        """
        files = sorted(p for p in self.fixture_dir.glob("raw*") if p.is_file())
        if not files:
            raise FileNotFoundError(f"no fixture for {self.id} in {self.fixture_dir}")
        if len(files) == 1:
            return _read_fixture(files[0])
        return {p.stem: _read_fixture(p) for p in files}

    # ---- the run wrapper ----------------------------------------------------

    def _check_credentials(self) -> None:
        missing = [v for v in self.requires_env if not os.environ.get(v)]
        if missing:
            raise MissingCredential(
                f"{self.id}: missing environment variable {missing[0]}"
                + (f" (also {', '.join(missing[1:])})" if len(missing) > 1 else "")
            )

    def path(self) -> Path:
        return snapshot_dir() / f"{self.id}.json"

    def _previous(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.path().read_text(encoding="utf-8"))
        except Exception:
            return None

    def run(self) -> dict[str, Any]:
        """Fetch, transform, write. Returns the envelope written. Never raises."""
        now = _now_iso()
        previous = self._previous()
        try:
            if mode() == "fixture":
                raw = self.fetch_fixture()
            else:
                self._check_credentials()
                raw = self.fetch()
            data = self.transform(raw)
            envelope = {
                "connector": self.id,
                "schema_version": SCHEMA_VERSION,
                "fetched_at": now,
                "updated_at": now,
                "status": "ok",
                "consecutive_failures": 0,
                "error": None,
                "data": data,
            }
        except Exception as exc:  # a connector failure is data, not a crash
            reason = mask_urls(f"{type(exc).__name__}: {exc}")
            log.warning("%s failed: %s", self.id, reason)
            envelope = {
                "connector": self.id,
                "schema_version": SCHEMA_VERSION,
                "fetched_at": now,
                # last SUCCESS is preserved exactly — the stale badge reads it
                "updated_at": (previous or {}).get("updated_at", now),
                "status": "error",
                "consecutive_failures": int((previous or {}).get("consecutive_failures", 0)) + 1,
                "error": reason,
                "data": (previous or {}).get("data", {}),
            }
        write_envelope(self.path(), envelope)
        return envelope


def _read_fixture(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else text


def write_envelope(path: Path, envelope: dict[str, Any]) -> None:
    """Atomic write — a reader never sees a half-written snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # tmp name is unique per writer so two concurrent runs can't share a buffer
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    replace_with_retry(tmp, path)


def replace_with_retry(tmp: Path, path: Path) -> None:
    """os.replace(tmp, path), removing tmp if it finally fails."""
    # os.replace is atomic on both POSIX and Windows, but Windows refuses while
    # a reader holds the destination open — retry briefly rather than fail a run.
    attempts = 60
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(min(0.005 * (attempt + 1), 0.1))
