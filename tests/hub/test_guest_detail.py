"""Joey TV WP-B3 step 4 (2026-10-21): detail pages under guest, and the ONE Jellyfin link seam.

As a friend a title / item page carries no household control (Q19): no Search now (`/arr`), no upgrade note or Search
for upgrade (`/upgrade`), no Quality, no file-strip badges, no Follow (`/media/follow`), no Jellyseerr link, and the
Request block only where hub.guest.allows() serves the request route (GUEST since WP-B4: tests/hub/test_guest_requests.py). The person page has no
Follow; the diary has no owner switch and no Play stats link (PRIVATE).

The seam: on the media front every Jellyfin link (Play, the shelves' links) is built on JELLYFIN_PUBLIC_URL - port kept
verbatim, because the TV shell's UrlPolicy matches scheme + host + PORT (a `:8443`-less href is "block", not
"hand-off") - never on the registry's `jellyfin-app` LAN launcher. Play carries `data-jf-id` (the Jellyfin item id the
shell hands to the Jellyfin app, WP-B6 route 1b)."""
import re

import pytest

from hub import shell
from tests.hub.fake_jellyfin import FRIEND_ID, PUBLIC_URL
from tests.hub.guest_pages import guest_client, links_of, sign_in

JF = "f11f" * 8
LIB = {"server_id": "srv-1", "library": {"movies": 1, "episodes": 0},
       "movies": [{"title": "Library Film", "jf_id": JF, "item_key": "tmdb:603", "year": 1999, "poster": "jf:" + JF,
                   "played": True, "last_played_at": "1999-01-01"}],
       "shows": [], "latest": []}
ARR = {"radarr": {"movies": [{"tmdb_id": 603, "title": "Library Film", "path": "/volume1/SENTINEL_DISK/Library Film",
                              "id": 7, "monitored": True, "has_file": True}]}}


@pytest.fixture()
def friend(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": LIB, "arr": ARR})
    fake.items[JF] = {"Id": JF, "Type": "Movie", "Name": "Library Film", "ProductionYear": 1999,
                      "ProviderIds": {"Tmdb": "603"}, "RunTimeTicks": 120 * 600_000_000,
                      "MediaSources": [{"Container": "mkv", "MediaStreams": [
                          {"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc", "VideoRangeType": "HDR10"},
                          {"Type": "Audio", "Codec": "truehd", "Channels": 8, "Language": "eng"}]}],
                      "MediaStreams": [{"Type": "Video", "Height": 2160, "Width": 3840, "Codec": "hevc"}],
                      "RemoteTrailers": [{"Url": "https://www.youtube.com/watch?v=abcdefghijk"}]}
    with client as c:
        c.fake = fake
        sign_in(c, fake, FRIEND_ID)
        yield c


def actions(html: str) -> list[str]:
    return [u for m, u, attr in links_of(html) if attr in ("action", "hx-post", "hx-get")]


def play_anchor(html: str) -> str:
    m = re.search(r'<a [^>]*class="btn btn-white"[^>]*>(?:Play|Resume|Play again)[^<]*</a>', html)
    assert m, "no Play button"
    return m.group(0)


@pytest.mark.parametrize("path", [f"/media/item/{JF}", "/media/title/movie/603"])
def test_film_page_guest_controls(friend, path):
    r = friend.get(path)
    assert r.status_code == 200, path
    html = r.text
    for bad in ("/arr", "/upgrade", "/media/follow", "/quality", "/search"):   # /request: GUEST since WP-B4
        assert not [a for a in actions(html) if bad in a], (path, bad, actions(html))
    assert "jellyseerr" not in html.lower() and "SENTINEL_DISK" not in html and "1999-01-01" not in html
    assert 'class="fmtbadges"' not in html                         # the file strip's badges are off


def test_play_href_is_the_public_jellyfin_url_with_the_item_id(friend):
    html = friend.get(f"/media/item/{JF}").text
    a = play_anchor(html)
    href = re.search(r'href="([^"]+)"', a).group(1).replace("&amp;", "&")
    assert href.startswith(PUBLIC_URL + "/web/#/details?id=" + JF), href
    assert f'data-jf-id="{JF}"' in a
    assert "192.168." not in html and "jellyfin.test:8096" not in html


def test_the_seam_is_one_function(friend, monkeypatch):
    """find_detail_source's link IS jellyfin_link(registry href): the public URL on the media front (port kept,
    trailing slash dropped), None when it is unset (fail closed: no Play link rather than the LAN launcher)."""
    src = shell.find_detail_source("jellyfin", {})
    assert src["href"] == PUBLIC_URL
    monkeypatch.setenv("JELLYFIN_PUBLIC_URL", PUBLIC_URL + "/")
    assert shell.jellyfin_link("http://192.168.68.59:8096") == PUBLIC_URL
    monkeypatch.delenv("JELLYFIN_PUBLIC_URL")
    assert shell.jellyfin_link("http://192.168.68.59:8096") is None
    monkeypatch.setenv("JOEY_FRONT", "private")
    assert shell.jellyfin_link("http://192.168.68.59:8096") == "http://192.168.68.59:8096"


def test_person_page_has_no_follow(friend):
    r = friend.get("/media/person/287")
    assert r.status_code in (200, 404)
    assert not [a for a in actions(r.text) if "/media/follow" in a]


def test_diary_has_no_owner_switch_and_no_play_stats(friend):
    html = friend.get("/media/diary").text
    assert "/media/settings/diary_scope" not in html and "/media/server/history" not in html
    assert "Everyone" not in html
