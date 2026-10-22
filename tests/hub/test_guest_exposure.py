"""Joey TV WP-B3 step 5 (2026-10-21): the exposure crawl - the offline gate of the guest surface.

Sentinel envelopes are built from config/sample_snapshots (the real connector shapes) with the household's private
values swapped for `SENTINEL_*` strings: now_playing title + user, up_next, history, Georgina's block, a played library
row with last_played_at '1999-01-01', a request's requested_by, the *arr disk path, a qBittorrent title; plus you / her
media.db rows. Then, as a signed-in friend (plain and with the TV shell's user agent), EVERY GUEST GET template of
hub.guest (path parameters from tests/deploy/route_sweep.py's fixed table), the guest home, the 404 page and /signin
are requested, and every same-origin href / action / hx-get / hx-post / src plus every absolute URL in each body is
collected.

Pass: no sentinel and no '1999-01-01' anywhere; every same-origin link is one hub.guest.allows() serves (with its own
method); no body names a LAN address (`192.168.`) and every absolute URL's host:port (netloc - NOT the bare host) is the
test JELLYFIN_PUBLIC_URL's, YouTube's or image.tmdb.org: a stray `https://jellyfin.example.test/` without the port
fails, as production's Deco drops external 443. Meta-checks prove the crawl can fail: with the media-front scrub
dropped it finds a sentinel; with the registry href back in the Jellyfin link seam it finds `192.168.`."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest

from hub import guest, media_db, shell
from tests.deploy import route_sweep
from tests.hub.fake_jellyfin import FRIEND_ID, PUBLIC_URL
from tests.hub.guest_pages import TV_UA, guest_client, links_of, sign_in

SAMPLES = Path(__file__).resolve().parents[2] / "config" / "sample_snapshots"
PLAYED = "1999-01-01"
ALLOWED_NETLOCS = {
    urlsplit(PUBLIC_URL).netloc,                  # the public Jellyfin edge, port included
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "www.youtube-nocookie.com",                   # the in-page trailer player (recorded privacy exception,
                                                  # docs/connector-contract.md "Trailer player"); YouTube's own domain
    "image.tmdb.org",
}
XMLNS = re.compile(r'\sxmlns(?::\w+)?="[^"]*"')
PORT_EM = re.compile(r"<em>(:\d+)</em>")
ABSOLUTE = re.compile(r"""https?://[^\s"'<>)\\]+""")


def sample(cid: str) -> dict:
    return copy.deepcopy(json.loads((SAMPLES / f"{cid}.json").read_text(encoding="utf-8"))["data"])


def sentinel_snapshots() -> tuple[dict, str]:
    """(connector -> data, the jf id of a library film the item page can render)."""
    jelly = sample("jellyfin")
    jelly["summary"], jelly["secondary"] = "SENTINEL_SUMMARY", "SENTINEL_SECONDARY"
    jelly["now_playing"][0].update(title="SENTINEL_NOW_TITLE", user="SENTINEL_NOW_USER", show_title="SENTINEL_NOW_SHOW")
    jelly["up_next"][0].update(title="SENTINEL_UPNEXT", show_title="SENTINEL_UPNEXT_SHOW")
    jelly["history"]["recent"][0].update(title="SENTINEL_HISTORY")
    jelly["her"].update(user="SENTINEL_HER_USER")
    for k in ("up_next",):
        if jelly["her"].get(k):
            jelly["her"][k][0]["title"] = "SENTINEL_HER_UPNEXT"
    if (jelly["her"].get("history") or {}).get("recent"):
        jelly["her"]["history"]["recent"][0]["title"] = "SENTINEL_HER_HIST"
    film = jelly["movies"][0]
    film.update(played=True, last_played_at=PLAYED)
    seerr = sample("jellyseerr")
    seerr["requests"][0].update(requested_by="SENTINEL_REQUESTER", tmdb_id=603, item_key="tmdb:603", kind="movie")
    arr = sample("arr")
    arr["disk"][0]["path"] = "/volume1/SENTINEL_DISK_PATH"
    qbit = sample("qbittorrent")
    qbit["active"][0]["name"] = "SENTINEL_TORRENT"
    return {"jellyfin": jelly, "jellyseerr": seerr, "arr": arr, "qbittorrent": qbit}, film["jf_id"]


class Args:
    ref, area_id = "x", "media"

    def __init__(self, jf_id: str):
        self.jf_id = jf_id


def guest_paths(jf_id: str) -> list[str]:
    gets = [route_sweep.fill(t, Args(jf_id)) for m, t in guest.GUEST if m == "GET"]
    return list(dict.fromkeys([guest.home_path(), *gets, "/no-such-page", "/signin"]))


def problems_of(path: str, status: int, body: str) -> list[str]:
    out = []
    if status not in (200, 404):
        out.append(f"{path}: HTTP {status}")
    for m in re.finditer(r"SENTINEL_\w+|" + PLAYED, body):
        out.append(f"{path}: {m.group(0)}")
    if "192.168." in body:
        out.append(f"{path}: 192.168.")
    for method, url, attr in links_of(body):
        if url.startswith(("#", "javascript:", "data:", "mailto:")):
            continue
        parts = urlsplit(urljoin("https://testserver" + path, url))
        if parts.netloc == "testserver":
            if not guest.allows(method, parts.path or "/"):
                out.append(f"{path}: {attr} {method} {parts.path} not served on the media front")
    # The Set up Jellyfin card paints the address's port gold (`...test<em>:8443</em>`): rejoin it, so the scan sees the whole URL.
    for url in ABSOLUTE.findall(PORT_EM.sub(r"\1", XMLNS.sub("", body))):
        netloc = urlsplit(url).netloc.lower()
        if netloc not in ALLOWED_NETLOCS:
            out.append(f"{path}: foreign URL {url[:80]}")
    return out


def crawl(c, jf_id: str, headers: dict | None = None) -> tuple[list[str], int]:
    problems, rendered = [], 0
    for path in guest_paths(jf_id):
        r = c.get(path, headers=headers or {}, follow_redirects=False)
        rendered += r.status_code == 200
        problems += problems_of(path, r.status_code, r.text)
    return problems, rendered


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    snaps, jf_id = sentinel_snapshots()
    client, fake = guest_client(monkeypatch, tmp_path, snaps)
    fake.items[jf_id] = {"Id": jf_id, "Type": "Movie", "Name": "Crawl Film", "ProductionYear": 2001,
                         "ProviderIds": {"Tmdb": "603"}, "RunTimeTicks": 100 * 600_000_000,
                         "RemoteTrailers": [{"Url": "https://www.youtube.com/watch?v=abcdefghijk"}]}
    for owner, word in (("you", "YOU"), ("her", "HER")):
        media_db.set_rating("tmdb:603", 7, "movie", f"SENTINEL_{word}_RATED_DB", owner=owner)
        media_db.add_manual_watch("tmdb:604", "movie", f"SENTINEL_{word}_DIARY_DB", watched_on="2026-10-20",
                                  owner=owner)
    with client as c:
        c.fake, c.jf_id = fake, jf_id
        sign_in(c, fake, FRIEND_ID)
        yield c


def test_sentinel_crawl_and_links(friend):
    problems, rendered = crawl(friend, friend.jf_id)
    assert not problems, "\n".join(problems[:40])
    assert rendered > 25   # the crawl really rendered pages


def test_sentinel_crawl_in_tv_mode(friend):
    problems, rendered = crawl(friend, friend.jf_id, {"User-Agent": TV_UA})
    assert not problems, "\n".join(problems[:40])
    assert rendered > 25


def test_the_crawl_saw_a_public_play_link(friend):
    body = friend.get(f"/media/item/{friend.jf_id}").text
    assert PUBLIC_URL + "/web/#/details?id=" + friend.jf_id in body


def test_a_portless_public_link_fails_the_crawl():
    host = urlsplit(PUBLIC_URL).hostname
    assert problems_of("/x", 200, f'<a href="https://{host}/web/#/details?id=1">Play</a>')
    assert not problems_of("/x", 200, f'<a href="{PUBLIC_URL}/web/#/details?id=1">Play</a>')
    assert problems_of("/x", 200, '<a href="/server">x</a>') and problems_of("/x", 200, '<form method="post" '
                                                                              'action="/media/follow/movie/1">')


# ---- meta-checks: the crawl can fail ----

def test_meta_dropping_the_scrub_fails_on_a_sentinel(friend, monkeypatch):
    monkeypatch.setattr(guest, "scrub_snapshots", lambda snaps: snaps)
    monkeypatch.setattr(guest, "scrub_data", lambda cid, data: dict(data or {}))
    problems, _ = crawl(friend, friend.jf_id)
    assert any("SENTINEL_" in p or PLAYED in p for p in problems), problems[:10]


def test_meta_the_registry_href_in_the_seam_fails_on_a_lan_address(friend, monkeypatch):
    monkeypatch.setattr(shell, "jellyfin_link", lambda registry_href: registry_href)
    problems, _ = crawl(friend, friend.jf_id)
    assert any(p.endswith("192.168.") for p in problems), problems[:10]
