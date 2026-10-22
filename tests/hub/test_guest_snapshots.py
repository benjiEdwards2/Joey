"""Joey TV WP-B1 (2026-10-21, Q22 (c), Q20): on the media front every request reads snapshots through ONE scrub point
(hub.shell.get_snapshots): only jellyfin / jellyseerr / arr survive, each reduced to a key allow-list, rows without
B.'s played state or the requester's name. The AST pins keep it the only reader on a request path."""
import ast
import importlib
import json
from pathlib import Path

import pytest

from hub import guest, shell

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "config" / "sample_snapshots"
FORBIDDEN_IDS = {"qbittorrent", "media_status", "system", "wud", "uptime_kuma", "gcal", "open_meteo",
                 "home_assistant", "macromates", "nas_stats"}


def raw(cid: str) -> dict:
    return json.loads((SAMPLES / f"{cid}.json").read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def samples(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DIR", str(SAMPLES))


def test_snapshot_allowlist(samples, monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    snaps = shell.get_snapshots()
    assert set(snaps) == {"jellyfin", "jellyseerr", "arr"}
    assert not set(snaps) & FORBIDDEN_IDS
    for cid, snap in snaps.items():
        assert set(snap.data) == guest.SNAPSHOT_KEYS[cid] & set(raw(cid)), cid
        assert set(snap.data) <= guest.SNAPSHOT_KEYS[cid], cid
    jf = snaps["jellyfin"].data
    assert set(jf) == {"latest", "library", "movies", "shows", "server_id", "summary"}   # sample has no library_fetched_at
    for key in ("movies", "shows", "latest"):
        assert jf[key] and not [r for r in jf[key] if {"played", "last_played_at", "unplayed"} & set(r)], key
    assert all("title" in r for r in jf["movies"])
    requests = snaps["jellyseerr"].data["requests"]
    assert requests and not [r for r in requests if "requested_by" in r]
    arr = snaps["arr"].data
    assert set(arr) == {"arrived", "this_week", "updated", "radarr", "sonarr"}
    assert set(arr["radarr"]) == {"movies", "missing", "wanted"} and set(arr["sonarr"]) == {"series", "wanted"}


def test_scrubbed_data_carries_no_household_names(samples, monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    text = json.dumps({cid: s.data for cid, s in shell.get_snapshots().items()})
    for name in {r.get("user") for r in raw("jellyfin")["now_playing"]} | {r["requested_by"] for r in raw("jellyseerr")["requests"]}:
        assert name and f'"{name}"' not in text


def test_private_front_is_unchanged_and_the_cache_untouched(samples, monkeypatch):
    monkeypatch.setenv("JOEY_FRONT", "media")
    shell.get_snapshots()   # a media read first: it must not mutate hub.store's cached envelopes
    monkeypatch.delenv("JOEY_FRONT")
    snaps = shell.get_snapshots()
    assert {"qbittorrent", "gcal", "system"} <= set(snaps)
    jf = snaps["jellyfin"].data
    assert "now_playing" in jf and "her" in jf
    assert any("played" in r for r in jf["movies"])
    assert any("requested_by" in r for r in snaps["jellyseerr"].data["requests"])


def test_unknown_envelope_and_bad_data_scrub_to_nothing():
    assert guest.scrub_data("gcal", {"events": []}) == {}
    assert guest.scrub_data("jellyfin", ["not", "a", "dict"]) == {}
    assert guest.scrub_data("arr", {"radarr": "junk"}) == {"radarr": {}}


# ---- one reader ----

def _store_get_snapshots_importers(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "hub.store" and \
                any(a.name == "get_snapshots" for a in node.names):
            return True
        if isinstance(node, ast.Attribute) and node.attr == "get_snapshots" and \
                isinstance(node.value, (ast.Name, ast.Attribute)) and ast.unparse(node.value) in ("store", "hub.store"):
            return True
    return False


def test_only_known_modules_read_hub_store_get_snapshots():
    readers = {p.name for p in (REPO_ROOT / "hub").glob("*.py") if _store_get_snapshots_importers(p)}
    # shell.py IS the scrub point. The others are lifespan-loop modules (server_digest.py: P2, 2026-10-22 - its tick runs on the hub loop only): the media front starts zero loops
    # (hub.tasks.lifespan, Q24), so none of them reads on joey-media.
    assert readers == {"shell.py", "media_warmup.py", "tasks.py", "server_alerts.py", "server_history.py",
                       "server_digest.py"}


def test_no_endpoint_module_reads_hub_store_directly():
    import hub.main
    importlib.reload(hub.main)

    def endpoints(routes):
        for r in routes:
            original = getattr(r, "original_router", None)
            if original is not None:
                yield from endpoints(original.routes)
            elif getattr(r, "endpoint", None) is not None:
                yield r.endpoint

    modules = {e.__module__ for e in endpoints(hub.main.app.routes) if e.__module__.startswith("hub.")}
    assert {"hub.main", "hub.media_pages", "hub.media_film", "hub.images"} <= modules
    offenders = [m for m in sorted(modules)
                 if _store_get_snapshots_importers(REPO_ROOT / (m.replace(".", "/") + ".py"))]
    assert offenders == []
