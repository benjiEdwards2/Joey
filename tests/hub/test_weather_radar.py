"""/weather rain radar panel + the radar file route (2026-10-06).

The open_meteo connector stores BOM PNGs under SNAPSHOT_DIR/radar/ and names them in
data.radar; the page stacks them as <img> layers and cycles frames with CSS only.
"""
import re

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


# ---- page --------------------------------------------------------------------------


def test_radar_panel_stacks_layers_and_cycles_six_frames(app_factory):
    html = _page(app_factory, {**WX_DATA, "radar": _radar()})
    panel = html.split('class="card panel wxradar"')[1].split("</section>")[0]
    imgs = re.findall(r'<img class="(wxr\w+)[^"]*" src="([^"]+)"', panel)
    # background, topography under the rain; range, locations over it
    assert [s for c, s in imgs if c == "wxrlayer"] == [
        "/weather/radar/layer_background.png", "/weather/radar/layer_topography.png",
        "/weather/radar/layer_range.png", "/weather/radar/layer_locations.png"]
    assert [s for c, s in imgs if c == "wxrframe"] == [f"/weather/radar/frame_{s}.png" for s in STAMPS]
    assert [c for c, _ in imgs].index("wxrframe") == 2            # rain sits between the layer groups
    assert all(f'class="wxrframe f{i}"' in panel for i in range(6))
    assert "<script" not in panel


def test_radar_text_line_and_legend_carry_the_meaning_in_words(app_factory):
    html = _page(app_factory, {**WX_DATA, "radar": _radar()})
    # 00:29Z is 11:29 in Melbourne (AEDT, UTC+11) on 2026-10-06
    assert "11:29–11:54, 5-min frames · 6 frames, latest held" in html
    for word in ("Light", "Moderate", "Heavy", "Very heavy", "Extreme, possible hail", "mm/h"):
        assert word in html
    assert "Bureau of Meteorology" in html
    assert "Radar unavailable" not in html
    assert 'class="wxrclock f5" aria-hidden="true">11:54<' in html


def test_fewer_frames_pad_the_cycle_with_the_oldest(app_factory):
    html = _page(app_factory, {**WX_DATA, "radar": _radar(STAMPS[-2:])})
    frames = re.findall(r'class="wxrframe f\d" src="/weather/radar/(frame_\d+)\.png"', html)
    assert frames == ["frame_202610060049"] * 5 + ["frame_202610060054"]
    assert "11:49–11:54, 5-min frames · 2 frames" in html


def test_stale_radar_shows_unavailable_with_the_last_frames(app_factory):
    html = _page(app_factory, {**WX_DATA, "radar": _radar(fetched_ok=False)})
    assert "<b>Radar unavailable</b> — showing the last stored frames, 11:29–11:54" in html
    assert 'class="wxrframe f5"' in html


def test_no_radar_field_shows_a_note_never_a_crash(app_factory):
    html = _page(app_factory, WX_DATA)                             # pre-radar envelope
    assert 'class="card panel wxradar wxradar-off"' in html
    assert "Radar unavailable — the loop appears after the next successful radar fetch." in html
    assert "<img" not in html.split("wxradar-off")[1].split("</section>")[0]


def test_malformed_radar_blocks_never_crash_and_never_emit_odd_paths(app_factory):
    for radar in ("x", {"frames": "x"}, {"frames": [None, 3, {"file": "../open_meteo.json",
                                                              "time_iso": "2026-10-06T00:00:00+00:00"}]},
                  {"frames": [{"file": "frame_202610060029.png", "time_iso": "nope"}]}):
        html = _page(app_factory, {**WX_DATA, "radar": radar})
        assert "9.7" in html and "wxradar-off" in html and "open_meteo.json" not in html


def test_unknown_layer_names_are_dropped(app_factory):
    html = _page(app_factory, {**WX_DATA, "radar": _radar(layers=["layer_background.png", "../x.png"])})
    assert html.count('class="wxrlayer"') == 1


def test_not_connected_weather_has_no_radar_panel(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        html = client.get("/weather").text
    assert "Not connected" in html and "wxradar" not in html.split("<main", 1)[1]


def test_reduced_motion_and_tokens_in_css():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    rm = css.split("@media (prefers-reduced-motion: reduce) {\n  .wxradarbox")[1].split("\n}")[0]
    assert "animation: none" in rm and ".f5 { opacity: 1; }" in rm
    assert "@keyframes wxr " in css and "@keyframes wxrlast" in css


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
