"""JY-055 (2026-10-27): progress, resume and watched synced to Jellyfin. Spec: docs/specs/JY-055-resume-watched-sync.md.

Jellyfin is the one record (JY-050 Q6 A). What the hub adds: a stop drops the hub's item cache (Joey's own watch-state
writes never show stale), a start refuses a player token that is another household member's Jellyfin user (plays would
land on the wrong person's Continue watching and Diary), and the play recorder sees a Joey player play like any other
Jellyfin client's. A fake Jellyfin keeps the sessions the reports make; names, ids and tokens are invented; no live call."""
import sqlite3
import time
from urllib.parse import urlsplit

import pytest

from hub import identity, media_item, media_plays, player_api
from tests.hub.test_player_api import (  # noqa: F401  (fixtures)
    HER, ITEM, START, TOKENS, UIDS, YOU, client, env, err, jf, start)

RUNTIME = 26_400_000_000
USERS = [{"Name": "Sample Person", "Id": UIDS[TOKENS["you"]]}, {"Name": "Sample Partner", "Id": UIDS[TOKENS["her"]]}]
ADMIN = "admin-key-test-77"


def jellyfin_sessions(jf):
    """The fake Jellyfin also keeps one session per user from the player's reports, and answers the recorder's
    `/Sessions` and `/Users` reads (admin key) the way Jellyfin does: NowPlayingItem while playing, gone after Stopped."""
    plain, kept = jf.handle, {}

    def handle(method, url, params=None, json=None, headers=None, timeout=None, **kw):
        path = urlsplit(url).path
        auth = (headers or {}).get("Authorization", "")
        if method == "GET" and path in ("/Sessions", "/Users"):
            jf.calls.append({"method": method, "path": path, "params": params, "json": json, "headers": headers or {},
                             "timeout": timeout})
            assert auth == f"MediaBrowser Token={ADMIN}"
            body = USERS if path == "/Users" else list(kept.values())

            class R:
                status_code = 200

                def json(self):
                    return body
            return R()
        resp = plain(method, url, params=params, json=json, headers=headers, timeout=timeout, **kw)
        if method == "POST" and path.startswith("/Sessions/Playing"):
            uid = UIDS[auth.rsplit('Token="', 1)[-1].rstrip('"')]
            name = next(u["Name"] for u in USERS if u["Id"] == uid)
            if path.endswith("/Stopped"):
                kept[uid] = {"UserId": uid, "UserName": name, "PlayState": {}}
            else:
                kept[uid] = {"UserId": uid, "UserName": name, "PlayState": {"PositionTicks": json["PositionTicks"]},
                             "Client": "Joey", "DeviceName": "Joey player web",
                             "NowPlayingItem": {"Id": json["ItemId"], "Name": "Harbour Lights", "Type": "Movie",
                                                "RunTimeTicks": RUNTIME, "ProviderIds": {"Tmdb": "603"}}}
        return resp
    jf.handle = handle
    return kept


@pytest.fixture()
def recorder(env, tmp_path):
    env.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    env.setenv("JELLYFIN_API_KEY", ADMIN)
    env.setenv("JELLYFIN_USER", "Sample Person")
    env.setenv("JELLYFIN_USER_HER", "Sample Partner")
    env.delenv("JELLYFIN_USER_ALIASES", raising=False)
    env.setenv("PLAY_RECORDER", "off")   # no background task: the test polls by hand

    def rows():
        with sqlite3.connect(tmp_path / "media.db") as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT owner, jf_id, position_pct, finished FROM play ORDER BY id")]
    return rows


def paths(body):
    return {name: body["stream"].replace("/stream", "/" + name) for name in ("progress", "stop")}


# ---- the recorder sees Joey player plays ----

def test_the_recorder_records_a_joey_player_play_as_the_members_own(client, jf, recorder):
    kept = jellyfin_sessions(jf)
    body = start(client, headers=HER)
    p = paths(body)
    assert client.post(p["progress"], headers=HER, json={"position_ticks": RUNTIME // 2}).status_code == 204
    assert media_plays.poll_once() == 1
    assert recorder() == [{"owner": "her", "jf_id": ITEM, "position_pct": 50, "finished": 0}]
    client.post(p["progress"], headers=HER, json={"position_ticks": RUNTIME * 95 // 100})
    media_plays.poll_once()
    assert recorder() == [{"owner": "her", "jf_id": ITEM, "position_pct": 95, "finished": 1}]
    assert client.post(p["stop"], headers=HER, json={"position_ticks": RUNTIME}).status_code == 204
    assert "NowPlayingItem" not in kept[UIDS[TOKENS["her"]]]
    assert media_plays.poll_once() == 0 and len(recorder()) == 1   # a stopped play is one watch, not a new row


def test_you_and_her_are_recorded_apart(client, jf, recorder):
    jellyfin_sessions(jf)
    for who in (YOU, HER):
        client.post(paths(start(client, headers=who))["progress"], headers=who, json={"position_ticks": RUNTIME // 4})
    assert media_plays.poll_once() == 2
    assert sorted(r["owner"] for r in recorder()) == ["her", "you"]


# ---- a player token must be the member's own Jellyfin user ----

def test_a_player_token_of_the_other_member_is_refused_before_playback_info(client, jf, env, recorder):
    identity.owner_for_jellyfin(UIDS[TOKENS["you"]], users_of=lambda: USERS)   # the household ids, as the recorder reads them
    env.setenv("JELLYFIN_PLAYER_TOKEN_HER", TOKENS["you"])   # B.'s token set as hers by mistake
    r = client.post("/api/play/sessions", headers=HER, json=START)
    assert r.status_code == 503 and err(r) == "not_configured"
    assert "your own Jellyfin user" in r.json()["error"]["message"]
    assert not any(c["path"].endswith("/PlaybackInfo") for c in jf.calls)
    assert TOKENS["you"] not in r.text and UIDS[TOKENS["you"]] not in r.text


def test_the_members_own_token_passes_the_owner_check(client, jf, recorder):
    identity.owner_for_jellyfin(UIDS[TOKENS["you"]], users_of=lambda: USERS)
    start(client, headers=HER)
    start(client, headers=YOU)


def test_an_unknown_household_never_blocks_a_start_or_reads_users(client, jf):
    """No /Users read yet (the recorder resolves it): the check is skipped, never a live /Users read on the start path."""
    start(client, headers=HER)
    assert "/Users" not in [c["path"] for c in jf.calls]


# ---- a stop drops the hub's item cache ----

def seed_item():
    media_item._cache[media_item._ck(ITEM)] = (time.time(), {"item": {"id": ITEM, "title": "Harbour Lights"},
                                                             "seasons": [], "files": None})


@pytest.mark.parametrize("answer", [None, 500])
def test_a_stop_drops_the_cached_item_so_the_title_page_reads_the_new_position(client, jf, answer):
    p = paths(start(client))
    seed_item()
    client.post(p["progress"], headers=YOU, json={"position_ticks": 5})
    assert media_item.peek(ITEM) is not None   # a heartbeat leaves it: only the stop changes what the page shows
    if answer:
        jf.fail["/Sessions/Playing/Stopped"] = answer
    r = client.post(p["stop"], headers=YOU, json={"position_ticks": 9_000_000_000})
    assert r.status_code == (502 if answer else 204)
    assert media_item.peek(ITEM) is None


def test_a_refused_stop_keeps_the_cache(client, jf):
    """A stop the hub refuses (someone else's session) changed nothing in Jellyfin: the cache stays."""
    p = paths(start(client))
    seed_item()
    assert client.post(p["stop"], headers=HER, json={"position_ticks": 1}).status_code == 404
    assert media_item.peek(ITEM) is not None


# ---- what Jellyfin needs to keep the resume point, the watched mark and the track choice ----

def test_every_stop_carries_the_position_and_the_chosen_tracks(client, jf):
    """Jellyfin marks an item watched when a stop carries NO position, so every stop sends one (required, 400 without);
    the chosen audio and subtitle indexes ride on every report, so Jellyfin's own "remember selections" keeps them."""
    p = paths(start(client, audio_index=2, subtitle_index=3))
    assert client.post(p["stop"], headers=YOU, json={}).status_code == 400
    client.post(p["progress"], headers=YOU, json={"position_ticks": 7})
    client.post(p["stop"], headers=YOU, json={"position_ticks": 8})
    reports = [c for c in jf.calls if c["path"].startswith("/Sessions/Playing")]
    assert [c["json"]["PositionTicks"] for c in reports] == [7, 8]
    assert all((c["json"]["AudioStreamIndex"], c["json"]["SubtitleStreamIndex"]) == (2, 3) for c in reports)
