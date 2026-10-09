"""Hub chrome on a synthetic registry: one KPI card per area (no size classes), the feeds line and the phone tab bar.
(WP20's weighted bento sizes — `hub_size` — were removed 2026-10-09, T3 H-01: nothing had read them since the Apex hub.)"""
import importlib
import re

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.helpers import AREAS_YAML, make_area, write_envelope, write_registry


def test_real_registry_has_no_hub_size_key():
    reg = load_registry(AREAS_YAML)
    assert all("hub_size" not in a.model_dump() for a in reg.areas)
    assert "hub_size" not in AREAS_YAML.read_text(encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fixture = write_registry(tmp_path, make_area("alpha", "a-t"), make_area("beta", "b-t", snapshot="jellyfin"))
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=10 * 60)  # stale vs 60-min default
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def test_one_kpi_card_per_area_without_size_classes(client):
    # Apex hub (2026-10-06): the KPI row is in registry / hub_rank order — one card per area, no size classes.
    html = client.get("/").text.split("<main", 1)[1]
    # the last of <= 3 cards carries `span2` (kpis few, 2026-10-06)
    assert re.search(r'<a class="panel tile" href="/a/alpha"', html)
    assert re.search(r'<a class="panel tile( span2)?" href="/a/beta"', html)
    assert "cardlink" not in html and "tile s22" not in html and "tile s11" not in html


def test_status_strip_reports_feeds_and_stale(client):
    html = client.get("/").text
    assert "Feeds 1/2 live" in html               # open_meteo present, jellyfin absent
    assert "stale" in html                        # stale feed named in the strip


def test_phone_tab_bar_holds_every_section_when_five_or_fewer(client):
    html = client.get("/").text
    assert html.count('nav class="tabbar"') == 1
    bar = html.split('nav class="tabbar"', 1)[1]
    assert bar.count("<a href=") == 4 and "<details" not in bar  # Hub, Weather, Alpha, Beta; More only past five
