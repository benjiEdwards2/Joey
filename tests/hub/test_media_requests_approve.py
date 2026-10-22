"""Approve / Decline a pending request (WP-RQ1, 2026-10-22): the Requests page shows what each pending request asked for
(quality profile, TV seasons) and lets B. - and only B. - change it, then approve, or decline. Seerr v3.5.0's routes as
read from server/routes/request.ts: GET /api/v1/request/{id}, PUT /api/v1/request/{id} (serverId / profileId /
rootFolder / languageProfileId / tags assigned straight from the body; seasons: number[]; 202 = no seasons left),
POST /api/v1/request/{id}/approve|decline (409 once not pending). Seerr, Radarr and Sonarr are faked at
requests.get / put / post; no network, no real sleeps."""
import copy
import importlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml
from fastapi.testclient import TestClient

from hub import media_arr_search, media_guest_requests as mgr, media_hidden, media_requests_approve as mra
from tests.hub.conftest import main_of
from tests.hub.helpers import FakeResponse as R, make_area, write_envelope

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyseerr.json")
                    .read_text(encoding="utf-8"))["data"]
SEERR = "http://seerr.secret-host.invalid:5055"
SKEY = "k-SECRET-seerr"
RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr"
ORIGIN_BAD = {"Origin": "https://evil.invalid"}

PENDING_TV = {"href": "http://nas.local:5055/tv/2005", "id": 15, "item_key": "tmdb:2005", "kind": "tv", "poster": None,
              "profile_id": 8, "requested_by": "Sample Friend", "requested_by_id": 5, "seasons": [1, 2],
              "status_text": "Pending", "title": "Quiet Shore", "tmdb_id": 2005, "tvdb_id": 82005,
              "when": "2 hours ago", "year": 2024}


def data():
    d = copy.deepcopy(SAMPLE)
    d["requests"].insert(1, copy.deepcopy(PENDING_TV))
    d["counts"] = {**d["counts"], "pending": 2, "total": 5}
    return d


class Fake:
    """Seerr (the request, its edit, approve / decline, the show's title body, the server settings) + Radarr / Sonarr
    (quality profiles, lookups, PUT, command)."""

    def __init__(self):
        self.calls = []                    # (method, url, params, json)
        self.raise_seerr = None
        self.status = {}                   # (method, path suffix) -> forced HTTP status
        self.requests = {
            13: {"id": 13, "status": 1, "type": "movie", "profileId": None, "serverId": 0, "rootFolder": "/movies",
                 "tags": [], "media": {"tmdbId": 1001}, "requestedBy": {"id": 1}},
            15: {"id": 15, "status": 1, "type": "tv", "profileId": 8, "serverId": 0, "rootFolder": "/tv",
                 "languageProfileId": 1, "tags": [3], "media": {"tmdbId": 2005, "tvdbId": 82005},
                 "seasons": [{"id": 40, "seasonNumber": 2, "status": 1}, {"id": 41, "seasonNumber": 1, "status": 1}],
                 "requestedBy": {"id": 5}}}
        self.show = {"id": 2005, "name": "Quiet Shore", "mediaInfo": {"status": 2, "seasons": [
                         {"seasonNumber": 1, "status": 2}, {"seasonNumber": 2, "status": 2}, {"seasonNumber": 4, "status": 5}]},
                     "seasons": [{"seasonNumber": 0, "name": "Specials"}, {"seasonNumber": 1, "name": "Season 1"},
                                 {"seasonNumber": 2, "name": "Season 2"}, {"seasonNumber": 3, "name": "Season 3"},
                                 {"seasonNumber": 4, "name": "Season 4"}]}
        self.movies = [{"id": 7, "tmdbId": 1001, "title": "Midnight Harbour", "monitored": True, "hasFile": False,
                        "qualityProfileId": 8}]
        self.series = [{"id": 9, "tvdbId": 82005, "tmdbId": 2005, "title": "Quiet Shore", "monitored": True,
                        "qualityProfileId": 7}]

    def _hdr(self, url, headers):
        want = {SEERR: SKEY, RADARR: RKEY, SONARR: TKEY}
        base = next(b for b in want if url.startswith(b))
        assert headers == {"X-Api-Key": want[base]}
        return base

    def _forced(self, method, url):
        return next((s for (m, tail), s in self.status.items() if m == method and url.endswith(tail)), None)

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert timeout
        self.calls.append(("GET", url, params, None))
        base = self._hdr(url, headers)
        if base == SEERR and self.raise_seerr:
            raise self.raise_seerr(f"Max retries exceeded with url: {url} key={SKEY}")
        if (forced := self._forced("GET", url)) is not None:
            return R({}, forced)
        if url == f"{RADARR}/api/v3/qualityprofile":
            return R([{"id": 8, "name": "1080p"}, {"id": 9, "name": "4K"}])
        if url == f"{SONARR}/api/v3/qualityprofile":
            return R([{"id": 7, "name": "1080p"}, {"id": 8, "name": "4K"}])
        if url == f"{SEERR}/api/v1/settings/radarr":
            return R([{"id": 0, "isDefault": True, "is4k": False, "activeProfileId": 8}])
        if url == f"{SEERR}/api/v1/settings/sonarr":
            return R([{"id": 0, "isDefault": True, "is4k": False, "activeProfileId": 7}])
        if url == f"{SEERR}/api/v1/tv/2005":
            return R(copy.deepcopy(self.show))
        if url.startswith(f"{SEERR}/api/v1/request/"):
            rid = int(url.rsplit("/", 1)[1])
            return R(copy.deepcopy(self.requests[rid])) if rid in self.requests else R({}, 404)
        if url == f"{RADARR}/api/v3/movie":
            return R([m for m in self.movies if m["tmdbId"] == (params or {}).get("tmdbId")])
        if url == f"{SONARR}/api/v3/series":
            if params and "tvdbId" in params:
                return R([s for s in self.series if s["tvdbId"] == params["tvdbId"]])
            return R(self.series)
        return R({}, 404)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert timeout
        self.calls.append(("PUT", url, None, json))
        base = self._hdr(url, headers)
        if base == SEERR and self.raise_seerr:
            raise self.raise_seerr(f"Max retries exceeded with url: {url} key={SKEY}")
        if (forced := self._forced("PUT", url)) is not None:
            return R({"message": "No seasons available to request"} if forced == 202 else {}, forced)
        if base == SEERR:
            req = self.requests[int(url.rsplit("/", 1)[1])]
            req["profileId"] = json.get("profileId")
            if "seasons" in json:
                req["seasons"] = [{"seasonNumber": n, "status": 1} for n in json["seasons"]]
            return R(copy.deepcopy(req))
        rows = self.movies if base == RADARR else self.series
        for i, e in enumerate(rows):
            if url.endswith(f"/{e['id']}"):
                rows[i] = dict(json)
        return R(json, 202)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        assert timeout
        self.calls.append(("POST", url, None, json))
        base = self._hdr(url, headers)
        if base == SEERR and self.raise_seerr:
            raise self.raise_seerr(f"Max retries exceeded with url: {url} key={SKEY}")
        if (forced := self._forced("POST", url)) is not None:
            return R({}, forced)
        if base == SEERR:
            rid, what = url.rsplit("/", 2)[1:]
            req = self.requests.get(int(rid))
            if req is None:
                return R({"message": "Request not found."}, 404)
            if req["status"] != 1:
                return R({"message": "Only pending requests can be approved or declined."}, 409)
            req["status"] = {"approve": 2, "decline": 3}[what]
            return R(copy.deepcopy(req))
        return R({"id": 5}, 201)

    def of(self, method, host=SEERR):
        return [c for c in self.calls if c[0] == method and c[1].startswith(host)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests")
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    for k, v in (("JELLYSEERR_URL", SEERR), ("JELLYSEERR_API_KEY", SKEY), ("RADARR_URL", RADARR),
                 ("RADARR_API_KEY", RKEY), ("SONARR_URL", SONARR), ("SONARR_API_KEY", TKEY)):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(media_arr_search, "FOLLOW_WAIT", 0)
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build(d=None):
        write_envelope(snaps, "jellyseerr", age_minutes=1, data=d or data())
        import hub.main
        importlib.reload(hub.main)
        fake = Fake()
        for m in ("get", "put", "post"):
            monkeypatch.setattr(requests, m, getattr(fake, m))
        return TestClient(hub.main.app), fake, snaps

    yield build
    media_hidden.clear()


def warm(client):
    """The first page view's BackgroundTask reads the profile lists; the next view draws chips and words."""
    client.get("/media/requests")
    return main_of(client.get("/media/requests").text)


def approve(client, rid, **form):
    return client.post(f"/media/requests/{rid}/approve", data=form, follow_redirects=False)


def decline(client, rid, **kw):
    return client.post(f"/media/requests/{rid}/decline", follow_redirects=False, **kw)


def rows_of(page):
    return {int(r.split('id="req-', 1)[1].split('"', 1)[0]): r for r in page.split('<div class="row has-form reqrow"')[1:]}


# ---- the page ----

def test_only_pending_rows_carry_approve_and_decline_with_inline_confirms(env):
    client, _, _ = env()
    with client:
        page = warm(client)
    rows = rows_of(page)
    for rid in (13, 15):
        assert f'action="/media/requests/{rid}/approve"' in rows[rid] and f'action="/media/requests/{rid}/decline"' in rows[rid]
        assert 'class="reqbreak"' in rows[rid]                            # a phone puts the buttons on their own line
    for rid in (14, 12, 11):
        assert "/approve" not in rows[rid] and "/decline" not in rows[rid] and "Remove" in rows[rid]
        assert "reqbreak" not in rows[rid]
    assert "confirm(" not in page                                         # guide 6: never a browser dialog
    assert "Decline the request for Quiet Shore?" in page and "Seerr keeps it as Declined. Nothing is downloaded." in page
    for row in rows.values():                                              # the row link never holds a form
        link = row.split('<a class="rowlink"', 1)[1].split("</a>", 1)[0]
        assert "<form" not in link and "<details" not in link


def test_pending_rows_say_what_was_asked_for_and_preselect_it(env):
    client, fake, _ = env()
    with client:
        page = warm(client)
    rows = rows_of(page)
    tv, film = rows[15], rows[13]
    assert "4K · Seasons 1–2" in tv.split("</a>", 1)[0]                  # the meta line: the requester's choice
    assert "Asked for 4K · Seasons 1–2" in tv
    assert '<input type="radio" name="profile" value="8" checked>4K' in tv
    assert '<input type="radio" name="profile" value="7">1080p · Default' in tv
    assert '<input type="checkbox" name="seasons" value="1" checked>' in tv and 'value="2" checked' in tv
    assert 'hx-get="/media/requests/15/seasons" hx-trigger="toggle once"' in tv
    assert "Asked for 1080p" in film                                       # null profileId = the server default
    assert '<input type="radio" name="profile" value="8" checked>1080p · Default' in film
    assert 'name="seasons"' not in film and "hx-get" not in film
    assert not fake.of("GET", SEERR + "/api/v1/request/")                # the page never reads a request live


def test_the_page_draws_without_any_seerr_call_on_the_first_view(env):
    client, fake, _ = env()
    with client:
        page = main_of(client.get("/media/requests").text)
    assert 'action="/media/requests/15/approve"' in page and "Asked for Seasons 1–2" in page   # no profile list yet
    assert [c for c in fake.calls if c[1].startswith(SEERR) and "/settings/" not in c[1]] == []


def test_lazy_season_list_ticks_the_asked_seasons_and_locks_held_ones(env):
    client, fake, _ = env()
    with client:
        html = client.get("/media/requests/15/seasons").text
    assert html.count('name="seasons"') == 4 and "Specials" not in html
    assert 'value="1" checked>' in html and 'value="2" checked>' in html
    assert 'value="3">' in html                                            # free to add
    assert 'value="4" disabled>' in html and "Available" in html          # on disk: shown, not tickable
    assert ("GET", f"{SEERR}/api/v1/tv/2005", None, None) in fake.calls


def test_lazy_season_list_falls_back_to_the_asked_seasons(env):
    client, fake, _ = env()
    fake.status[("GET", "/api/v1/tv/2005")] = 503
    with client:
        html = client.get("/media/requests/15/seasons").text
    assert html.count('name="seasons"') == 2 and 'value="1" checked>' in html


def test_season_list_is_for_pending_tv_rows_only(env):
    client, _, _ = env()
    with client:
        assert client.get("/media/requests/13/seasons").status_code == 404   # a film
        assert client.get("/media/requests/14/seasons").status_code == 404   # approved
        assert client.get("/media/requests/999/seasons").status_code == 404


# ---- approving ----

def test_approve_unchanged_film_sends_no_edit(env):
    client, fake, _ = env()
    with client:
        warm(client)
        r = approve(client, 13, profile="8")
        assert r.status_code == 303 and r.headers["location"] == "/media/requests?decided=approved&dp=8"
        page = main_of(client.get(r.headers["location"]).text)
    assert [c[0] + " " + c[1][len(SEERR):] for c in fake.calls if c[1].startswith(SEERR + "/api/v1/request")] == [
        "GET /api/v1/request/13", "POST /api/v1/request/13/approve"]
    assert fake.of("PUT") == [] and fake.of("PUT", RADARR) == []             # default profile: no safety net
    assert '<p class="metaline st-good" role="status">Approved · 1080p</p>' in page
    row = rows_of(page)[13]
    assert "/approve" not in row and "Approved" in row                    # shown as approved at once
    assert "1 pending · 3 approved" in page


def test_approve_in_4k_edits_keeping_stored_fields_then_approves_and_checks_radarr(env):
    client, fake, _ = env()
    with client:
        warm(client)
        r = approve(client, 13, profile="9")
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?decided=approved&dp=9"
    puts = fake.of("PUT")
    assert puts == [("PUT", f"{SEERR}/api/v1/request/13", None,
                     {"mediaType": "movie", "serverId": 0, "rootFolder": "/movies", "tags": [], "profileId": 9})]
    order = [c[1] for c in fake.calls if c[1].startswith(SEERR + "/api/v1/request")]
    assert order[-1] == f"{SEERR}/api/v1/request/13/approve"
    # the safety net: Radarr still had 1080p, so the movie is PUT to 4K and searched
    rput = fake.of("PUT", RADARR)
    assert rput and rput[0][3]["qualityProfileId"] == 9
    assert fake.of("POST", RADARR)[0][3] == {"name": "MoviesSearch", "movieIds": [7]}
    assert "Approved · 4K" in page


def test_approve_tv_with_changed_seasons_sends_an_int_array_and_keeps_the_rest(env):
    client, fake, _ = env()
    with client:
        warm(client)
        r = client.post("/media/requests/15/approve", data={"profile": "8", "seasons": ["1", "2", "3"]},
                        follow_redirects=False)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?decided=approved&dp=8&ds=1%2C2%2C3"
    assert fake.of("PUT")[0][3] == {"mediaType": "tv", "serverId": 0, "rootFolder": "/tv", "tags": [3],
                                    "languageProfileId": 1, "profileId": 8, "seasons": [1, 2, 3]}
    assert "Approved · 4K · Seasons 1–3" in page
    assert fake.of("PUT", SONARR)[0][3]["qualityProfileId"] == 8          # the safety net moved Sonarr to 4K
    row = rows_of(page)[15]
    assert "Approved" in row and "/media/requests/15/approve" not in row   # decided: no form until the next sweep


def test_approve_tv_unchanged_needs_no_edit(env):
    client, fake, _ = env()
    with client:
        warm(client)
        r = client.post("/media/requests/15/approve", data={"profile": "8", "seasons": ["2", "1"]}, follow_redirects=False)
    assert r.headers["location"].startswith("/media/requests?decided=approved")
    assert fake.of("PUT") == [] and fake.of("POST")[0][1] == f"{SEERR}/api/v1/request/15/approve"


def test_approve_without_chips_keeps_seerrs_profile(env):
    client, fake, _ = env()
    with client:
        r = client.post("/media/requests/15/approve", data={"seasons": ["1", "2"]}, follow_redirects=False)
    assert fake.of("PUT") == [] and r.headers["location"].startswith("/media/requests?decided=approved")


@pytest.mark.parametrize("form", [{}, {"seasons": ["0"]}, {"seasons": ["x"]}])
def test_tv_approve_needs_a_season(env, form):
    client, fake, _ = env()
    with client:
        r = client.post("/media/requests/15/approve", data=form, follow_redirects=False)
    assert r.status_code == 422 and fake.of("POST") == [] and fake.of("PUT") == []


def test_unknown_profile_is_422(env):
    client, fake, _ = env()
    with client:
        r = approve(client, 13, profile="77")
    assert r.status_code == 422 and fake.of("POST") == [] and fake.of("PUT") == []


def test_friend_list_cache_is_dropped_on_approve(env):
    client, _, _ = env()
    mgr._mine[5] = (0.0, {("tv", 2005): 1})
    with client:
        warm(client)
        client.post("/media/requests/15/approve", data={"seasons": ["1", "2"]}, follow_redirects=False)
    assert 5 not in mgr._mine


# ---- declining ----

def test_decline_posts_decline_and_shows_declined_at_once(env):
    client, fake, _ = env()
    with client:
        r = decline(client, 15)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?decided=declined"
    assert [c[1] for c in fake.of("POST")] == [f"{SEERR}/api/v1/request/15/decline"] and fake.of("PUT") == []
    assert '<p class="metaline st-good" role="status">Declined</p>' in page
    row = rows_of(page)[15]
    assert "/approve" not in row and "Declined" in row
    assert "1 pending · 2 approved · 1 available · 2 declined" in page


def test_a_newer_snapshot_is_the_truth_again(env):
    client, _, snaps = env()
    with client:
        decline(client, 15)
        assert "/media/requests/15/approve" not in client.get("/media/requests").text
        ts = (datetime.now(timezone.utc) + timedelta(seconds=media_hidden.GRACE_S + 5)).isoformat()
        env_json = json.loads((snaps / "jellyseerr.json").read_text(encoding="utf-8"))
        env_json["updated_at"] = env_json["fetched_at"] = ts
        (snaps / "jellyseerr.json").write_text(json.dumps(env_json), encoding="utf-8")
        assert "/media/requests/15/approve" in client.get("/media/requests").text


def test_a_decided_row_cannot_be_decided_again(env):
    client, fake, _ = env()
    with client:
        decline(client, 15)
        n = len(fake.calls)
        r = approve(client, 15, seasons="1")
    assert r.headers["location"] == "/media/requests?error=notpending" and len(fake.calls) == n


def test_non_pending_and_unknown_rows_are_refused_without_a_call(env):
    client, fake, _ = env()
    with client:
        assert approve(client, 14, seasons="1").headers["location"] == "/media/requests?error=notpending"
        assert decline(client, 12).headers["location"] == "/media/requests?error=notpending"
        assert decline(client, 999).headers["location"] == "/media/requests?error=missing"
    assert fake.calls == []


# ---- Seerr's answers as words ----

def test_seerr_says_no_longer_pending(env):
    client, fake, _ = env()
    fake.requests[13]["status"] = 2                                        # approved in Seerr since the sweep
    with client:
        r = approve(client, 13)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?error=notpending" and fake.of("POST") == []
    assert "That request is no longer pending" in page


def test_decline_409_is_no_longer_pending(env):
    client, fake, _ = env()
    fake.requests[15]["status"] = 3
    with client:
        assert decline(client, 15).headers["location"] == "/media/requests?error=notpending"


def test_edit_202_means_no_seasons_left_and_nothing_is_approved(env):
    client, fake, _ = env()
    fake.status[("PUT", "/api/v1/request/15")] = 202
    with client:
        r = client.post("/media/requests/15/approve", data={"seasons": ["3"]}, follow_redirects=False)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?error=noseasons" and fake.of("POST") == []
    assert "Seerr has no seasons left to request" in page and "/media/requests/15/approve" in page


def test_refusal_shows_the_status_only(env, caplog):
    client, fake, _ = env()
    fake.status[("POST", "/api/v1/request/13/approve")] = 500
    with caplog.at_level(logging.WARNING), client:
        r = approve(client, 13)
        page = main_of(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/requests?error=refused&code=500"
    assert "Seerr refused (HTTP 500)" in page and "/media/requests/13/approve" in page   # still pending
    assert "seerr request approve refused: HTTP 500" in caplog.text


@pytest.mark.parametrize("act", ["approve", "decline"])
def test_unreachable_is_a_word_and_never_leaks(env, caplog, act):
    client, fake, _ = env()
    fake.raise_seerr = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = client.post(f"/media/requests/13/{act}", follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/media/requests?error=unreachable"
    assert "Couldn&#39;t reach Seerr" in page or "Couldn't reach Seerr" in page
    assert f"seerr request {act} failed: ConnectionError" in caplog.text
    for text in (page, caplog.text, r.headers["location"]):
        assert "secret-host" not in text and "SECRET" not in text


def test_seerr_not_connected(env, monkeypatch):
    client, fake, _ = env()
    monkeypatch.delenv("JELLYSEERR_API_KEY")
    with client:
        assert decline(client, 13).headers["location"] == "/media/requests?error=unset"
    assert fake.of("POST") == []


# ---- the gate ----

def test_her_can_neither_see_nor_use_approve_or_decline(env, monkeypatch):
    from hub.identity import IDENTITY_HEADER
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.invalid")
    as_her = {IDENTITY_HEADER: "her@example.invalid"}
    client, fake, _ = env()
    with client:
        page = client.get("/media/requests", headers=as_her).text
        assert "/approve" not in page and "/decline" not in page and "Midnight Harbour" in page
        assert client.post("/media/requests/13/approve", headers=as_her, follow_redirects=False).status_code == 403
        assert client.post("/media/requests/13/decline", headers=as_her, follow_redirects=False).status_code == 403
        assert client.get("/media/requests/15/seasons", headers=as_her).status_code == 403
        as_you = {IDENTITY_HEADER: "you@example.invalid"}
        assert "/media/requests/13/approve" in client.get("/media/requests", headers=as_you).text
    assert fake.of("POST") == [] and fake.of("PUT") == [] and not fake.of("GET", SEERR + "/api/v1/request")


def test_cross_site_writes_are_refused(env):
    client, fake, _ = env()
    with client:
        for act in ("approve", "decline"):
            assert client.post(f"/media/requests/13/{act}", headers=ORIGIN_BAD, follow_redirects=False).status_code == 403
    assert fake.of("POST") == [] and fake.of("PUT") == []


def test_get_is_not_a_write_route(env):
    client, fake, _ = env()
    with client:
        for act in ("approve", "decline"):
            assert client.get(f"/media/requests/13/{act}").status_code in (404, 405)


def test_the_media_front_never_serves_them(monkeypatch, tmp_path):
    from tests.hub.fake_jellyfin import FRIEND_ID
    from tests.hub.guest_pages import guest_client, sign_in
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyseerr": data()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        for method, path in (("post", "/media/requests/13/approve"), ("post", "/media/requests/13/decline"),
                             ("get", "/media/requests/15/seasons"), ("get", "/media/requests")):
            assert getattr(c, method)(path, follow_redirects=False).status_code == 404, path


def test_routes_are_private_in_the_guest_table():
    from hub import guest
    for method, path in (("POST", "/media/requests/13/approve"), ("POST", "/media/requests/13/decline"),
                         ("GET", "/media/requests/13/seasons")):
        assert not guest.allows(method, path)
    assert all("approve" not in p and "decline" not in p for _, p in guest.GUEST)


def test_media_front_scrub_drops_the_requester_id():
    from hub import guest
    out = guest.scrub_data("jellyseerr", data())
    assert out["requests"] and all("requested_by_id" not in r and "requested_by" not in r for r in out["requests"])
    assert any("profile_id" in r for r in out["requests"])


# ---- words ----

@pytest.mark.parametrize("nums,words", [([1, 2, 4], "Seasons 1–2, 4"), ([3], "Season 3"), ([], None), (None, None),
                                        ([1, 2, 3, 5, 6, 9], "Seasons 1–3, 5–6, 9"), ([2, 1, 2], "Seasons 1–2")])
def test_season_words(nums, words):
    assert mra.season_words(nums) == words


def test_flash_words():
    from hub import media_quality
    media_quality._memo["tv"] = {"at": 0, "rows": [{"id": 7, "name": "1080p", "is_4k": False, "default": True},
                                                   {"id": 8, "name": "4K", "is_4k": True, "default": False}]}
    assert mra.flash_text({"decided": "approved", "dp": "8", "ds": "1,2"}) == "Approved · 4K · Seasons 1–2"
    assert mra.flash_text({"decided": "approved"}) == "Approved"
    assert mra.flash_text({"decided": "declined"}) == "Declined"
    assert mra.flash_text({"decided": "bogus"}) is None and mra.flash_text({}) is None
    assert mra.net_text({"decided": "approved", "qnet": "notyet", "ds": "1"}).startswith("Sonarr hasn't added it yet")
