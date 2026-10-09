"""/weather rain radar panel + the radar file route.

RADAR SUPERSESSION (2026-10-07, DECISIONS.md): the page's radar is now a Windy embed
iframe; the BOM layer-stack page assertions (2026-10-06) were replaced by the Windy-embed
assertions below — a deliberate feature replacement, not a weakening. The BOM file route
stays (parked, still tested); the connector's BOM fetch is gated behind RADAR_LOOP=1.
"""
import html as htmllib
import re

import pytest

from tests.hub.test_store import write_envelope
from tests.hub.test_weather import WX_DATA, app_factory  # noqa: F401  (fixture re-export)

PNG = b"\x89PNG\r\n\x1a\nfake"
STAMPS = ["202610060029", "202610060034", "202610060039", "202610060044",
          "202610060049", "202610060054"]
LAYERS = ["layer_background.png", "layer_topography.png", "layer_locations.png", "layer_range.png"]


def _radar(stamps=STAMPS, fetched_ok=True, layers=LAYERS):
    return {"station": "IDR023", "fetched_ok": fetched_ok, "layers": list(layers),
            "frames": [{"file": f"frame_{s}.png",
                        "time_iso": f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:]}:00+00:00"}
                       for s in stamps]}


def _setup(tmp_path, data, files=()):
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=5, data=data)
    (snaps / "radar").mkdir(parents=True, exist_ok=True)
    for name in files:
        (snaps / "radar" / name).write_bytes(PNG)
    return snaps


def _page(app_factory, data, files=()):
    build, tmp_path = app_factory
    with build(_setup(tmp_path, data, files)) as client:
        r = client.get("/weather")
        assert r.status_code == 200
        return r.text


# ---- page: Windy embed (2026-10-07) ------------------------------------------------


def _windy_src(page):
    panel = page.split('class="sec wxradar"')[1].split("</section>")[0]
    m = re.search(r'<iframe class="wxwindy" src="([^"]+)"', panel)
    assert m, "Windy iframe missing"
    return panel, htmllib.unescape(m.group(1))


@pytest.fixture()
def coords(monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "-37.84")
    monkeypatch.setenv("WEATHER_LON", "144.88")


def test_radar_panel_is_a_windy_embed_with_the_home_coords(app_factory, coords):
    page = _page(app_factory, {**WX_DATA, "radar": _radar()})
    panel, src = _windy_src(page)
    assert src.startswith("https://embed.windy.com/embed2.html?")
    for part in ("lat=-37.84", "lon=144.88", "overlay=radar", "zoom=8", "metricTemp=%C2%B0C",
                 "metricWind=km%2Fh", "detectRotation=false"):
        assert part in src.split("?", 1)[1].split("&"), part
    assert 'title="Interactive rain radar map' in panel and 'loading="lazy"' in panel
    assert "Interactive radar · windy.com · needs internet" in panel
    # the BOM layer stack is gone from the page, and the page itself runs no script for it
    assert "wxrframe" not in page and "/weather/radar/" not in page and "<script" not in panel


def test_windy_coords_follow_the_weather_env(app_factory, monkeypatch):
    monkeypatch.setenv("WEATHER_LAT", "-33.87")
    monkeypatch.setenv("WEATHER_LON", "151.21")
    _, src = _windy_src(_page(app_factory, WX_DATA))
    assert "lat=-33.87&lon=151.21&detailLat=-33.87&detailLon=151.21" in src


@pytest.mark.parametrize("lat,lon", [(None, None), ("x", "144.88"), ("-137", "144.88")])
def test_windy_falls_back_to_newport_when_env_missing_or_bad(app_factory, monkeypatch, lat, lon):
    for k, v in (("WEATHER_LAT", lat), ("WEATHER_LON", lon)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    _, src = _windy_src(_page(app_factory, WX_DATA))
    assert "lat=-37.84&lon=144.88" in src


def test_windy_panel_renders_when_the_weather_snapshot_is_absent(app_factory, coords):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/weather")
    assert r.status_code == 200 and "Not connected" in r.text
    _, src = _windy_src(r.text)
    assert "lat=-37.84" in src


def test_windy_iframe_css_keeps_the_square_capped_slot():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    rule = css.split(".wxwindy {")[1].split("}")[0]
    assert "aspect-ratio: 1" in rule and "min(100%, 78vh)" in rule and "border: 0" in rule


def test_parked_bom_css_is_gone_and_the_page_gets_no_radar_context(app_factory):
    """H-05/H-12 (2026-10-09): the BOM loop's CSS and its per-request context are dropped; route + connector stay."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert ".wxradarbox" not in css and ".wxlegend" not in css and "@keyframes wxr" not in css and "--rad-" not in css
    build, tmp_path = app_factory
    snaps = _setup(tmp_path, {**WX_DATA, "radar": _radar()}, files=LAYERS + [f"frame_{s}.png" for s in STAMPS])
    import hub.main
    seen = {}
    real = hub.main.templates.TemplateResponse
    with build(snaps) as client:
        hub.main.templates.TemplateResponse = lambda req, name, ctx=None, *a, **k: (
            seen.setdefault(name, set(ctx or {})), real(req, name, ctx, *a, **k))[1]
        try:
            assert client.get("/weather").status_code == 200
        finally:
            del hub.main.templates.TemplateResponse
    assert "radar" not in seen["weather.html"]


# ---- file route --------------------------------------------------------------------


def test_route_serves_stored_pngs(app_factory):
    build, tmp_path = app_factory
    snaps = _setup(tmp_path, {**WX_DATA, "radar": _radar()},
                   files=LAYERS + [f"frame_{s}.png" for s in STAMPS])
    with build(snaps) as client:
        r = client.get("/weather/radar/frame_202610060054.png")
        assert r.status_code == 200 and r.content == PNG
        assert r.headers["content-type"] == "image/png"
        assert "immutable" in r.headers["cache-control"]
        r = client.get("/weather/radar/layer_range.png")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_route_rejects_traversal_unknown_and_missing_names(app_factory):
    build, tmp_path = app_factory
    snaps = _setup(tmp_path, WX_DATA, files=["frame_202610060054.png", "secret.png"])
    (snaps / "radar" / ".frame_202610060054.png.1.2.tmp").write_bytes(PNG)
    with build(snaps) as client:
        for bad in ("..%2Fopen_meteo.json", "../open_meteo.json", "%2e%2e%2fopen_meteo.json",
                    "secret.png", "layer_roads.png", "frame_2026.png", "frame_202610060054.png.tmp",
                    ".frame_202610060054.png.1.2.tmp", "frame_202610060059.png",
                    "..%5Copen_meteo.json"):
            r = client.get(f"/weather/radar/{bad}")
            assert r.status_code == 404, bad
            assert b"connector" not in r.content, bad
