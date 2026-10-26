"""WP-RQ2 (2026-10-22): a friend picks the quality and the seasons, as in Seerr's request dialog.

The media front's request panel (Discover, `?panel=1`) and the title page's confirm step carry the Quality chips
(hub.media_quality.profiles, the default preselected) and, for a show, the season ticks ("All seasons", no "+ future";
seasons on disk disabled). The pick rides the friend's OWN request (`X-Api-User`, pending): Seerr 3.5 keeps a REQUEST-only
user's `profileId` (server/entity/MediaRequest.ts createRequest: `let profileId = requestBody.profileId`, replaced only by
an override rule for a user without REQUEST_ADVANCED). When Seerr stored another profile anyway, the hub PUTs the pick
with the admin key alone (server/routes/request.ts PUT /request/:id: MANAGE_REQUESTS for another user's request, pending
requests only, the status untouched). Nothing approves; the quality safety net and Sonarr's follow never run here.

The fake below extends tests/hub/fake_seerr.FakeSeerr with that PUT and an override-rule switch. Names are invented."""
from __future__ import annotations

import copy
import logging
import re
from urllib.parse import urlsplit

import pytest
import requests

from hub import media_arr_search, media_guest_requests as mgr, media_quality
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.fake_seerr import ADMIN, AUTO_APPROVE, KEY, MANAGE_REQUESTS, URL, FakeSeerr, Resp, res
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.test_guest_requests import FORM, FRIEND_SEERR, HX, SEERR_SNAP, seed

REQUEST_ADVANCED = 8192
PROFILES = [{"id": 4, "name": "1080p", "is_4k": False, "default": True},
            {"id": 5, "name": "4K", "is_4k": True, "default": False}]


class PickSeerr(FakeSeerr):
    """FakeSeerr plus `PUT /api/v1/request/{id}` as Seerr 3.5 serves it, and `override` (an override rule's profile,
    which Seerr stores instead of a non-advanced user's pick)."""

    def __init__(self):
        super().__init__()
        self.override: int | None = None
        self.put_status: int | None = None

    def install(self, monkeypatch) -> "PickSeerr":
        super().install(monkeypatch)
        prev_put = requests.put

        def put(url, *a, **kw):
            return self.put(url, **kw) if str(url).startswith(URL) else prev_put(url, *a, **kw)
        monkeypatch.setattr(requests, "put", put)
        return self

    def post(self, url, json=None, data=None, headers=None, timeout=None, **kw):
        resp = super().post(url, json=json, data=data, headers=headers, timeout=timeout, **kw)
        if self.override is not None and urlsplit(url).path == "/api/v1/request" and resp.status_code == 201:
            self.requests[-1]["profileId"] = self.override
            resp._body["profileId"] = self.override
        return resp

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert timeout, "every Seerr call carries a timeout"
        path, _ = self._record("PUT", url, headers, json)
        headers = headers or {}
        if headers.get("X-Api-Key") != KEY:
            return Resp({"message": "Unauthorized"}, 401)
        if self.put_status:
            return Resp({"message": "refused"}, self.put_status)
        acting = self.users.get(int(headers["X-Api-User"])) if "X-Api-User" in headers else self.users[1]
        req = next((r for r in self.requests if path == f"/api/v1/request/{r['id']}"), None)
        if req is None:
            return Resp({"message": "Request not found."}, 404)
        body, perms = json or {}, acting["permissions"]
        mine = req["requestedBy"]["id"] == acting["id"]
        if (not mine or (body.get("mediaType") != "tv" and not perms & (ADMIN | REQUEST_ADVANCED))) \
                and not perms & (ADMIN | MANAGE_REQUESTS):
            return Resp({"message": "You do not have permission to modify this request."}, 403)
        if req["status"] != 1:
            return Resp({"message": "Only pending requests can be modified."}, 409)
        if body.get("mediaType") == "tv" and not body.get("seasons"):
            return Resp({"message": "Missing seasons."}, 500)
        for k in ("serverId", "profileId", "rootFolder", "tags", "languageProfileId"):
            if k in body:
                req[k] = body[k]
        if body.get("mediaType") == "tv":
            req["seasons"] = [{"seasonNumber": n} for n in body["seasons"]]
        return Resp(copy.deepcopy(req), 200)

    def puts(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "PUT"]


def shows(seerr: PickSeerr) -> PickSeerr:
    """tv 100 gains Specials (never offered); tv 200 is partly on disk (Season 3 available)."""
    seerr.titles[("tv", 100)]["seasons"].insert(0, {"seasonNumber": 0, "name": "Specials", "episodeCount": 2})
    seerr.titles[("tv", 200)] = {**res(200, "Copper Tides", "tv"), "numberOfSeasons": 3,
                                 "seasons": [{"seasonNumber": n, "name": f"Season {n}", "episodeCount": 6} for n in (1, 2, 3)],
                                 "mediaInfo": {"status": 4, "seasons": [{"seasonNumber": 3, "status": 5}]}}
    return seerr


@pytest.fixture()
def side(monkeypatch):
    """Every admin side effect a request could trigger, and the two profiles (1080p default, 4K)."""
    got = []
    monkeypatch.setattr(media_arr_search, "follow_all", lambda *a, **k: got.append(("follow_all", a)) or "ok")
    monkeypatch.setattr(media_quality, "ensure", lambda *a, **k: got.append(("ensure", a)) or "ok")
    monkeypatch.setattr(media_quality, "profiles", lambda kind: copy.deepcopy(PROFILES))
    return got


@pytest.fixture()
def friend(monkeypatch, tmp_path, side):
    client, fake = guest_client(monkeypatch, tmp_path, SEERR_SNAP)
    seerr = shows(seed(PickSeerr().install(monkeypatch)))
    seerr.add_user(FRIEND_SEERR, FRIEND_ID)
    with client as c:
        c.seerr, c.side = seerr, side
        sign_in(c, fake, FRIEND_ID)
        yield c


def post(c, path: str, body: str = "", htmx: bool = True):
    return c.post(path, content=body, headers={**(HX if htmx else {}), **FORM}, follow_redirects=False)


def sent(seerr) -> list[tuple]:
    return seerr.posts_to("/api/v1/request")


def still_pending_and_theirs(seerr) -> None:
    req = seerr.requests[-1]
    assert req["status"] == 1 and req["requestedBy"]["id"] == FRIEND_SEERR
    assert not [c for c in seerr.calls if c[1].endswith(("/approve", "/decline"))]


# ---- the pick rides the friend's own pending request ----

def test_panel_offers_the_quality_chips_with_the_default_ticked(friend):
    panel = friend.get("/media/title/movie/701/request?panel=1", headers=HX).text
    assert re.search(r'role="radiogroup" aria-label="Quality"', panel)
    assert re.search(r'<input type="radio" name="profile" value="4" checked>1080p · Default', panel)
    assert re.search(r'<input type="radio" name="profile" value="5">4K<', panel)
    assert re.search(r'<button[^>]*type="submit" data-first>Request</button>', panel)


def test_a_4k_film_is_sent_as_the_friend_with_its_profile_and_stays_pending(friend):
    done = post(friend, "/media/title/movie/701/request", "panel=1&profile=5").text
    [call] = sent(friend.seerr)
    assert call[3] == {"mediaType": "movie", "mediaId": 701, "profileId": 5}
    assert call[4] == {"X-Api-Key": KEY, "X-Api-User": str(FRIEND_SEERR)}
    assert friend.seerr.requests[-1]["profileId"] == 5
    still_pending_and_theirs(friend.seerr)
    assert friend.seerr.puts() == []                     # Seerr 3.5 kept the pick: no admin PUT
    assert "Requested in 4K — waiting for approval" in done
    assert friend.side == []                             # no safety net, no Sonarr follow


def test_the_default_quality_is_sent_and_not_named(friend):
    done = post(friend, "/media/title/movie/701/request", "panel=1&profile=4").text
    assert sent(friend.seerr)[0][3]["profileId"] == 4
    assert "Requested — waiting for approval" in done and "Requested in" not in done


@pytest.mark.parametrize("raw", ["99", "abc", "", "-5", "1234567890", "4&profile=77"])
def test_an_unknown_profile_falls_back_to_the_default(friend, raw):
    r = post(friend, "/media/title/movie/701/request", f"panel=1&profile={raw}")
    assert r.status_code == 200
    assert sent(friend.seerr)[0][3]["profileId"] == 4
    still_pending_and_theirs(friend.seerr)


def test_an_override_rule_is_undone_by_an_admin_put_and_the_request_stays_pending(friend):
    friend.seerr.override = 4                            # Seerr stored the rule's profile, not the friend's 4K
    done = post(friend, "/media/title/tv/100/request", "panel=1&seasons=1&seasons=2&profile=5").text
    [call] = sent(friend.seerr)
    assert call[3] == {"mediaType": "tv", "mediaId": 100, "seasons": [1, 2], "profileId": 5}
    [put] = friend.seerr.puts()
    rid = friend.seerr.requests[-1]["id"]
    assert put[1] == f"/api/v1/request/{rid}"
    assert put[4] == {"X-Api-Key": KEY}                  # the admin key alone: the friend never holds that power
    assert put[3] == {"mediaType": "tv", "profileId": 5, "seasons": [1, 2]}
    assert friend.seerr.requests[-1]["profileId"] == 5
    still_pending_and_theirs(friend.seerr)
    assert "Requested in 4K · Seasons 1–2 — waiting for approval" in done


def test_a_refused_put_logs_the_status_only_and_still_answers(friend, caplog):
    friend.seerr.override, friend.seerr.put_status = 4, 403
    with caplog.at_level(logging.INFO):
        done = post(friend, "/media/title/movie/701/request", "panel=1&profile=5").text
    assert "waiting for approval" in done
    still_pending_and_theirs(friend.seerr)
    logs = [r.getMessage() for r in caplog.records if r.name in ("hub.media_guest_requests", "hub.media_discover")]
    assert logs == ["friend request pick refused: HTTP 403"]   # the status only: no URL, key, id or name


def test_keep_pick_never_touches_a_request_that_is_not_pending(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "put", lambda *a, **k: calls.append(a) or Resp({}, 200))
    assert mgr.keep_pick({"id": 9, "status": 2, "profileId": 4}, "movie", 5) == "skipped"
    assert mgr.keep_pick({"id": 9, "status": 1, "profileId": 5}, "movie", 5) == "kept"
    assert mgr.keep_pick({"status": 1, "profileId": 4}, "movie", 5) == "skipped"
    assert calls == []


# Seerr's AUTO_APPROVE_4K / _4K_MOVIE / _4K_TV (Overseerr's Permission enum, unchanged in Seerr 3.5). JY-231: B.'s
# "go approve" (2026-10-27) makes 4K approval only, so a friend holding any of them is refused like AUTO_APPROVE.
AUTO_APPROVE_4K, AUTO_APPROVE_4K_MOVIE, AUTO_APPROVE_4K_TV = 32768, 65536, 131072


@pytest.mark.parametrize("perms", [ADMIN, MANAGE_REQUESTS, AUTO_APPROVE,
                                   AUTO_APPROVE_4K, AUTO_APPROVE_4K_MOVIE, AUTO_APPROVE_4K_TV])
def test_a_friend_who_could_approve_is_still_refused(friend, perms):
    friend.seerr.users[FRIEND_SEERR]["permissions"] = perms
    done = post(friend, "/media/title/movie/701/request", "panel=1&profile=5").text
    assert "set up for you yet" in done
    assert sent(friend.seerr) == [] and friend.seerr.puts() == []


# ---- the seasons ----

def test_panel_offers_the_season_ticks_with_all_seasons_ticked(friend):
    panel = friend.get("/media/title/tv/100/request?panel=1", headers=HX).text
    assert '<input type="checkbox" name="seasons" value="all" checked> All seasons' in panel
    assert "+ future" not in panel and 'type="hidden" name="seasons"' not in panel
    assert re.search(r'<input type="checkbox" name="seasons" value="1">\s*Season 1', panel)
    assert re.search(r'<input type="checkbox" name="seasons" value="2">\s*Season 2', panel)
    assert 'value="0"' not in panel and "Specials" not in panel     # season 0 is refused by the form check
    assert 'name="profile"' in panel


def test_all_seasons_is_sent_as_all(friend):
    done = post(friend, "/media/title/tv/100/request", "panel=1&seasons=all").text
    assert sent(friend.seerr)[0][3] == {"mediaType": "tv", "mediaId": 100, "seasons": "all", "profileId": 4}
    assert "Requested — waiting for approval" in done
    assert friend.side == []


def test_seasons_on_disk_or_not_in_the_show_are_dropped(friend):
    confirm = friend.get("/media/title/tv/200/request?step=confirm", headers=HX).text
    assert re.search(r'value="3" disabled>', confirm) and 'name="profile"' in confirm and "+ future" not in confirm
    r = post(friend, "/media/title/tv/200/request", "seasons=2&seasons=3&seasons=9&profile=5")
    assert sent(friend.seerr)[0][3] == {"mediaType": "tv", "mediaId": 200, "seasons": [2], "profileId": 5}
    assert "Requested in 4K · Season 2 — waiting for approval" in r.text
    still_pending_and_theirs(friend.seerr)


def test_only_seasons_on_disk_sends_nothing(friend):
    r = post(friend, "/media/title/tv/200/request", "seasons=3&seasons=9")
    assert "Pick a season that isn&#39;t here yet" in r.text or "Pick a season that isn't here yet" in r.text
    assert sent(friend.seerr) == []


def test_no_season_ticked_answers_in_the_panel(friend):
    """JY-231 review: "All seasons" unticked and no season ticked was a 422 the htmx panel swallowed (nothing happened).
    The panel now comes back as the request form with "Pick at least one season", and nothing is sent."""
    r = post(friend, "/media/title/tv/100/request", "panel=1&profile=5")
    assert r.status_code == 200
    assert "Pick at least one season" in r.text and 'class="reqpanel-form"' in r.text
    assert '<input type="checkbox" name="seasons" value="all" checked> All seasons' in r.text   # the defaults again
    assert sent(friend.seerr) == []


def test_season_words():
    assert mgr.span_words([1, 2]) == "Seasons 1–2"
    assert mgr.span_words([5, 1, 2, 3]) == "Seasons 1–3, 5"
    assert mgr.span_words([4]) == "Season 4"
    four_k = {"name": "4K", "default": False}
    assert mgr.sent_words(four_k, "all", True) == "Requested in 4K — waiting for approval"
    assert mgr.sent_words(None, [1, 2], True) == "Requested · Seasons 1–2 — waiting for approval"
    assert mgr.sent_words({"name": "1080p", "default": True}, [], False) == "Requested"


# ---- TV mode: unchanged (JY-231, B. 2026-10-27: "stop any tv development please"; the TV picks are deferred) ----

def test_tv_mode_keeps_the_request_flow_from_before_rq2(friend):
    """Desktop and phone only: in TV mode the panel is Request + Cancel (a show whole, `seasons=all`), the confirm step
    has no Quality chips, and a posted profile is ignored - the friend's request goes as it did before RQ2."""
    tv = {"User-Agent": TV_UA}
    panel = friend.get("/media/title/tv/100/request?panel=1", headers={**HX, **tv}).text
    assert '<form class="reqpanel-btns"' in panel and '<input type="hidden" name="seasons" value="all">' in panel
    assert 'name="profile"' not in panel and 'type="checkbox"' not in panel and "reqpanel-form" not in panel
    assert re.search(r'<button[^>]*type="submit" data-first>Request</button>', panel)
    confirm = friend.get("/media/title/tv/100/request?step=confirm", headers={**HX, **tv}).text
    assert "Confirm request" in confirm and 'name="profile"' not in confirm and "+ future" not in confirm
    done = friend.post("/media/title/tv/100/request", content="panel=1&seasons=all&profile=5",
                       headers={**HX, **FORM, **tv}, follow_redirects=False).text
    friend.post("/media/title/movie/701/request", content="panel=1&profile=5", headers={**HX, **FORM, **tv},
                follow_redirects=False)
    assert [c[3] for c in sent(friend.seerr)] == [{"mediaType": "tv", "mediaId": 100, "seasons": "all"},
                                                   {"mediaType": "movie", "mediaId": 701}]
    assert friend.seerr.puts() == [] and friend.side == []
    still_pending_and_theirs(friend.seerr)
    assert "Requested — waiting for approval" in done and "Requested in" not in done


def test_panel_and_confirm_leak_nothing(friend):
    from tests.hub.test_guest_exposure import problems_of
    problems = []
    for path in ("/media/title/tv/100/request?panel=1", "/media/title/movie/701/request?panel=1",
                 "/media/title/tv/200/request?step=confirm", "/media/title/movie/701/request?step=confirm"):
        for ua in ({}, {"User-Agent": TV_UA}):
            r = friend.get(path, headers={**HX, **ua})
            problems += problems_of(path, r.status_code, r.text)
            problems += [f"{path}: {w}" for w in ("seerr.test", KEY, "Sample Admin", "radarr", "sonarr") if w in r.text]
    assert not problems, "\n".join(problems)


# ---- JY-231 (2026-10-27): the 4K pick is marked for B.'s approval; nothing on the friend path approves ----
# B., 2026-10-27: "JY-231: go approve" - the 4K policy stays approval only: nothing auto-approves, and B.'s approval on
# Activity > Requests (JY-230) is the control. JY-230 reads the pending request's own profileId + seasons ("4K · Seasons
# 1–2"); these pins prove the friend path writes exactly that, pending (desktop and phone; TV mode is unchanged).

def test_a_4k_seasons_pick_lands_pending_and_marked_for_b(friend):
    done = post(friend, "/media/title/tv/100/request", "panel=1&seasons=1&seasons=2&profile=5").text
    [call] = sent(friend.seerr)
    assert call[3] == {"mediaType": "tv", "mediaId": 100, "seasons": [1, 2], "profileId": 5}
    req = friend.seerr.requests[-1]
    assert req["profileId"] == 5 and [s["seasonNumber"] for s in req["seasons"]] == [1, 2]   # what B.'s row reads
    assert next(p for p in PROFILES if p["id"] == req["profileId"])["is_4k"]                  # the 4K profile, marked
    still_pending_and_theirs(friend.seerr)
    assert "Requested in 4K · Seasons 1–2 — waiting for approval" in done


def test_nothing_on_the_friend_path_approves(friend):
    """Every friend request shape (film, show, 4K, all seasons, an override undone by the admin PUT, web and TV mode): no
    approve / decline call, no `status` and no `is4k` in any body (Seerr's 4K auto-approve bits never apply: Joey's 4K
    is a profile on the one server), and every request Seerr holds is still pending."""
    friend.seerr.override = 4
    for path, body in (("/media/title/movie/701/request", "panel=1&profile=5"),
                       ("/media/title/tv/100/request", "panel=1&seasons=all&profile=5"),
                       ("/media/title/tv/200/request", "seasons=1&seasons=2&profile=5")):
        for ua in ({}, {"User-Agent": TV_UA}):
            friend.post(path, content=body, headers={**HX, **FORM, **ua}, follow_redirects=False)
    writes = [c for c in friend.seerr.calls if c[0] in ("POST", "PUT") and c[1] != "/api/v1/user/import-from-jellyfin"]
    assert len(sent(friend.seerr)) == 6 and friend.seerr.puts()
    assert not [c for c in friend.seerr.calls if c[1].endswith(("/approve", "/decline"))]
    assert all("status" not in (c[3] or {}) and "is4k" not in (c[3] or {}) for c in writes)
    assert all(c[4].get("X-Api-User") == str(FRIEND_SEERR) for c in sent(friend.seerr))   # the friend's own, never B.'s
    assert friend.seerr.requests and all(r["status"] == 1 for r in friend.seerr.requests)


def test_the_friend_path_never_names_an_approve_call():
    """Source guard: the friend request modules hold no approve or decline endpoint (JY-230's approval is B.'s, on the
    private front only)."""
    import inspect
    from hub import media_discover
    for mod in (mgr, media_discover):
        src = inspect.getsource(mod)
        assert "/approve" not in src and "/decline" not in src, mod.__name__
