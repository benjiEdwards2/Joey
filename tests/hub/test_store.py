"""WP18 — snapshot store: crash-proof reads + the four tile states."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hub.registry import Owner, Tier, Tile
from hub.store import get_snapshots, tile_state


def write_envelope(d: Path, connector: str, age_minutes: int = 10, data: dict | None = None,
                   status: str = "ok") -> None:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{connector}.json").write_text(json.dumps({
        "connector": connector, "schema_version": 1,
        "fetched_at": ts, "updated_at": ts, "status": status,
        "consecutive_failures": 0, "error": None,
        "data": data if data is not None else {"summary": "VALUE"},
    }), encoding="utf-8")


def embed_tile(snapshot="open_meteo", stale_after=120, **over) -> Tile:
    kw = dict(id="t", label="T", tier=Tier.embed, owner=Owner.shared,
              snapshot=snapshot, stale_after_minutes=stale_after, setup_note="set me up")
    kw.update(over)
    return Tile(**kw)


def test_missing_dir_returns_empty(tmp_path):
    assert get_snapshots(tmp_path / "nope") == {}


def test_reads_envelope_with_age(tmp_path):
    write_envelope(tmp_path, "open_meteo", age_minutes=30)
    snaps = get_snapshots(tmp_path)
    assert snaps["open_meteo"].status == "ok"
    assert 29 <= snaps["open_meteo"].age_minutes <= 35


def test_malformed_file_treated_as_absent(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "money.json").write_text("{not json", encoding="utf-8")
    write_envelope(tmp_path, "open_meteo")
    snaps = get_snapshots(tmp_path)
    assert "money" not in snaps and "open_meteo" in snaps


def test_state_fresh(tmp_path):
    write_envelope(tmp_path, "open_meteo", age_minutes=12,
                   data={"summary": "18 °C", "secondary": "rain later"})
    st = tile_state(embed_tile(), get_snapshots(tmp_path))
    assert st["state"] == "fresh"
    assert st["value"] == "18 °C"
    assert st["secondary"] == "rain later"
    assert st["age_text"] == "12m ago"


def test_state_stale_in_words(tmp_path):
    write_envelope(tmp_path, "open_meteo", age_minutes=5 * 60)
    st = tile_state(embed_tile(stale_after=120), get_snapshots(tmp_path))
    assert st["state"] == "stale"
    assert st["age_text"] == "stale 5h"
    assert st["value"] == "VALUE"  # last known value still shown


def test_state_not_connected(tmp_path):
    st = tile_state(embed_tile(), get_snapshots(tmp_path / "empty"))
    assert st["state"] == "off"
    assert st["note"] == "set me up"


def test_state_link_never_reads_snapshots():
    t = Tile(id="t", label="Notion", tier=Tier.link, owner=Owner.shared, href="https://x.test")
    st = tile_state(t, {})
    assert st["state"] == "link" and st["href"] == "https://x.test"


# ---- WP-U2 (2026-10-06): _runner_history.jsonl tail reader ----

def write_history(d: Path, sweeps: list, junk: list | None = None) -> Path:
    """Append run_all-shaped lines: each sweep is (minutes_ago, {cid: status | (status, error)})."""
    d.mkdir(parents=True, exist_ok=True)
    path = d / "_runner_history.jsonl"
    now = datetime.now(timezone.utc)
    with path.open("a", encoding="utf-8") as fh:
        for minutes_ago, results in sweeps:
            res = {}
            for cid, r in results.items():
                status, error = r if isinstance(r, tuple) else (r, None)
                res[cid] = {"status": status, "consecutive_failures": 0, "error": error}
            fh.write(json.dumps({"ran_at": (now - timedelta(minutes=minutes_ago)).isoformat(),
                                 "results": res}) + "\n")
        for line in junk or []:
            fh.write(line + "\n")
    return path


def test_runner_history_reads_the_tail_and_skips_junk(tmp_path):
    from hub.store import get_runner_history
    assert get_runner_history(tmp_path) is None                      # missing file
    write_history(tmp_path, [(m, {"wud": "ok"}) for m in range(30, 0, -1)], junk=["{nope", "[]"])
    rows = get_runner_history(tmp_path)
    assert len(rows) == 30 and all(r["results"]["wud"]["status"] == "ok" for r in rows)
    assert len(get_runner_history(tmp_path, max_lines=5)) == 5
    tail = get_runner_history(tmp_path, max_bytes=400)               # cut mid-line: partial dropped
    assert tail and all("ran_at" in r for r in tail) and len(tail) < 30


def test_heartbeat_files_are_skipped_without_a_warning(tmp_path, caplog):
    """_runner.json / _runner_history.jsonl are not envelopes; they used to log an
    'unreadable' warning on every read (2026-10-06)."""
    import logging
    from hub import store
    (tmp_path / "_runner.json").write_text('{"ran_at": "x", "results": []}', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="hub.store"):
        assert store.get_snapshots(tmp_path) == {}
    assert "unreadable" not in caplog.text


def _age_file(path, seconds_ago=60):
    import os
    import time
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def test_envelopes_are_parsed_once_per_file_version(tmp_path, monkeypatch):
    """H-48: an unchanged file is not re-parsed; age is still recomputed per call; a changed file is re-read."""
    import os

    import hub.store as store
    write_envelope(tmp_path, "open_meteo", age_minutes=30)
    write_envelope(tmp_path, "jellyfin", age_minutes=5)
    for name in ("open_meteo.json", "jellyfin.json"):
        _age_file(tmp_path / name)
    parsed, real = [], store._parse
    monkeypatch.setattr(store, "_parse", lambda p: parsed.append(p.name) or real(p))
    first, second = get_snapshots(tmp_path), get_snapshots(tmp_path)
    assert sorted(parsed) == ["jellyfin.json", "open_meteo.json"]
    assert second["open_meteo"] is not first["open_meteo"] and second["open_meteo"].age_minutes >= first["open_meteo"].age_minutes
    # same size, new mtime -> re-read
    path = tmp_path / "open_meteo.json"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    _age_file(path, 30)
    get_snapshots(tmp_path)
    assert parsed.count("open_meteo.json") == 2 and parsed.count("jellyfin.json") == 1
    (tmp_path / "jellyfin.json").unlink()
    assert set(get_snapshots(tmp_path)) == {"open_meteo"}


def test_a_just_written_file_is_always_re_read(tmp_path, monkeypatch):
    """Coarse-mtime filesystems: a file changed within the last second never comes from the cache."""
    import hub.store as store
    parsed, real = [], store._parse
    monkeypatch.setattr(store, "_parse", lambda p: parsed.append(p.name) or real(p))
    write_envelope(tmp_path, "gcal", age_minutes=1, data={"summary": "A"})
    assert get_snapshots(tmp_path)["gcal"].data["summary"] == "A"
    write_envelope(tmp_path, "gcal", age_minutes=1, data={"summary": "B"})   # same size, same second
    assert get_snapshots(tmp_path)["gcal"].data["summary"] == "B"
    assert parsed == ["gcal.json", "gcal.json"]


def test_parse_utc_accepts_z_fractions_and_naive():
    from datetime import datetime, timezone

    from hub.store import parse_utc
    assert parse_utc("2026-10-08T01:02:03.1234567Z") == datetime(2026, 10, 8, 1, 2, 3, 123456, tzinfo=timezone.utc)
    assert parse_utc("2026-10-08T01:02:03").tzinfo == timezone.utc
    assert parse_utc("nope") is None and parse_utc(None) is None
