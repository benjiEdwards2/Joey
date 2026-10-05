"""WP20 — Control Surface port: weighted bento sizes + cockpit chrome."""
import importlib

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.test_registry import AREAS_YAML, make_area, write_registry
from tests.hub.test_store import write_envelope


def test_real_registry_hub_sizes():
    reg = load_registry(AREAS_YAML)
    sizes = {a.id: a.hub_size.value for a in reg.areas}
    assert sizes["money"] == "s22"      # second hero beside Media (B., 2026-10-06)
    assert sizes["media"] == "s22"      # bento hero
    assert sizes["calendar"] == "s21"   # double width
    assert sizes["kitchen"] == "s11"    # default


def test_invalid_hub_size_rejected(tmp_path):
    bad = make_area("a1")
    bad["hub_size"] = "huge"
    with pytest.raises(ValueError, match="hub_size"):
        load_registry(write_registry(tmp_path, bad))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    a1 = make_area("alpha", "a-t")
    a1["hub_size"] = "s22"
    fixture = write_registry(tmp_path, a1, make_area("beta", "b-t", snapshot="jellyfin"))
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=10 * 60)  # stale vs 60-min default
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def test_hub_card_carries_size_class(client):
    # Apex hub (2026-10-06): hub_size no longer drives the hub layout (KPI row in registry /
    # hub_rank order), so this pin is weakened to "one KPI card per area" — size classes gone.
    html = client.get("/").text.split("<main", 1)[1]
    assert '<a class="cardlink" href="/a/alpha">' in html
    assert '<a class="cardlink" href="/a/beta">' in html
    assert "cardlink s22" not in html and "cardlink s11" not in html


def test_status_strip_reports_feeds_and_stale(client):
    html = client.get("/").text
    assert "FEEDS" in html and "1/2" in html      # open_meteo present, jellyfin absent
    assert "stale" in html                        # stale feed named in the strip


def test_phone_nav_first_three_plus_more_sheet(client):
    html = client.get("/").text
    assert html.count('nav class="tabs"') == 1
    assert "<details" in html and "More" in html  # 4 slots + More disclosure, no JS
