"""Joey TV WP-B3 (2026-10-21): what the guest-surface tests share - a signed-in media-front client on the real registry
(config/areas.yaml) with tests/hub/fake_jellyfin.py behind it, and Jellyfin item bodies in the 12.2 shapes the two
per-friend Overview reads return (`/UserItems/Resume`, `/Items?IsPlayed=true&SortBy=DatePlayed`). Names and ids are
invented ("Sample Friend"); no real address appears."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from tests.hub.fake_jellyfin import HTTPS, FakeJellyfin, media_env, reload_app, session_cookie
from tests.hub.helpers import write_envelope

TV_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/155.0 Safari/537.36 JoeyTV/1.0.0 (2026110101)"
TICKS_PER_MIN = 600_000_000


def movie(jf_id: str, name: str, tmdb: str | None = None, *, minutes: int = 120, at_min: int = 0,
          played_at: str | None = None) -> dict:
    """A Movie item as /UserItems/Resume or /Items return it (UserData carries the viewer's own state)."""
    ud = {"PlaybackPositionTicks": at_min * TICKS_PER_MIN, "Played": played_at is not None,
          "PlayedPercentage": round(100 * at_min / minutes, 1) if at_min else None}
    if played_at:
        ud["LastPlayedDate"] = played_at
    return {"Id": jf_id, "Name": name, "Type": "Movie", "RunTimeTicks": minutes * TICKS_PER_MIN,
            "ProviderIds": {"Tmdb": tmdb} if tmdb else {}, "ImageTags": {"Primary": "tag"}, "UserData": ud}


def episode(jf_id: str, series: str, series_id: str, season: int, number: int, name: str, *, minutes: int = 45,
            at_min: int = 0, played_at: str | None = None) -> dict:
    body = movie(jf_id, name, None, minutes=minutes, at_min=at_min, played_at=played_at)
    body.update(Type="Episode", SeriesName=series, SeriesId=series_id, SeasonId=series_id[:-4] + "5ea5",
                ParentIndexNumber=season, IndexNumber=number)
    return body


def guest_client(monkeypatch, tmp_path, snapshots: dict | None = None, *, base_url: str = HTTPS):
    """(TestClient context manager, fake): the media front on the real registry, snapshots written to tmp_path."""
    media_env(monkeypatch)
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    snaps.mkdir(parents=True, exist_ok=True)
    for cid, data in (snapshots or {}).items():
        write_envelope(snaps, cid, age_minutes=1, data=data)
    fake = FakeJellyfin().install(monkeypatch)
    return TestClient(reload_app(), base_url=base_url), fake


def sign_in(c, fake, uid: str) -> str:
    """Give the client a valid session for Jellyfin user `uid` (the WP-B2 cookie); returns the token."""
    token = fake.token_for(uid)
    c.cookies.clear()
    for k, v in session_cookie(token).items():
        c.cookies.set(k, v)
    return token


def shelf_titles(html: str) -> list[str]:
    """The Overview's shelf headings, in page order (the words before any ' · <count>')."""
    return [re.sub(r"<[^>]+>", "", h).split(" · ")[0].strip()
            for h in re.findall(r'<h2 class="seclabel">(.*?)</h2>', html, re.S)]


class Links(HTMLParser):
    """Every link-ish attribute of a page: (method, url) for href / hx-get (GET), form action (its method, POST by
    default when the form says post), hx-post (POST), hx-delete (DELETE); plus src values (GET)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, str]] = []   # (method, url, attribute)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name, method in (("href", "GET"), ("hx-get", "GET"), ("hx-post", "POST"), ("hx-delete", "DELETE"),
                             ("src", "GET")):
            if a.get(name):
                self.found.append((method, a[name], name))
        if tag == "form" and a.get("action"):
            self.found.append(((a.get("method") or "GET").upper(), a["action"], "action"))


def links_of(html: str) -> list[tuple[str, str, str]]:
    p = Links()
    p.feed(html)
    return p.found
