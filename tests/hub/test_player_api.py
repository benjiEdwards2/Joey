"""JY-053 (2026-10-26): the playback-session API contract (docs/playback-contract.md), against a fake Jellyfin.

Flag off = the unknown-path 404 for everyone; household only (401 no identity, 403 a friend, the media front's gate 404s
it); each endpoint's Jellyfin mapping, error shape and timeout; no token or Jellyfin URL in a log. Names, tokens and
hosts are invented; no live call is made (the one real socket is a local fake that never answers)."""
import importlib
import logging
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from hub import guest, player_api
from hub.identity import IDENTITY_HEADER, Identity

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE, PUBLIC = "http://jf-lan.test:8096", "https://jf-public.test:8443"
TOKENS = {"you": "tok-you-0123456789", "her": "tok-her-9876543210"}
UIDS = {TOKENS["you"]: "a1" * 16, TOKENS["her"]: "b2" * 16}
YOU, HER = {IDENTITY_HEADER: "you@example.test"}, {IDENTITY_HEADER: "her@example.test"}
ITEM = "dcd12e5bf6856e60c225472186cd6cb6"
PROFILE = {"Name": "Test browser", "MaxStreamingBitrate": 120000000,
           "DirectPlayProfiles": [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}]}
START = {"item_id": ITEM, "device": {"kind": "tv", "profile": PROFILE}}   # tv: the kind that may direct-play
FRIEND = Identity(owner="jf:" + "f00d" * 8, name="Sample Friend", jf_user_id="f00d" * 8, jf_token="tok-friend")
ALIAS = Identity(owner="you", name="Sample Alias", jf_user_id="c3" * 16, jf_token="tok-alias-555")
ROUTES = [("POST", "/api/play/sessions"), ("POST", "/api/play/sessions/abc/stream"),
          ("POST", "/api/play/sessions/abc/progress"), ("POST", "/api/play/sessions/abc/stop"),
          ("GET", f"/api/play/items/{ITEM}/tracks")]

STREAMS = [
    {"Type": "Video", "Index": 0, "Codec": "h264"},
    {"Type": "Audio", "Index": 1, "Codec": "aac", "Language": "eng", "DisplayTitle": "English AAC 2.0", "Channels": 2,
     "IsDefault": True},
    {"Type": "Audio", "Index": 2, "Codec": "eac3", "Language": "ita", "DisplayTitle": "Italian EAC3 5.1", "Channels": 6},
    {"Type": "Subtitle", "Index": 3, "Codec": "subrip", "Language": "eng", "DisplayTitle": "English SRT",
     "IsTextSubtitleStream": True, "IsExternal": True, "DeliveryMethod": "External",
     "DeliveryUrl": f"/Videos/{ITEM}/src1/Subtitles/3/0/Stream.vtt?ApiKey=tok-leak-1"},
    {"Type": "Subtitle", "Index": 4, "Codec": "PGSSUB", "Language": "eng", "DisplayTitle": "English PGS",
     "IsForced": True, "DeliveryMethod": "Encode"},
]


def source(**over):
    src = {"Id": "src1", "Container": "mp4", "RunTimeTicks": 26_400_000_000, "SupportsDirectPlay": True,
           "SupportsDirectStream": True, "MediaStreams": STREAMS, "DefaultAudioStreamIndex": 1,
           "DefaultSubtitleStreamIndex": -1}
    src.update(over)
    return src


REMUX_URL = (f"/videos/{ITEM}/master.m3u8?DeviceId=x&MediaSourceId=src1&VideoCodec=h264&AudioCodec=aac"
             f"&ApiKey=tok-leak-2&PlaySessionId=ps1&api_key=tok-leak-3&TranscodeReasons=ContainerNotSupported")


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeJellyfin:
    """Answers the five Jellyfin paths the API uses; records every call. `fail[path] = exception or status`."""

    def __init__(self):
        self.calls, self.fail = [], {}
        self.info = {"MediaSources": [source()], "PlaySessionId": "ps1"}

    def path_of(self, url):
        assert url.startswith(BASE + "/"), "every Jellyfin call goes to JELLYFIN_URL"
        return urlsplit(url).path

    def handle(self, method, url, params=None, json=None, headers=None, timeout=None, **kw):
        path = self.path_of(url)
        self.calls.append({"method": method, "path": path, "params": params, "json": json,
                           "headers": headers or {}, "timeout": timeout})
        failure = self.fail.get(path) or self.fail.get("*")
        if isinstance(failure, type) and issubclass(failure, Exception):
            raise failure("fake failure for " + url)
        if isinstance(failure, int):
            return Resp(failure, {"error": "x"})
        if path == "/Users/Me":
            token = (headers or {}).get("Authorization", "").rsplit('Token="', 1)[-1].rstrip('"')
            return Resp(200, {"Id": UIDS.get(token, "d4" * 16), "Name": "never-logged"})
        if path.endswith("/PlaybackInfo"):
            return Resp(200, self.info)
        if path.startswith("/Sessions/Playing"):
            return Resp(204)
        return Resp(404, {})

    def paths(self):
        return [c["path"] for c in self.calls]


@pytest.fixture()
def jf(monkeypatch):
    fake = FakeJellyfin()
    monkeypatch.setattr(requests, "get", lambda url, **kw: fake.handle("GET", url, **kw))
    monkeypatch.setattr(requests, "post", lambda url, **kw: fake.handle("POST", url, **kw))
    return fake


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(REPO_ROOT / "config" / "areas.yaml"))
    monkeypatch.setenv("OWNER_EMAIL_YOU", "you@example.test")
    monkeypatch.setenv("JELLYFIN_URL", BASE)
    monkeypatch.setenv("JELLYFIN_PUBLIC_URL", PUBLIC + "/")
    monkeypatch.setenv("JELLYFIN_PLAYER_TOKEN_YOU", TOKENS["you"])
    monkeypatch.setenv("JELLYFIN_PLAYER_TOKEN_HER", TOKENS["her"])
    monkeypatch.setenv("PLAYER_API", "on")
    monkeypatch.delenv("JOEY_FRONT", raising=False)
    player_api.clear()
    yield monkeypatch
    player_api.clear()


@pytest.fixture()
def client(env, jf):
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as c:
        yield c


def call(c, method, path, headers=None, json=None):
    return c.request(method, path, headers=headers, json=json, follow_redirects=False)


def err(resp):
    return resp.json()["error"]["code"]


def start(c, headers=YOU, **over):
    r = c.post("/api/play/sessions", headers=headers, json={**START, **over})
    assert r.status_code == 201, r.text
    return r.json()


def media_front_open(monkeypatch, who):
    """The media front with the player routes moved to GUEST (as JY-057 would) and `who` signed in."""
    monkeypatch.setenv("JOEY_FRONT", "media")
    moved = {(m, p) for m, p in guest.PRIVATE if p.startswith("/api/play/")}
    monkeypatch.setattr(guest, "PRIVATE", tuple(e for e in guest.PRIVATE if e not in moved))
    monkeypatch.setattr(guest, "GUEST", guest.GUEST + tuple(sorted(moved)))
    monkeypatch.setattr(guest, "identity_provider", lambda scope: who)


# ---- the flag ----

@pytest.mark.parametrize("value", [None, "", "off", "1", "true", "ON "])
def test_flag_off_every_route_is_the_unknown_path_404(client, jf, env, value):
    if value is None:
        env.delenv("PLAYER_API")
    else:
        env.setenv("PLAYER_API", value)
    if value == "ON ":   # case and spaces are forgiven: this one is ON
        assert call(client, "POST", "/api/play/sessions", YOU, START).status_code == 201
        return
    for method, path in ROUTES:
        unknown = call(client, method, "/api/play-nothing-here", YOU)
        for headers in (YOU, None, {**YOU, "Origin": "https://evil.example"}):
            r = call(client, method, path, headers, {"item_id": "junk"})
            assert (r.status_code, r.content) == (404, unknown.content) == (404, b'{"detail":"Not Found"}'), path
    assert jf.calls == []


def test_flag_off_on_the_media_front_is_the_ordinary_404(client, jf, env):
    env.setenv("PLAYER_API", "off")
    env.setenv("JOEY_FRONT", "media")
    env.setattr(guest, "identity_provider", lambda scope: FRIEND)
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in ROUTES:
        r = call(client, method, path, json=START)
        assert (r.status_code, r.content) == (404, unknown.content), path
    assert jf.calls == []


# ---- who may call ----

def test_not_signed_in_is_401_on_every_route(client, jf):
    for method, path in ROUTES:
        r = call(client, method, path, None, START)
        assert r.status_code == 401 and err(r) == "not_signed_in", path
        assert r.headers["cache-control"] == "no-store"
    assert jf.calls == []


def test_unconfigured_access_owner_is_401(client, jf, env):
    env.delenv("OWNER_EMAIL_YOU")
    r = call(client, "POST", "/api/play/sessions", YOU, START)
    assert r.status_code == 401 and err(r) == "not_signed_in" and jf.calls == []


def test_media_front_friend_gets_the_ordinary_404(client, jf, env):
    env.setenv("JOEY_FRONT", "media")
    env.setattr(guest, "identity_provider", lambda scope: FRIEND)
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in ROUTES:
        r = call(client, method, path, json=START)
        assert (r.status_code, r.content) == (404, unknown.content), path
    assert jf.calls == []


def test_media_front_without_a_session_gets_the_ordinary_404(client, jf, env):
    env.setenv("JOEY_FRONT", "media")
    unknown = call(client, "GET", "/no-such-page-xyz")
    for method, path in ROUTES:
        assert call(client, method, path, json=START).content == unknown.content, path


def test_a_friend_is_refused_by_the_handler_even_past_the_gate(client, jf, env):
    media_front_open(env, FRIEND)
    for method, path in ROUTES:
        r = call(client, method, path, json=START)
        assert r.status_code == 403 and err(r) == "not_allowed", path
    assert jf.calls == []


def test_household_alias_on_the_media_front_plays_with_its_own_token(client, jf, env):
    media_front_open(env, ALIAS)
    env.delenv("JELLYFIN_PLAYER_TOKEN_YOU")
    body = start(client, headers=None)
    assert "/Users/Me" not in jf.paths()   # the session already names the user
    info = jf.calls[-1]
    assert 'Token="tok-alias-555"' in info["headers"]["Authorization"]
    assert info["json"]["UserId"] == ALIAS.jf_user_id and info["params"] == {"userId": ALIAS.jf_user_id}
    s = client.post(body["stream"])
    assert 'Token="tok-alias-555"' in s.json()["headers"]["Authorization"]


def test_cross_site_post_is_refused(client, jf):
    for method, path in ROUTES:
        if method == "POST":
            r = call(client, method, path, {**YOU, "Origin": "https://evil.example"}, START)
            assert r.status_code == 403 and err(r) == "cross_site", path
    assert jf.calls == []


def test_missing_player_token_or_public_url_is_503(client, jf, env):
    env.delenv("JELLYFIN_PLAYER_TOKEN_HER")
    r = call(client, "POST", "/api/play/sessions", HER, START)
    assert r.status_code == 503 and err(r) == "not_configured"
    env.delenv("JELLYFIN_PUBLIC_URL")
    r = call(client, "POST", "/api/play/sessions", YOU, START)
    assert r.status_code == 503 and err(r) == "not_configured"
    assert jf.calls == []


# ---- start ----

def test_start_direct_play(client, jf):
    r = client.post("/api/play/sessions", headers=YOU, json=START)
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    body = r.json()
    sid = body["session_id"]
    assert r.headers["location"] == f"/api/play/sessions/{sid}" and body["stream"] == f"/api/play/sessions/{sid}/stream"
    assert body["play_method"] == "direct" and body["item_id"] == ITEM and body["media_source_id"] == "src1"
    assert body["heartbeat_s"] == 10 and body["start_ticks"] == 0 and body["runtime_ticks"] == 26_400_000_000
    assert (body["audio_index"], body["subtitle_index"]) == (1, -1)   # Jellyfin's per-user defaults (JY-050 Q5 A)
    assert "url" not in body and "headers" not in body                  # the stream is handed out separately
    assert jf.paths() == ["/Users/Me", f"/Items/{ITEM}/PlaybackInfo"]
    me, info = jf.calls
    for c in jf.calls:
        auth = c["headers"]["Authorization"]
        assert auth.startswith('MediaBrowser Client="Joey", Device="Joey player tv", DeviceId="joey-player-you", ')
        assert auth.endswith(f'Token="{TOKENS["you"]}"') and "X-Emby" not in str(c["headers"])
    assert info["method"] == "POST" and info["params"] == {"userId": UIDS[TOKENS["you"]]}
    sent = info["json"]
    assert sent["UserId"] == UIDS[TOKENS["you"]] and sent["DeviceProfile"] == PROFILE
    assert sent["EnableDirectPlay"] and sent["EnableDirectStream"] and sent["EnableTranscoding"]
    assert not {"StartTimeTicks", "AudioStreamIndex", "SubtitleStreamIndex", "MaxStreamingBitrate"} & set(sent)
    start(client)   # the user id is kept: one /Users/Me per token
    assert jf.paths().count("/Users/Me") == 1


def test_start_passes_the_player_options(client, jf):
    body = start(client, start_ticks=6_000_000_000, audio_index=2, subtitle_index=3, max_bitrate=8_000_000,
                 device={"kind": "tv", "profile": PROFILE})
    sent = jf.calls[-1]["json"]
    assert (sent["StartTimeTicks"], sent["AudioStreamIndex"], sent["SubtitleStreamIndex"], sent["MaxStreamingBitrate"]) \
        == (6_000_000_000, 2, 3, 8_000_000)
    assert 'Device="Joey player tv"' in jf.calls[-1]["headers"]["Authorization"]
    assert (body["start_ticks"], body["audio_index"], body["subtitle_index"]) == (6_000_000_000, 2, 3)


@pytest.mark.parametrize("over, method", [({"SupportsDirectPlay": False, "TranscodingUrl": REMUX_URL,
                                            "TranscodingSubProtocol": "hls"}, "remux"),
                                           ({"SupportsDirectPlay": False, "SupportsDirectStream": False,
                                             "TranscodingUrl": REMUX_URL, "TranscodingSubProtocol": "hls"}, "transcode")])
def test_start_remux_and_transcode(client, jf, over, method):
    jf.info = {"MediaSources": [source(**over)], "PlaySessionId": "ps1"}
    body = start(client)
    assert body["play_method"] == method
    s = client.post(body["stream"], headers=YOU).json()
    assert s["protocol"] == "hls" and s["play_method"] == method
    parts = urlsplit(s["url"])
    assert f"{parts.scheme}://{parts.netloc}" == PUBLIC and parts.path == f"/videos/{ITEM}/master.m3u8"
    q = parse_qs(parts.query)
    assert q["PlaySessionId"] == ["ps1"] and q["TranscodeReasons"] == ["ContainerNotSupported"]
    assert "tok-leak" not in s["url"] and not {"ApiKey", "api_key"} & set(q)


@pytest.mark.parametrize("body, code", [
    ({}, "bad_request"),
    ({**START, "item_id": "not-an-id"}, "bad_request"),
    ({**START, "item_id": 12}, "bad_request"),
    ({**START, "device": {"kind": "fridge", "profile": PROFILE}}, "bad_request"),
    ({**START, "device": {"kind": "web"}}, "bad_request"),
    ({**START, "device": "web"}, "bad_request"),
    ({**START, "start_ticks": -1}, "bad_request"),
    ({**START, "audio_index": True}, "bad_request"),
    ({**START, "subtitle_index": -2}, "bad_request"),
    ({**START, "max_bitrate": 0}, "bad_request"),
])
def test_start_refuses_a_bad_body_before_any_call(client, jf, body, code):
    r = client.post("/api/play/sessions", headers=YOU, json=body)
    assert r.status_code == 400 and err(r) == code and r.json()["error"]["message"]
    assert jf.calls == []


def test_start_refuses_non_json_and_oversized_bodies(client, jf):
    r = client.post("/api/play/sessions", headers={**YOU, "content-type": "application/json"}, content=b"{nope")
    assert r.status_code == 400 and err(r) == "bad_request"
    r = client.post("/api/play/sessions", headers=YOU, json=[1, 2])
    assert r.status_code == 400
    big = {**START, "device": {"kind": "tv", "profile": {"pad": "x" * player_api.MAX_BODY}}}
    r = client.post("/api/play/sessions", headers=YOU, json=big)
    assert r.status_code == 413 and err(r) == "too_large"
    assert jf.calls == []


def test_start_dashed_item_id_is_normalised(client, jf):
    dashed = f"{ITEM[:8]}-{ITEM[8:12]}-{ITEM[12:16]}-{ITEM[16:20]}-{ITEM[20:]}".upper()
    assert start(client, item_id=dashed)["item_id"] == ITEM


def test_start_unknown_item_and_cannot_play(client, jf):
    jf.fail[f"/Items/{ITEM}/PlaybackInfo"] = 404
    r = client.post("/api/play/sessions", headers=YOU, json=START)
    assert r.status_code == 404 and err(r) == "item_not_found"
    del jf.fail[f"/Items/{ITEM}/PlaybackInfo"]
    jf.info = {"MediaSources": [], "ErrorCode": "NoCompatibleStream"}
    r = client.post("/api/play/sessions", headers=YOU, json=START)
    assert r.status_code == 409 and r.json()["error"] == {"code": "cannot_play", "message": r.json()["error"]["message"],
                                                          "reason": "NoCompatibleStream"}
    jf.info = {"MediaSources": [], "PlaySessionId": "p"}
    assert client.post("/api/play/sessions", headers=YOU, json=START).status_code == 409
    jf.info = {"MediaSources": [source(SupportsDirectPlay=False)], "PlaySessionId": "p"}   # no TranscodingUrl either
    r = client.post("/api/play/sessions", headers=YOU, json=START)
    assert r.status_code == 409 and r.json()["error"]["reason"] == "NoCompatibleStream"
    assert player_api.SESSIONS == {}


# ---- stream hand-out ----

def test_stream_hands_out_the_public_url_and_the_header_with_no_call(client, jf):
    body = start(client)
    calls = len(jf.calls)
    r = client.post(body["stream"], headers=YOU)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    s = r.json()
    assert s["protocol"] == "file" and s["play_method"] == "direct"
    parts = urlsplit(s["url"])
    assert f"{parts.scheme}://{parts.netloc}" == PUBLIC and parts.path == f"/Videos/{ITEM}/stream"
    assert parse_qs(parts.query) == {"static": ["true"], "mediaSourceId": ["src1"], "playSessionId": ["ps1"]}
    assert TOKENS["you"] not in s["url"]
    assert s["headers"]["Authorization"].endswith(f'Token="{TOKENS["you"]}"')
    assert len(jf.calls) == calls


def test_a_session_belongs_to_its_owner(client, jf):
    body = start(client)
    for path in (body["stream"], body["stream"].replace("/stream", "/progress"), body["stream"].replace("/stream", "/stop")):
        r = client.post(path, headers=HER, json={"position_ticks": 1})
        assert r.status_code == 404 and err(r) == "session_unknown", path
    assert client.post("/api/play/sessions/nope/stream", headers=YOU).status_code == 404
    assert client.post(body["stream"], headers=YOU).status_code == 200   # still yours


# ---- progress and stop ----

def test_progress_reports_playing_then_progress(client, jf):
    body = start(client)
    prog = body["stream"].replace("/stream", "/progress")
    r = client.post(prog, headers=YOU, json={"position_ticks": 10_000_000})
    assert r.status_code == 204 and r.content == b""
    client.post(prog, headers=YOU, json={"position_ticks": 110_000_000, "paused": True})
    first, second = jf.calls[-2:]
    assert (first["path"], second["path"]) == ("/Sessions/Playing", "/Sessions/Playing/Progress")
    assert first["json"] == {"ItemId": ITEM, "MediaSourceId": "src1", "PlaySessionId": "ps1", "PositionTicks": 10_000_000,
                             "PlayMethod": "DirectPlay", "CanSeek": True, "IsPaused": False, "AudioStreamIndex": 1,
                             "SubtitleStreamIndex": -1}
    assert second["json"]["IsPaused"] is True and second["json"]["PositionTicks"] == 110_000_000
    assert second["timeout"] == (player_api.CONNECT_S, player_api.TIMEOUTS["progress"])


@pytest.mark.parametrize("payload", [{}, {"position_ticks": -5}, {"position_ticks": "10"},
                                     {"position_ticks": 1, "paused": "yes"}])
def test_progress_refuses_a_bad_body(client, jf, payload):
    body = start(client)
    calls = len(jf.calls)
    r = client.post(body["stream"].replace("/stream", "/progress"), headers=YOU, json=payload)
    assert r.status_code == 400 and err(r) == "bad_request" and len(jf.calls) == calls


def test_stop_reports_stopped_and_ends_the_session(client, jf):
    jf.info = {"MediaSources": [source(SupportsDirectPlay=False, SupportsDirectStream=False, TranscodingUrl=REMUX_URL,
                                       TranscodingSubProtocol="hls")], "PlaySessionId": "ps9"}
    body = start(client)
    stop = body["stream"].replace("/stream", "/stop")
    r = client.post(stop, headers=YOU, json={"position_ticks": 3_000_000_000})
    assert r.status_code == 204
    last = jf.calls[-1]
    assert last["path"] == "/Sessions/Playing/Stopped"
    assert last["json"] == {"ItemId": ITEM, "MediaSourceId": "src1", "PlaySessionId": "ps9",
                            "PositionTicks": 3_000_000_000, "PlayMethod": "Transcode", "CanSeek": True,
                            "AudioStreamIndex": 1, "SubtitleStreamIndex": -1}
    assert last["timeout"] == (player_api.CONNECT_S, player_api.TIMEOUTS["stop"])
    for path in (stop, body["stream"]):
        r = client.post(path, headers=YOU, json={"position_ticks": 1})
        assert r.status_code == 404 and err(r) == "session_unknown"


def test_stop_needs_a_position(client, jf):
    body = start(client)
    r = client.post(body["stream"].replace("/stream", "/stop"), headers=YOU, json={})
    assert r.status_code == 400 and body["session_id"] in player_api.SESSIONS


def test_a_fifth_session_drops_the_owners_oldest(client, jf):
    mine = [start(client)["session_id"] for _ in range(player_api.MAX_PER_OWNER)]
    hers = start(client, headers=HER)["session_id"]
    start(client)
    assert mine[0] not in player_api.SESSIONS and all(s in player_api.SESSIONS for s in mine[1:] + [hers])
    assert client.post(f"/api/play/sessions/{mine[0]}/stream", headers=YOU).status_code == 404


def test_an_idle_session_is_forgotten(client, jf, env):
    body = start(client)
    env.setattr(player_api, "IDLE_S", -1)
    r = client.post(body["stream"], headers=YOU)
    assert r.status_code == 404 and err(r) == "session_unknown"


# ---- tracks ----

def test_tracks_lists_audio_and_subtitles(client, jf):
    r = client.get(f"/api/play/items/{ITEM}/tracks", headers=YOU)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    t = r.json()
    assert jf.calls[-1]["method"] == "GET" and jf.calls[-1]["path"] == f"/Items/{ITEM}/PlaybackInfo"
    assert jf.calls[-1]["params"] == {"userId": UIDS[TOKENS["you"]]}
    assert t["item_id"] == ITEM and t["media_source_id"] == "src1"
    assert (t["default_audio_index"], t["default_subtitle_index"]) == (1, -1)
    assert t["audio"] == [
        {"index": 1, "language": "eng", "title": "English AAC 2.0", "codec": "aac", "default": True, "channels": 2},
        {"index": 2, "language": "ita", "title": "Italian EAC3 5.1", "codec": "eac3", "default": False, "channels": 6}]
    srt, pgs = t["subtitles"]
    assert srt == {"index": 3, "language": "eng", "title": "English SRT", "codec": "subrip", "default": False,
                   "forced": False, "external": True, "text": True, "delivery": "external",
                   "url": f"{PUBLIC}/Videos/{ITEM}/src1/Subtitles/3/0/Stream.vtt"}
    assert pgs["text"] is False and pgs["forced"] is True and pgs["delivery"] == "encode" and "url" not in pgs
    assert "tok-leak" not in r.text


def test_start_carries_the_same_tracks(client, jf):
    body = start(client)
    assert body["tracks"] == {k: v for k, v in client.get(f"/api/play/items/{ITEM}/tracks", headers=YOU).json().items()
                              if k not in ("item_id", "media_source_id")}


def test_tracks_bad_and_unknown_item(client, jf):
    r = client.get("/api/play/items/zzz/tracks", headers=YOU)
    assert r.status_code == 400 and err(r) == "bad_request" and jf.calls == []
    jf.fail[f"/Items/{ITEM}/PlaybackInfo"] = 404
    r = client.get(f"/api/play/items/{ITEM}/tracks", headers=YOU)
    assert r.status_code == 404 and err(r) == "item_not_found"


# ---- upstream failures and timeouts ----

def _each_op(client, jf):
    """(op, response) for one call per Jellyfin-calling endpoint, failing at that endpoint's own Jellyfin path."""
    jf.fail.clear()
    body = start(client)
    sid_paths = {"progress": body["stream"].replace("/stream", "/progress"), "stop": body["stream"].replace("/stream", "/stop")}
    for op, path, method, url, payload in (
            ("start", f"/Items/{ITEM}/PlaybackInfo", "POST", "/api/play/sessions", START),
            ("tracks", f"/Items/{ITEM}/PlaybackInfo", "GET", f"/api/play/items/{ITEM}/tracks", None),
            ("progress", "/Sessions/Playing", "POST", sid_paths["progress"], {"position_ticks": 5}),
            ("stop", "/Sessions/Playing/Stopped", "POST", sid_paths["stop"], {"position_ticks": 5})):
        yield op, path, (lambda m=method, u=url, p=payload: call(client, m, u, YOU, p))


@pytest.mark.parametrize("failure, status, code, retry", [
    (requests.Timeout, 504, "upstream_timeout", True),
    (requests.ConnectionError, 502, "upstream_unreachable", True),
    (401, 502, "upstream_refused", None),
    (500, 502, "upstream_error", True),
    (400, 502, "upstream_error", False),
])
def test_upstream_failures_have_one_shape(client, jf, failure, status, code, retry):
    for op, path, go in _each_op(client, jf):
        jf.fail = {path: failure}
        before = len(jf.calls)
        r = go()
        assert r.status_code == status, (op, r.text)
        e = r.json()["error"]
        assert e["code"] == code and e["message"] and e.get("retry") == retry, op
        assert r.headers["cache-control"] == "no-store"
        assert jf.calls[before]["timeout"] == (player_api.CONNECT_S, player_api.TIMEOUTS[op]), op
        jf.fail = {}


def test_users_me_failure_is_an_upstream_error_too(client, jf):
    jf.fail["/Users/Me"] = requests.Timeout
    r = client.post("/api/play/sessions", headers=YOU, json=START)
    assert r.status_code == 504 and err(r) == "upstream_timeout"
    assert jf.calls[0]["timeout"] == (player_api.CONNECT_S, player_api.TIMEOUTS["me"])
    assert player_api.SESSIONS == {}


def test_a_jellyfin_that_never_answers_times_out_on_a_real_socket(env, monkeypatch):
    """No fake requests: a local socket accepts and never answers; the hub gives up at its read timeout."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    held, stop = [], threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                continue
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    monkeypatch.setenv("JELLYFIN_URL", f"http://127.0.0.1:{srv.getsockname()[1]}")
    monkeypatch.setattr(player_api, "TIMEOUTS", {k: 0.4 for k in player_api.TIMEOUTS})
    import hub.main
    importlib.reload(hub.main)
    try:
        with TestClient(hub.main.app) as c:
            t0 = time.monotonic()
            r = c.post("/api/play/sessions", headers=YOU, json=START)
            took = time.monotonic() - t0
    finally:
        stop.set()
        t.join(2)
        for conn in held:
            conn.close()
        srv.close()
    assert r.status_code == 504 and err(r) == "upstream_timeout"
    assert 0.35 <= took < 2.0, took


# ---- logs and budgets ----

def test_logs_carry_no_token_url_or_user(client, jf, caplog):
    caplog.set_level(logging.DEBUG)
    body = start(client)
    client.post(body["stream"], headers=YOU)
    client.post(body["stream"].replace("/stream", "/progress"), headers=YOU, json={"position_ticks": 1})
    jf.fail = {"*": requests.Timeout}
    client.post(body["stream"].replace("/stream", "/stop"), headers=YOU, json={"position_ticks": 2})
    jf.fail = {"*": requests.ConnectionError}
    client.post("/api/play/sessions", headers=YOU, json=START)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "player: start tv direct" in text
    for secret in (*TOKENS.values(), "jf-lan.test", "jf-public.test", "never-logged", "you@example.test",
                   "fake failure", UIDS[TOKENS["you"]], "tok-leak"):
        assert secret not in text, secret


def test_hub_overhead_is_inside_the_page_budget(client, jf):
    """docs/playback-contract.md "Budgets": the hub's own time per call (fake Jellyfin answers at once) p95 <= 50 ms."""
    def p95(fn, n=40):
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            times.append(time.perf_counter() - t0)
        return sorted(times)[int(n * 0.95) - 1] * 1000
    body = start(client)
    prog = body["stream"].replace("/stream", "/progress")
    measured = {
        "start": p95(lambda: client.post("/api/play/sessions", headers=HER, json=START)),
        "stream": p95(lambda: client.post(body["stream"], headers=YOU)),
        "progress": p95(lambda: client.post(prog, headers=YOU, json={"position_ticks": 1})),
        "tracks": p95(lambda: client.get(f"/api/play/items/{ITEM}/tracks", headers=YOU)),
    }
    print("hub overhead p95 ms:", {k: round(v, 1) for k, v in measured.items()})
    assert all(v <= 50 for v in measured.values()), measured


# ---- review round 1 (2026-10-26) ----

WRONG = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@pytest.mark.parametrize("flag", ["off", "on"])
def test_a_wrong_method_on_a_real_path_is_404_never_405(client, jf, env, flag):
    """Security review: a 405 + Allow header told a prober the route exists while the flag was off."""
    env.setenv("PLAYER_API", flag)
    for right, path in ROUTES:
        unknown = {m: call(client, m, "/api/play-nothing-here", YOU) for m in WRONG}
        for method in WRONG:
            if method == right or (right == "GET" and method == "HEAD"):
                continue
            r = call(client, method, path, YOU)
            assert r.status_code == 404 and "allow" not in r.headers, (flag, method, path)
            if flag == "off":
                assert r.content == unknown[method].content, (method, path)
    r = call(client, "POST", "/api/play/other/thing", YOU, START)
    assert r.status_code == 404 and r.content == b'{"detail":"Not Found"}'
    assert jf.calls == []


def test_browsers_never_direct_play(client, jf):
    """Q4 A: kind web / phone ask Jellyfin with EnableDirectPlay off and take the HLS URL even if direct play is offered."""
    jf.info = {"MediaSources": [source(TranscodingUrl=REMUX_URL, TranscodingSubProtocol="hls")], "PlaySessionId": "ps1"}
    for kind in ("web", "phone"):
        body = start(client, device={"kind": kind, "profile": PROFILE})
        assert jf.calls[-1]["json"]["EnableDirectPlay"] is False and body["play_method"] == "remux"
        assert client.post(body["stream"], headers=YOU).json()["protocol"] == "hls"
    body = start(client, device={"kind": "tv", "profile": PROFILE})
    assert jf.calls[-1]["json"]["EnableDirectPlay"] is True and body["play_method"] == "direct"
    jf.info = {"MediaSources": [source()], "PlaySessionId": "ps1"}   # direct only, no TranscodingUrl
    r = client.post("/api/play/sessions", headers=YOU, json={**START, "device": {"kind": "web", "profile": PROFILE}})
    assert r.status_code == 409 and r.json()["error"]["reason"] == "NoCompatibleStream"


def test_stop_by_send_beacon_text_plain(client, jf):
    """A closing tab sends stop with navigator.sendBeacon: text/plain JSON, same-origin Origin header."""
    body = start(client)
    r = client.post(body["stream"].replace("/stream", "/stop"), content=b'{"position_ticks": 42}',
                    headers={**YOU, "content-type": "text/plain;charset=UTF-8", "origin": "http://testserver"})
    assert r.status_code == 204
    assert jf.calls[-1]["path"] == "/Sessions/Playing/Stopped" and jf.calls[-1]["json"]["PositionTicks"] == 42


def test_an_oversized_content_length_is_refused_before_reading():
    import asyncio
    from starlette.requests import Request

    async def receive():
        raise AssertionError("the body must not be read")
    scope = {"type": "http", "method": "POST", "path": "/api/play/sessions", "headers": [
        (b"content-length", str(player_api.MAX_BODY + 1).encode())]}
    with pytest.raises(player_api.PlayError) as e:
        asyncio.run(player_api._body(Request(scope, receive)))
    assert (e.value.status, e.value.code) == (413, "too_large")


def test_a_null_subtitle_default_is_minus_one(client, jf):
    jf.info = {"MediaSources": [source(DefaultSubtitleStreamIndex=None)], "PlaySessionId": "ps1"}
    body = start(client)
    assert body["subtitle_index"] == -1 and body["tracks"]["default_subtitle_index"] == -1
    client.post(body["stream"].replace("/stream", "/progress"), headers=YOU, json={"position_ticks": 1})
    assert jf.calls[-1]["json"]["SubtitleStreamIndex"] == -1
