"""WP-U3 commit B (2026-10-07): the Services band as a Homepage-style card grid with vendored
logos. Real registry + sample snapshots; every assertion is made inside <main>."""
import re
from pathlib import Path

from connectors.stubs import MEDIA_APPS
from hub import server
from tests.hub.test_server import env, main_of, services_of, txt  # noqa: F401 (fixture)

SVC_DIR = Path(server.__file__).resolve().parent / "static" / "svc"


def cards_of(body):
    return re.findall(r'<a class="svc-card[^"]*".*?</a>', services_of(body), re.S)


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
    assert 'class="row' not in svc.split('id="monitors"', 1)[0]           # the old row list is gone
    jf = card(body, "Jellyfin")
    assert re.search(r'<img class="svc-logo" src="/static/svc/jellyfin\.svg\?v=[0-9a-f]+" alt="" '
                     r'width="40" height="40">', jf)
    assert '<span class="svc-sub">Media server</span>' in jf and ">Up</span>" in jf
    assert 'href="http://nas.local:8096" target="_blank" rel="noopener"' in jf
    pr = card(body, "Prowlarr")
    assert 'class="svc-card is-down"' in pr and ">Down</span>" in pr and "timeout" in pr
    assert '<span class="svc-sub">Indexers</span>' in pr
    assert "/static/svc/uptime-kuma.svg?v=" in card(body, "Uptime Kuma")
    assert "/static/svc/homepage.png?v=" in card(body, "Homepage")
    for c in cards:                                   # the whole card is the one link
        assert c.count("<a ") == 1 and c.count("</a>") == 1
    order = [svc.index(f'<h2 class="seclabel">{h}</h2>') for h in ("Media", "Downloads", "System")]
    assert order == sorted(order)
    media = svc.split('<h2 class="seclabel">Media</h2>', 1)[1].split("</section>", 1)[0]
    assert ">Jellyfin<" in media and ">Jellyseerr<" in media and ">Radarr<" not in media


def test_kuma_response_ms_when_a_monitor_name_matches(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    assert '<span class="svc-note">38 ms</span>' in card(body, "Jellyfin")
    assert '<span class="svc-note">27 ms</span>' in card(body, "Radarr")
    assert " ms</span>" not in card(body, "Portainer")             # no matching monitor


def test_homepage_card_links_to_the_gated_hostname(env):
    with env() as client:
        body = main_of(client.get("/server").text)
    assert 'href="https://homepage.joeyhome.net"' in card(body, "Homepage")
    assert 'href="http://nas.local:3000"' not in services_of(body)


def test_unknown_app_gets_the_fallback_tile_and_no_subtitle(env):
    apps = {"summary": "1 of 1 up", "apps": [
        {"id": "mystery", "name": "mystery App", "href": "http://h:1", "up": True, "status_text": "Up"}]}
    with env(samples=False, media_status=apps) as client:
        body = main_of(client.get("/server").text)
    c = card(body, "mystery App")
    assert "<img" not in c and 'class="svc-logo svc-fallback" aria-hidden="true"' in c
    assert '<span class="svc-initial">M</span>' in c and '<svg class="ic"' in c
    assert "svc-sub" not in c and ">Up</span>" in c


def test_service_card_helper():
    mons = [{"name": "Jellyfin HTTP", "response_ms": 12}, {"name": "jellyfin", "response_ms": None}]
    c = server.service_card({"id": "jellyfin", "name": "Jellyfin", "href": "http://x"}, mons)
    assert (c["logo"], c["subtitle"], c["href"], c["response_ms"], c["initial"]) == (
        "jellyfin.svg", "Media server", "http://x", 12, "J")
    assert server.service_card({"id": "zzz"}, [])["logo"] is None
