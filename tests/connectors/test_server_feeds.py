"""Server area feeds (WP-S1, 2026-10-06): `system` and `wud` stub transforms.
The live fetches arrive in WP-S2 / WP-S3; until then a live run is an error envelope
(data kept), never a crash."""

import json
from pathlib import Path

import jsonschema

from connectors.stubs import System, Wud

SCHEMAS = Path(__file__).resolve().parents[2] / "connectors" / "schema" / "data"


def schema(cid):
    return json.loads((SCHEMAS / f"{cid}.schema.json").read_text(encoding="utf-8"))


def test_system_fixture_transform(snapshots):
    data = System().run()["data"]
    jsonschema.validate(data, schema("system"))
    assert data["cpu_pct"] == 16.2 and data["load_1m"] == 0.42
    assert (data["ram_free_gb"], data["ram_total_gb"], data["ram_pct_used"]) == (1.9, 7.7, 75)
    assert data["uptime_s"] == 1052400
    assert [v["path"] for v in data["volumes"]] == ["/volume1", "/volume2", "/volume1/Docker"]
    assert [v["pct_used"] for v in data["volumes"]] == [71, 66, 74]
    assert data["summary"] == "CPU 16% · 1.9 GB RAM free"
    assert data["secondary"] == "Up 12 days · /volume1/Docker 74% used"


def test_system_transform_tolerates_missing_load_and_volumes():
    data = System().transform({"cpu_pct": 3, "mem_total_bytes": 0, "mem_available_bytes": 0,
                               "uptime_s": 125})
    jsonschema.validate(data, schema("system"))
    assert data["load_1m"] is None and data["volumes"] == [] and data["ram_pct_used"] == 0
    assert data["secondary"] == "Up 2 min"


def test_wud_fixture_transform(snapshots):
    data = Wud().run()["data"]
    jsonschema.validate(data, schema("wud"))
    assert (data["monitoring"], data["updates"]) == (17, 2)  # + vaultwarden digest (WP-S3)
    first = data["containers"][0]
    assert first == {"name": "uptime-kuma", "image": "louislam/uptime-kuma", "current_tag": "1.23.16",
                     "new_tag": "2.0.2", "update_available": True, "kind": "tag"}
    assert data["containers"][1] == {"name": "vaultwarden", "image": "vaultwarden/server",
                                     "current_tag": "latest", "new_tag": None,
                                     "update_available": True, "kind": "digest"}
    assert all(c["kind"] is None and c["new_tag"] is None for c in data["containers"][2:])
    assert data["summary"] == "2 updates available"
    assert data["secondary"] == "uptime-kuma 1.23.16 → 2.0.2 (+1 more)"


def test_wud_digest_update_has_no_new_tag_and_empty_list_is_all_up_to_date():
    digest = Wud().transform([{"name": "nginx", "image": {"name": "nginx", "tag": {"value": "alpine"}},
                               "updateAvailable": True, "updateKind": {"kind": "digest"},
                               "result": {"tag": "alpine"}}])
    jsonschema.validate(digest, schema("wud"))
    assert digest["containers"][0]["kind"] == "digest" and digest["containers"][0]["new_tag"] is None
    assert digest["secondary"] == "nginx new image digest"
    empty = Wud().transform([])
    assert (empty["summary"], empty["monitoring"], empty["updates"]) == ("All up to date", 0, 0)


def test_live_run_without_a_fetch_is_an_error_envelope_not_a_crash(snapshots, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "live")
    env = System().run()
    assert env["status"] == "error" and "NotImplementedError" in env["error"]
    # Wud has a live fetch since WP-S3: without its env it fails fast, still never a crash
    for var in Wud.requires_env:
        monkeypatch.delenv(var, raising=False)
    env = Wud().run()
    assert env["status"] == "error" and "WUD_URL" in env["error"]
