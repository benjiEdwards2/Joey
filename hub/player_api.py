"""Playback-session API (JY-053, 2026-10-26): the hub side of Joey's own player. The contract is
docs/playback-contract.md; this module follows it and nothing else does.

* OFF unless PLAYER_API=on. Off, every route answers exactly what an unknown path answers (FastAPI's 404), before
  any auth, body or upstream work, so nothing a user can see changes.
* Household only (JY-050 Q2 A). Private front: the Access identity must be `you` or `her`; no identity = 401, any other
  owner = 403. Media front: every route is PRIVATE in hub/guest.py; since JY-057 (2026-10-27, Q3 A) its gate serves the
  five routes (guest.HOUSEHOLD_PLAYER) to a signed-in household member only, flag on, and 404s everyone else; the
  handler still refuses a friend (403) and plays with the member's own session token.
* JY-057: the start answer's `up_next` (the next aired episode) comes from the hub's item cache only, no Jellyfin call.
* Jellyfin identity (JY-053 Q1 A): on the private front each household member's own Jellyfin token, JELLYFIN_PLAYER_TOKEN_YOU /
  _HER (NAS env, never the admin key); the user id comes from `GET /Users/Me` with that token, kept 1 h per token.
* Every Jellyfin call sends the 12.2 header `Authorization: MediaBrowser Client=..., Device=..., DeviceId=..., Version=...,
  Token="..."` and goes to JELLYFIN_URL. Streams are handed out on JELLYFIN_PUBLIC_URL (the :8443 edge, never the tunnel)
  with no credential in the URL: the player sends the same header itself (JY-053 Q2 A).
* Browsers (kind web / phone) never direct-play (JY-053 Q4 A): the hub asks PlaybackInfo with EnableDirectPlay off, so
  every byte (HLS playlists, segments, subtitles) goes through hls.js, which can send the header.
* Wrong methods and unknown paths under /api/play hit `not_found` (a method-agnostic catch-all), so with the flag off
  no probe can tell the routes exist (no 405, no Allow header).
* At most one Jellyfin call per request; the stream hand-out makes none. Timeouts are TIMEOUTS (connect CONNECT_S).
  JY-054 (2026-10-27): a start with `resume: true` first reads the item with the member's own token (their resume
  point and the chapters, `_item_facts`); without it the start is unchanged.
* Sessions live in this process only (SESSIONS): a restart forgets them and the player starts a new one.
* JY-055 (2026-10-27): Jellyfin keeps the resume point, the watched mark (its own rule on Stopped) and the track choice.
  The hub adds two things: a start on the private front refuses a player token whose Jellyfin user is not that member's
  own (`_check_owner`; plays would land on the other person's Continue watching, Diary and History), and a stop drops
  hub.media_item's cache, as Joey's other watch-state writes do, so the title page reads the new position.
* Logs carry the endpoint, the play method and the exception type or HTTP status only: never a URL, token, user or title.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match, Route

from hub import guest, identity, upstream
from hub.identity import resolve_identity
from hub.media_write import same_origin

log = logging.getLogger("hub.player")

FLAG = "PLAYER_API"
PREFIX = "/api/play"
CLIENT, VERSION = "Joey", "0.1.0"
KINDS = ("web", "phone", "tv")
HOUSEHOLD = ("you", "her")
TOKEN_ENV = {"you": "JELLYFIN_PLAYER_TOKEN_YOU", "her": "JELLYFIN_PLAYER_TOKEN_HER"}
CONNECT_S = 2.0
TIMEOUTS = {"start": 4.0, "tracks": 4.0, "progress": 3.0, "stop": 3.0, "me": 3.0, "item": 2.0}   # read timeouts, seconds
HEARTBEAT_S = 10
IDLE_S = 30 * 60            # a session with no call for this long is forgotten
MAX_PER_OWNER = 4           # a fifth start drops that owner's oldest session
MAX_BODY = 64 * 1024        # bytes; a DeviceProfile is a few KB
MAX_CHAPTERS = 100          # JY-054: chapters handed to the player with `resume`
UID_TTL = 3600
METHODS = {"DirectPlay": "direct", "DirectStream": "remux", "Transcode": "transcode"}
BROWSERS = ("web", "phone")   # no direct play: a <video src> / <track src> cannot send the header (Q4 A)
ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
TEXT_SUBS = {"srt", "subrip", "ass", "ssa", "webvtt", "vtt", "mov_text", "ttml", "smi", "sami"}
_HEX32 = re.compile(r"[0-9a-f]{32}")
_KEY_PARAMS = {"apikey", "api_key"}

router = APIRouter()

SESSIONS: dict[str, dict] = {}
_lock = threading.Lock()
_uids: dict[str, tuple[float, str]] = {}   # sha256(token)[:16] -> (fetched_at, user id)


class PlayError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(code)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def clear() -> None:
    with _lock:
        SESSIONS.clear()
        _uids.clear()


def enabled() -> bool:
    return (os.environ.get(FLAG) or "").strip().lower() == "on"


def _no_store(resp: Response) -> Response:
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _error(err: PlayError) -> JSONResponse:
    return _no_store(JSONResponse({"error": {"code": err.code, "message": err.message, **err.extra}},
                                  status_code=err.status))


def _gate(request: Request) -> None:
    """The flag, checked before anything else: off = the unknown-path 404."""
    if not enabled():
        raise HTTPException(404)


def _same_site(request: Request) -> None:
    """The hub's cross-site guard for every POST, in this API's error shape."""
    try:
        same_origin(request)
    except HTTPException:
        raise PlayError(403, "cross_site", "Cross-site request refused.") from None


# ---- who is playing ----

def _viewer(request: Request) -> dict:
    """{owner, token, user_id or None, device_id} for a household member, else PlayError."""
    ident = resolve_identity(request)
    if ident.owner is None:
        raise PlayError(401, "not_signed_in", "Sign in first.")
    if ident.owner not in HOUSEHOLD:
        raise PlayError(403, "not_allowed", "The player is for the household only.")
    if guest.is_media():
        from hub import guest_auth
        token, uid = ident.jf_token, ident.jf_user_id
        device_id = guest_auth.device_of(guest_auth.cookies_of(request.headers))
    else:
        token, uid = (os.environ.get(TOKEN_ENV[ident.owner]) or "").strip(), None
        device_id = f"joey-player-{ident.owner}"
    if not token:
        raise PlayError(503, "not_configured", "The player has no Jellyfin sign-in for you yet.")
    return {"owner": ident.owner, "token": token, "user_id": uid, "device_id": device_id}


def _auth(viewer: dict, kind: str) -> dict:
    return {"Authorization": f'MediaBrowser Client="{CLIENT}", Device="Joey player {kind}", '
                             f'DeviceId="{viewer["device_id"]}", Version="{VERSION}", Token="{viewer["token"]}"'}


def _bases() -> tuple[str, str]:
    base = (os.environ.get("JELLYFIN_URL") or "").strip().rstrip("/")
    public = (os.environ.get("JELLYFIN_PUBLIC_URL") or "").strip().rstrip("/")
    if not (base and public):
        raise PlayError(503, "not_configured", "The player is not connected to Jellyfin.")
    return base, public


# ---- Jellyfin ----

def _call(op: str, method: str, url: str, headers: dict, params=None, body=None, want_json=True,
          not_found: str | None = None):
    """One Jellyfin call with this op's timeout; -> parsed JSON (or None). Every failure is a PlayError."""
    session = upstream.session("jellyfin")
    timeout = (CONNECT_S, TIMEOUTS[op])
    try:
        if method == "GET":
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
        else:
            resp = session.post(url, params=params, json=body, headers=headers, timeout=timeout)
    except requests.Timeout:
        log.info("player: %s upstream timeout", op)
        raise PlayError(504, "upstream_timeout", "Jellyfin did not answer in time.", retry=True) from None
    except Exception as exc:
        log.info("player: %s upstream %s", op, type(exc).__name__)
        raise PlayError(502, "upstream_unreachable", "Can't reach Jellyfin.", retry=True) from None
    status = resp.status_code
    if status == 404 and not_found:
        raise PlayError(404, not_found, "Jellyfin has no such item.")
    if status in (401, 403):
        log.info("player: %s upstream HTTP %d", op, status)
        raise PlayError(502, "upstream_refused", "Jellyfin refused the player's sign-in.")
    if not 200 <= status < 300:
        log.info("player: %s upstream HTTP %d", op, status)
        raise PlayError(502, "upstream_error", f"Jellyfin answered HTTP {status}.", retry=status >= 500)
    if not want_json:
        return None
    try:
        return resp.json()
    except Exception:
        raise PlayError(502, "upstream_error", "Jellyfin sent an answer the hub can't read.") from None


def _user_id(viewer: dict, base: str, headers: dict) -> str:
    if viewer["user_id"]:
        return viewer["user_id"]
    key = hashlib.sha256(viewer["token"].encode()).hexdigest()[:16]
    with _lock:
        hit = _uids.get(key)
    if hit and time.time() - hit[0] < UID_TTL:
        return hit[1]
    me = _call("me", "GET", f"{base}/Users/Me", headers)
    uid = me.get("Id") if isinstance(me, dict) else None
    if not isinstance(uid, str) or not uid:
        raise PlayError(502, "upstream_error", "Jellyfin did not say who the player's sign-in is.")
    with _lock:
        _uids[key] = (time.time(), uid)
    return uid


def _no_users_read():
    raise identity.OwnerUnresolved("not read on the start path")


def _check_owner(viewer: dict, uid: str) -> None:
    """JY-055: on the private front the player token's Jellyfin user must be the member's own (JELLYFIN_USER /
    _ALIASES for `you`, JELLYFIN_USER_HER for `her`), the user the recorder, the Jellyfin sweep and the Diary read for
    them. Checked against the household ids the hub has already read (the recorder reads /Users once); never a /Users
    read here: while they are unknown the start goes ahead. The media front plays as the signed-in user, so no check."""
    if viewer["user_id"]:
        return
    try:
        owner = identity.owner_for_jellyfin(uid, users_of=_no_users_read)
    except identity.OwnerUnresolved:
        return
    except ValueError:
        owner = None
    if owner != viewer["owner"]:
        log.info("player: start refused, the player token is not the member's own Jellyfin user")
        raise PlayError(503, "not_configured", "The player's Jellyfin sign-in is not your own Jellyfin user.")


def _strip_key(url: str, public: str) -> str:
    """Jellyfin's URL as path + query on the public base, with any key parameter removed."""
    parts = urlsplit(url or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _KEY_PARAMS]
    return public + (parts.path if parts.path.startswith("/") else "/" + parts.path) + \
        (("?" + urlencode(query)) if query else "")


def _tracks(source: dict, public: str) -> dict:
    audio, subs = [], []
    for s in source.get("MediaStreams") or []:
        if not isinstance(s, dict) or not isinstance(s.get("Index"), int):
            continue
        common = {"index": s["Index"], "language": s.get("Language"), "title": s.get("DisplayTitle") or s.get("Title"),
                  "codec": (s.get("Codec") or "").lower() or None, "default": bool(s.get("IsDefault"))}
        if s.get("Type") == "Audio":
            audio.append({**common, "channels": s.get("Channels")})
        elif s.get("Type") == "Subtitle":
            text = s.get("IsTextSubtitleStream")
            sub = {**common, "forced": bool(s.get("IsForced")), "external": bool(s.get("IsExternal")),
                   "text": bool(text) if text is not None else common["codec"] in TEXT_SUBS,
                   "delivery": (s.get("DeliveryMethod") or "").lower() or None}
            if s.get("DeliveryUrl"):
                sub["url"] = _strip_key(s["DeliveryUrl"], public)
            subs.append(sub)
    return {"audio": audio, "subtitles": subs,
            "default_audio_index": source.get("DefaultAudioStreamIndex"),
            "default_subtitle_index": -1 if source.get("DefaultSubtitleStreamIndex") is None
            else source["DefaultSubtitleStreamIndex"]}


def _item_facts(base: str, headers: dict, uid: str, item: str) -> dict:
    """JY-054 (2026-10-27), the start's `resume` option: the member's own saved position and the item's chapters, from
    one read with the member's own token (the hub's item cache holds B.'s watch state only). Never fails the start: any
    failure is no resume point and no chapters."""
    try:
        raw = _call("item", "GET", f"{base}/Users/{uid}/Items/{item}", headers, params={"Fields": "Chapters"})
    except PlayError:
        return {"position": 0, "chapters": []}
    raw = raw if isinstance(raw, dict) else {}
    ud = raw.get("UserData") if isinstance(raw.get("UserData"), dict) else {}
    pos = ud.get("PlaybackPositionTicks")
    position = pos if isinstance(pos, int) and not isinstance(pos, bool) and pos > 0 and not ud.get("Played") else 0
    chapters = []
    for c in raw.get("Chapters") or []:
        tick = c.get("StartPositionTicks") if isinstance(c, dict) else None
        if isinstance(tick, int) and not isinstance(tick, bool) and tick >= 0:
            chapters.append({"name": str(c.get("Name") or "")[:80], "start_ticks": tick})
    return {"position": position, "chapters": chapters[:MAX_CHAPTERS]}


def _up_next(item: str) -> dict | None:
    """JY-057 (2026-10-27, additive): the next aired episode from the hub's item cache (media_watch.up_next), never a
    Jellyfin call; None when nothing is cached. A failure here never fails the start."""
    from hub import media_watch   # lazy: media_watch imports this module
    try:
        return media_watch.up_next(item)
    except Exception as exc:
        log.info("player: up_next %s", type(exc).__name__)
        return None


def _first_source(info) -> dict:
    if not isinstance(info, dict):
        raise PlayError(502, "upstream_error", "Jellyfin sent an answer the hub can't read.")
    if info.get("ErrorCode"):
        raise PlayError(409, "cannot_play", "Jellyfin can't play this here.", reason=str(info["ErrorCode"])[:40])
    sources = [s for s in info.get("MediaSources") or [] if isinstance(s, dict) and s.get("Id")]
    if not sources:
        raise PlayError(409, "cannot_play", "Jellyfin has no playable file for this item.", reason="NoMediaSource")
    return sources[0]


# ---- request bodies ----

async def _body(request: Request) -> dict:
    """The JSON object body, whatever its Content-Type (navigator.sendBeacon posts text/plain)."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise PlayError(400, "bad_request", "Bad Content-Length.") from None
    if declared > MAX_BODY:
        raise PlayError(413, "too_large", "Request body over 64 KB.")
    chunks, size = [], 0
    async for chunk in request.stream():   # capped while reading: a chunked body has no Content-Length
        size += len(chunk)
        if size > MAX_BODY:
            raise PlayError(413, "too_large", "Request body over 64 KB.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if len(raw) > MAX_BODY:
        raise PlayError(413, "too_large", "Request body over 64 KB.")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise PlayError(400, "bad_request", "Body is not JSON.") from None
    if not isinstance(data, dict):
        raise PlayError(400, "bad_request", "Body must be a JSON object.")
    return data


def _item_id(value) -> str:
    text = value.replace("-", "").lower() if isinstance(value, str) else ""
    if not _HEX32.fullmatch(text):
        raise PlayError(400, "bad_request", "item_id must be a Jellyfin item id.")
    return text


def _int(data: dict, name: str, low: int, required: bool = False):
    value = data.get(name)
    if value is None:
        if required:
            raise PlayError(400, "bad_request", f"{name} is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise PlayError(400, "bad_request", f"{name} must be a whole number of at least {low}.")
    return value


# ---- sessions ----

def _prune(now: float) -> None:
    for sid in [s for s, v in SESSIONS.items() if now - v["seen"] > IDLE_S]:
        del SESSIONS[sid]


def _keep(sess: dict) -> str:
    sid = secrets.token_urlsafe(16)
    now = time.time()
    with _lock:
        _prune(now)
        # JY-237: sort on `seen` alone (stable, so insertion order breaks a tie). The clock ticks ~16 ms on Windows, so
        # sessions started back to back share a `seen`, and tying on the random sid dropped a random one, not the oldest.
        mine = sorted(((v["seen"], s) for s, v in SESSIONS.items() if v["owner"] == sess["owner"]),
                      key=lambda t: t[0])
        for _, old in mine[: max(0, len(mine) - MAX_PER_OWNER + 1)]:
            del SESSIONS[old]
        SESSIONS[sid] = {**sess, "seen": now}
    return sid


def _session(sid: str, owner: str, drop: bool = False) -> dict:
    with _lock:
        _prune(time.time())
        sess = SESSIONS.get(sid)
        if sess is None or sess["owner"] != owner:
            raise PlayError(404, "session_unknown", "No such playback session. Start a new one.")
        if drop:
            del SESSIONS[sid]
        else:
            sess["seen"] = time.time()
        return sess


def _report_body(sess: dict, position: int, paused: bool | None = None) -> dict:
    body = {"ItemId": sess["item_id"], "MediaSourceId": sess["media_source_id"],
            "PlaySessionId": sess["play_session_id"], "PositionTicks": position, "PlayMethod": sess["jf_method"],
            "CanSeek": True}
    if paused is not None:
        body["IsPaused"] = paused
    if sess.get("audio_index") is not None:
        body["AudioStreamIndex"] = sess["audio_index"]
    if sess.get("subtitle_index") is not None:
        body["SubtitleStreamIndex"] = sess["subtitle_index"]
    return body


# ---- the work, run in the threadpool ----

def _start(viewer: dict, item: str, kind: str, profile: dict, opts: dict) -> tuple[str, dict]:
    base, public = _bases()
    headers = _auth(viewer, kind)
    uid = _user_id(viewer, base, headers)
    _check_owner(viewer, uid)
    facts = _item_facts(base, headers, uid, item) if opts.pop("resume", False) else {"position": 0, "chapters": []}
    resumed = opts.get("start_ticks") is None and facts["position"] > 0
    if resumed:
        opts = {**opts, "start_ticks": facts["position"]}
    browser = kind in BROWSERS
    body = {"UserId": uid, "DeviceProfile": profile, "EnableDirectPlay": not browser, "EnableDirectStream": True,
            "EnableTranscoding": True, "AllowVideoStreamCopy": True, "AllowAudioStreamCopy": True,
            "AutoOpenLiveStream": False}
    for key, name in (("StartTimeTicks", "start_ticks"), ("AudioStreamIndex", "audio_index"),
                      ("SubtitleStreamIndex", "subtitle_index"), ("MaxStreamingBitrate", "max_bitrate")):
        if opts.get(name) is not None:
            body[key] = opts[name]
    info = _call("start", "POST", f"{base}/Items/{item}/PlaybackInfo", headers, params={"userId": uid}, body=body,
                 not_found="item_not_found")
    source = _first_source(info)
    if source.get("SupportsDirectPlay") and not browser:
        jf_method = "DirectPlay"
        query = {"static": "true", "mediaSourceId": source["Id"]}
        if info.get("PlaySessionId"):
            query["playSessionId"] = info["PlaySessionId"]
        url, protocol = f"{public}/Videos/{item}/stream?{urlencode(query)}", "file"
    elif source.get("TranscodingUrl"):
        jf_method = "DirectStream" if source.get("SupportsDirectStream") else "Transcode"
        url = _strip_key(source["TranscodingUrl"], public)
        protocol = "hls" if (source.get("TranscodingSubProtocol") or "").lower() == "hls" else "file"
    else:
        raise PlayError(409, "cannot_play", "Jellyfin offered no way to play this here.", reason="NoCompatibleStream")
    tracks = _tracks(source, public)
    sess = {"owner": viewer["owner"], "kind": kind, "item_id": item, "media_source_id": source["Id"],
            "play_session_id": info.get("PlaySessionId"), "jf_method": jf_method, "url": url, "protocol": protocol,
            "audio_index": opts.get("audio_index", tracks["default_audio_index"]),
            "subtitle_index": opts.get("subtitle_index", tracks["default_subtitle_index"]), "reported": False}
    if sess["subtitle_index"] is None:   # Jellyfin's "none" is a null default; the contract says -1 = off
        sess["subtitle_index"] = -1
    sid = _keep(sess)
    log.info("player: start %s %s", kind, METHODS[jf_method])
    return sid, {"session_id": sid, "item_id": item, "play_method": METHODS[jf_method],
                 "media_source_id": source["Id"], "container": source.get("Container"),
                 "runtime_ticks": source.get("RunTimeTicks"), "start_ticks": opts.get("start_ticks") or 0,
                 "audio_index": sess["audio_index"], "subtitle_index": sess["subtitle_index"],
                 "tracks": tracks, "heartbeat_s": HEARTBEAT_S,
                 "stream": f"{PREFIX}/sessions/{sid}/stream",
                 "resumed": resumed, "chapters": facts["chapters"], "up_next": _up_next(item)}


def _tracks_of(viewer: dict, item: str) -> dict:
    base, public = _bases()
    headers = _auth(viewer, "web")
    uid = _user_id(viewer, base, headers)
    info = _call("tracks", "GET", f"{base}/Items/{item}/PlaybackInfo", headers, params={"userId": uid},
                 not_found="item_not_found")
    source = _first_source(info)
    return {"item_id": item, "media_source_id": source["Id"], **_tracks(source, public)}


def _report(viewer: dict, sess: dict, position: int, paused: bool, stop: bool) -> None:
    base, _ = _bases()
    headers = _auth(viewer, sess["kind"])
    if stop:
        path, op, body = "/Sessions/Playing/Stopped", "stop", _report_body(sess, position)
    elif not sess["reported"]:
        path, op, body = "/Sessions/Playing", "progress", _report_body(sess, position, paused)
    else:
        path, op, body = "/Sessions/Playing/Progress", "progress", _report_body(sess, position, paused)
    _call(op, "POST", f"{base}{path}", headers, body=body, want_json=False)
    if not stop:
        with _lock:
            sess["reported"] = True


# ---- routes ----

@router.post(f"{PREFIX}/sessions")
async def start_session(request: Request):
    _gate(request)
    try:
        _same_site(request)
        viewer = _viewer(request)
        data = await _body(request)
        item = _item_id(data.get("item_id"))
        device = data.get("device")
        if not isinstance(device, dict) or device.get("kind") not in KINDS:
            raise PlayError(400, "bad_request", "device.kind must be web, phone or tv.")
        if not isinstance(device.get("profile"), dict) or not device["profile"]:
            raise PlayError(400, "bad_request", "device.profile must be a Jellyfin DeviceProfile object.")
        opts = {"start_ticks": _int(data, "start_ticks", 0), "audio_index": _int(data, "audio_index", 0),
                "subtitle_index": _int(data, "subtitle_index", -1), "max_bitrate": _int(data, "max_bitrate", 1)}
        opts = {k: v for k, v in opts.items() if v is not None}
        resume = data.get("resume")   # JY-054: the member's own resume point + chapters (one more read); null = left out
        if resume is not None and not isinstance(resume, bool):
            raise PlayError(400, "bad_request", "resume must be true or false.")
        if resume:
            opts["resume"] = True
        sid, answer = await run_in_threadpool(_start, viewer, item, device["kind"], device["profile"], opts)
    except PlayError as err:
        return _error(err)
    resp = _no_store(JSONResponse(answer, status_code=201))
    resp.headers["Location"] = f"{PREFIX}/sessions/{sid}"
    return resp


@router.post(f"{PREFIX}/sessions/{{session_id}}/stream")
async def stream(request: Request, session_id: str):
    _gate(request)
    try:
        _same_site(request)
        viewer = _viewer(request)
        _bases()
        sess = _session(session_id, viewer["owner"])
    except PlayError as err:
        return _error(err)
    return _no_store(JSONResponse({"url": sess["url"], "protocol": sess["protocol"],
                                   "play_method": METHODS[sess["jf_method"]],
                                   "headers": _auth(viewer, sess["kind"])}))


@router.post(f"{PREFIX}/sessions/{{session_id}}/progress")
async def progress(request: Request, session_id: str):
    _gate(request)
    try:
        _same_site(request)
        viewer = _viewer(request)
        data = await _body(request)
        position = _int(data, "position_ticks", 0, required=True)
        paused = data.get("paused", False)
        if not isinstance(paused, bool):
            raise PlayError(400, "bad_request", "paused must be true or false.")
        sess = _session(session_id, viewer["owner"])
        await run_in_threadpool(_report, viewer, sess, position, paused, False)
    except PlayError as err:
        return _error(err)
    return _no_store(Response(status_code=204))


@router.post(f"{PREFIX}/sessions/{{session_id}}/stop")
async def stop(request: Request, session_id: str):
    _gate(request)
    try:
        _same_site(request)
        viewer = _viewer(request)
        data = await _body(request)
        position = _int(data, "position_ticks", 0, required=True)
        sess = _session(session_id, viewer["owner"], drop=True)
        try:
            await run_in_threadpool(_report, viewer, sess, position, False, True)
        finally:   # JY-055: the title page re-reads the member's new position, whatever Jellyfin answered
            from hub import media_item   # lazy: media_item pulls in the library modules
            media_item.invalidate()
    except PlayError as err:
        return _error(err)
    return _no_store(Response(status_code=204))


@router.get(f"{PREFIX}/items/{{item_id}}/tracks")
async def tracks(request: Request, item_id: str):
    _gate(request)
    try:
        viewer = _viewer(request)
        answer = await run_in_threadpool(_tracks_of, viewer, _item_id(item_id))
    except PlayError as err:
        return _error(err)
    return _no_store(JSONResponse(answer))


class FlagOffRoute(Route):
    """JY-054 verifier must-fix (2026-10-27): while PLAYER_API is off, EVERY method on a player prefix (TRACE,
    PROPFIND, a made-up one) answers what an unknown path answers. The method-filtered routes left those a 405 with an
    Allow header naming the route. Registered FIRST in hub.main's router: off, it matches any method on its path and
    raises the router's own 404 (the app's handler draws it, byte for byte the unknown path's); on, it never matches,
    so the routes behind it answer exactly as before. Its `methods` mirror the catch-all's, so the guest tables
    classify it with the same (method, path) pairs."""

    def __init__(self, path: str):
        super().__init__(path, endpoint=_flag_off, methods=ALL_METHODS, include_in_schema=False)

    def matches(self, scope):
        if scope.get("type") == "http" and not enabled() and self.path_regex.match(scope.get("path", "")):
            return Match.FULL, {}
        return Match.NONE, {}

    async def handle(self, scope, receive, send):
        raise HTTPException(404)


async def _flag_off(request: Request):   # never called: FlagOffRoute.handle answers first
    raise HTTPException(404)


def flag_off_routes(*prefixes: str) -> list:
    """`<prefix>` and `<prefix>/{rest:path}` for each player prefix (this API's and the player page's)."""
    return [FlagOffRoute(p) for prefix in prefixes for p in (prefix, f"{prefix}/{{rest:path}}")]


@router.api_route(PREFIX, methods=ALL_METHODS, include_in_schema=False)
@router.api_route(f"{PREFIX}/{{rest:path}}", methods=ALL_METHODS, include_in_schema=False)
async def not_found(request: Request):
    """Registered LAST: a wrong method on a real path, any other path under /api/play, and bare /api/play (else
    redirect_slashes answers it 307 to /api/play/, naming the prefix). Flag off: the unknown-path 404 (never a 405 with
    an Allow header, never a redirect). Flag on: the same 404."""
    _gate(request)
    raise HTTPException(404)
