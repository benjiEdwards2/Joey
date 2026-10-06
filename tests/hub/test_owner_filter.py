"""WP19 — owner switcher: Both / You / Her (Q9 semantics), cookie-persisted.

Works as plain links (no-JS path) — the htmx fragment swap is a progressive
enhancement layered on the same endpoints.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """One area holding a you-tile, a her-tile, and a shared tile (the summary)."""
    area = make_area("mixed", "shared-t")
    area["tiles"] = [
        make_tile("shared-t", snapshot="money", stale_after_minutes=120),  # money, not open_meteo: the weather tile is dropped beside the weather band (2026-10-06)
        make_tile("you-t", owner="you", snapshot="jellyfin", stale_after_minutes=120),
        make_tile("her-t", owner="her", snapshot="gcal", stale_after_minutes=120),
    ]
    her_area = make_area("hers", "hers-t", owner="her", snapshot="nas_stats")
    fixture = write_registry(tmp_path, area, her_area)
    monkeypatch.setenv("AREAS_PATH", str(fixture))

    snaps = tmp_path / "snaps"
    write_envelope(snaps, "money", data={"summary": "SHARED-VAL"})
    write_envelope(snaps, "jellyfin", data={"summary": "YOU-VAL"})
    write_envelope(snaps, "gcal", data={"summary": "HER-VAL"})
    write_envelope(snaps, "nas_stats", data={"summary": "HERS-CARD"})
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def test_both_shows_everything(client):
    html = client.get("/a/mixed?owner_view=both").text
    assert "SHARED-VAL" in html and "YOU-VAL" in html and "HER-VAL" in html


def test_you_view_keeps_shared_drops_her(client):
    html = client.get("/a/mixed?owner_view=you").text
    assert "SHARED-VAL" in html and "YOU-VAL" in html
    assert "HER-VAL" not in html


def test_her_view_keeps_shared_drops_you(client):
    html = client.get("/a/mixed?owner_view=her").text
    assert "SHARED-VAL" in html and "HER-VAL" in html
    assert "YOU-VAL" not in html


def test_hub_summary_cards_respect_filter(client):
    """'hers' area's summary tile is her-owned: gone in you-view (Q24 assumption)."""
    both = client.get("/?owner_view=both").text
    you = client.get("/?owner_view=you").text
    assert "HERS-CARD" in both
    assert "HERS-CARD" not in you     # her-owned summary card gone from the grid
    assert "Hers" in you              # ...but the area stays in the tab bar
    assert "SHARED-VAL" in you        # shared summary stays


def test_cookie_set_and_honoured_across_requests(client):
    r = client.get("/a/mixed?owner_view=you")
    assert client.cookies.get("owner_view") == "you"
    html = client.get("/a/mixed").text            # no query param this time
    assert "HER-VAL" not in html                  # cookie applied
    html = client.get("/a/mixed?owner_view=both").text
    assert "HER-VAL" in html                      # switching back restores


def test_invalid_view_falls_back_to_both(client):
    html = client.get("/a/mixed?owner_view=aliens").text
    assert "SHARED-VAL" in html and "YOU-VAL" in html and "HER-VAL" in html


def test_switcher_links_render_plain_hrefs(client):
    """2026-10-06: the Both/You/Her links are gone (the signed-in user picks the view);
    without the Access header the plain ?owner_view= query still switches the view."""
    html = client.get("/a/mixed").text
    assert 'class="switcher"' not in html and "owner_view=" not in html
    assert "HER-VAL" not in client.get("/a/mixed?owner_view=you").text
