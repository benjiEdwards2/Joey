"""WP-U3 commit B (2026-10-07): the Services band as a card grid with vendored
logos. Real registry + sample snapshots; every assertion is made inside <main>."""
import re
from pathlib import Path

from connectors.stubs import MEDIA_APPS
from hub import server
from tests.hub.test_server import env, main_of, services_of, txt  # noqa: F401 (fixture)

SVC_DIR = Path(server.__file__).resolve().parent / "static" / "svc"


def cards_of(body):
    """Every card: a link (<a>) or, for an app with no href, a plain <div>."""
    return [m.group(0) for m in re.finditer(r'<(a|div) class="svc-card[^"]*".*?</\1>', services_of(body), re.S)]


def card(body, name):
    return next(c for c in cards_of(body) if f'<span class="svc-name">{name}</span>' in c)


def test_every_media_app_has_a_logo_file_or_is_listed_in_no_logo():
    for app in MEDIA_APPS:
        aid = app["id"]
        if aid in server.NO_LOGO:
            continue
        assert aid in server.SERVICE_LOGOS, f"{aid}: add a logo to hub/static/svc/ or list it in NO_LOGO"
        path = SVC_DIR / server.SERVICE_LOGOS[aid]
        assert path.is_file() and path.stat().st_size < 200_000, aid
        if path.suffix == ".svg":
            head = path.read_text(encoding="utf-8")
            assert head.lstrip().startswith(("<svg", "<?xml")) and "<script" not in head.lower(), aid
    assert all(aid in server.SERVICE_SUBTITLES for aid in (a["id"] for a in MEDIA_APPS))


def test_one_card_per_app_with_logo_subtitle_word_and_grouping(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    svc = services_of(body)
    cards = cards_of(body)
    assert len(cards) == len(MEDIA_APPS)
    assert 'class="row' not in svc                                         # the old row list is gone
    jf = card(body, "Jellyfin")
    assert re.search(r'<img class="svc-logo" src="/static/svc/jellyfin\.svg\?v=[0-9a-f]+" alt="" '
                     r'width="40" height="40">', jf)
    assert '<span class="svc-sub">Media server · LAN</span>' in jf and ">Up</span>" in jf
    assert jf.startswith('<a class="svc-card" href="http://') and ':8096" target="_blank"' in jf  # LAN link, 2026-10-10
    pr = card(body, "Prowlarr")
    assert 'class="svc-card is-down"' in pr and ">Down</span>" in pr and "timeout" in pr
    assert '<span class="svc-sub">Indexers · LAN</span>' in pr
    assert "/static/svc/uptime-kuma.svg?v=" in card(body, "Uptime Kuma")
    for c in cards:                                   # a linked card is the one link; a card with no href has none
        assert c.count("<a ") == c.count("</a>") == (1 if c.startswith("<a ") else 0)
    order = [svc.index(f'<h2 class="seclabel">{h}</h2>') for h in ("Media", "Downloads", "System")]
    assert order == sorted(order)
    media = svc.split('<h2 class="seclabel">Media</h2>', 1)[1].split("</section>", 1)[0]
    assert ">Jellyfin<" in media and ">Seerr<" in media and ">Radarr<" not in media


def test_kuma_response_ms_when_a_monitor_name_matches(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    assert '<span class="svc-note">38 ms</span>' in card(body, "Jellyfin")
    assert '<span class="svc-note">27 ms</span>' in card(body, "Radarr")
    assert '<span class="svc-note">51 ms</span>' in card(body, "Seerr")          # Kuma still says "Jellyseerr": id match
    assert " ms</span>" not in card(body, "Portainer")             # no matching monitor


def test_service_card_takes_its_gated_hostname():
    """The gated-hostname path (was pinned through the link tile row's `_tile_row`, removed with the row in WP-T3,
    2026-10-19): a gated hostname beats the LAN address; without one the card keeps the LAN link and says "LAN"."""
    app = {"id": "portainer", "name": "Portainer", "href": "http://192.168.68.59:9000", "up": True}
    gated = server.service_card(app, [], {"portainer": "https://portainer.example.org"})
    assert gated["href"] == "https://portainer.example.org" and gated["lan"] is False
    lan = server.service_card(app, [], {})
    assert lan["href"] == "http://192.168.68.59:9000" and lan["lan"] is True


def test_unknown_app_gets_the_fallback_tile_and_no_subtitle(env):
    apps = {"summary": "1 of 1 up", "apps": [
        {"id": "mystery", "name": "mystery App", "href": "http://h:1", "up": True, "status_text": "Up"}]}
    with env(samples=False, media_status=apps) as client:
        body = main_of(client.get("/server").text)
    c = card(body, "mystery App")
    assert "<img" not in c and 'class="svc-logo svc-fallback" aria-hidden="true"' in c
    assert '<span class="svc-initial">M</span>' in c and '<svg class="ic"' in c
    assert '<span class="svc-sub">LAN</span>' in c and ">Up</span>" in c    # http://h:1 is a LAN host


def test_service_card_helper():
    """H-72: the monitor whose name IS the app's name (case-insensitive) — "Jellyfin HTTP" no longer matches."""
    mons = [{"name": "Jellyfin HTTP", "response_ms": 12}, {"name": " jellyfin ", "response_ms": 9}]
    c = server.service_card({"id": "jellyfin", "name": "Jellyfin", "href": "https://jf.example.org"}, mons)
    assert (c["logo"], c["subtitle"], c["href"], c["response_ms"], c["initial"], c["lan"]) == (
        "jellyfin.svg", "Media server", "https://jf.example.org", 9, "J", False)
    assert server.service_card({"id": "wud", "name": "WUD"}, [{"name": "WUD Admin", "response_ms": 3}])["response_ms"] is None
    lan = server.service_card({"id": "jellyfin", "name": "Jellyfin", "href": "http://192.168.68.59:8096"}, [])
    assert lan["href"] == "http://192.168.68.59:8096" and lan["lan"] is True      # LAN link kept, 2026-10-10
    assert server.service_card({"id": "wud", "name": "WUD"}, [])["href"] is None
    gated = server.service_card({"id": "jellyfin", "href": "http://192.168.68.59:8096"}, [],
                                {"jellyfin": "https://jellyfin.joeyhome.net"})
    assert gated["href"] == "https://jellyfin.joeyhome.net" and gated["lan"] is False


def test_is_lan():
    for href in ("http://192.168.68.59:9000", "http://10.0.0.2", "http://127.0.0.1:8000", "http://nas.local:3000",
                 "http://nas:8096", "http://box.lan/", "http://[fd00::1]:80"):
        assert server.is_lan(href), href
    for href in ("https://jellyfin.joeyhome.net", "https://8.8.8.8", "", None, "not a url"):
        assert not server.is_lan(href), href
    assert server.service_card({"id": "zzz"}, [])["logo"] is None
