"""WP17 — FastAPI skeleton: routing rendered from the registry.

Runs against a 2-area fixture yaml to prove the hub is registry-driven,
not hardcoded to the 8 real areas.
"""
import importlib

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, write_registry

IDENTITY_HEADER = "Cf-Access-Authenticated-User-Email"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fixture = write_registry(
        tmp_path,
        make_area("alpha", "alpha-t"),
        make_area("beta", "beta-t", tier="link", href="https://example.test",
                  snapshot=None, stale_after_minutes=None),
    )
    monkeypatch.setenv("AREAS_PATH", str(fixture))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:   # context manager runs startup
        yield c


def test_hub_page_lists_fixture_areas_in_order(client):
    html = client.get("/").text
    assert "Alpha" in html and "Beta" in html
    assert html.index("Alpha") < html.index("Beta")


def test_each_area_page_renders(client):
    for aid in ("alpha", "beta"):
        r = client.get(f"/a/{aid}")
        assert r.status_code == 200
        assert aid.title() in r.text


def test_link_tile_renders_href(client):
    assert 'href="https://example.test"' in client.get("/a/beta").text


def test_unknown_area_is_styled_404(client):
    r = client.get("/a/pool")
    assert r.status_code == 404
    assert "No page here" in r.text and "Back to Hub" in r.text   # one 404 wording, with a way back
    assert "Alpha" in r.text           # tab bar still rendered


def test_healthz_reports_fixture_area_count(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["areas"] == 2
    assert body["registry_loaded_at"]


def test_whoami_echoes_identity_header(client):
    assert client.get("/whoami", headers={IDENTITY_HEADER: "b@example.test"}).json() == {
        "email": "b@example.test"}


def test_whoami_dash_without_header(client):
    assert client.get("/whoami").json() == {"email": "-"}


def test_invalid_registry_fails_startup(tmp_path, monkeypatch):
    bad = tmp_path / "areas.yaml"
    bad.write_text(yaml.safe_dump({"areas": [
        {"id": "x", "name": "X", "icon": "x",
         "summary_tile": "ghost", "tiles": [
             {"id": "t", "label": "T", "tier": "embed", "owner": "shared"}]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(bad))
    import hub.main
    importlib.reload(hub.main)
    with pytest.raises(ValueError, match="violation"):
        with TestClient(hub.main.app):
            pass
