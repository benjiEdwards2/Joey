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
