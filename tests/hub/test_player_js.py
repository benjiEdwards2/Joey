"""JY-054 (2026-10-27): the player's own logic (hub/static/player.js) under node, with a fake hls.js, a fake fetch, a
fake <video> and manual timers, as tests/hub/test_history_replace.py runs the shell hooks. Start -> stream -> hls.js ->
progress -> stop / sendBeacon, the track picker's restart, the hub forgetting a session, words when hls.js can't run,
the device profile, the desktop keys and the phone's taps. Tokens and hosts are invented; no network."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER = REPO_ROOT / "hub" / "static" / "player.js"
TOKEN = "tok-js-SECRET-42"

HARNESS = r"""
'use strict';
var P = require(%(player)s);
var TOKEN = %(token)s;
var AUTH = 'MediaBrowser Client="Joey", Device="Joey player web", DeviceId="joey-player-you", Version="0.1.0", Token="' + TOKEN + '"';
var STREAM_URL = 'https://jf-public.test:8443/videos/abc/master.m3u8?MediaSourceId=src1&PlaySessionId=ps1';
var stored = [];
global.localStorage = {setItem: function (k, v) { stored.push([k, v]); }};
global.sessionStorage = global.localStorage;

function flush() { return new Promise(function (r) { setImmediate(r); }); }
async function settle() { for (var i = 0; i < 12; i++) await flush(); }

function Resp(status, body) {
  return {status: status, ok: status >= 200 && status < 300,
          json: function () { return body === undefined ? Promise.reject(new Error('no body')) : Promise.resolve(body); }};
}

function world(opt) {
  opt = opt || {};
  var w = {calls: [], beacons: [], hls: [], events: [], timers: {}, nextTimer: 1, srcSet: [], n: 0};
  var answers = opt.answers || {};
  w.fetch = function (url, init) {
    var body = init && init.body ? JSON.parse(init.body) : undefined;
    w.calls.push({url: url, method: init.method, body: body, keepalive: !!init.keepalive, raw: init.body || ''});
    var m;
    if (url === '/api/play/sessions') {
      if (answers.start) return Promise.resolve(answers.start(body));
      w.n += 1;
      return Promise.resolve(Resp(201, {session_id: 'S' + w.n, play_method: 'remux', start_ticks: body.start_ticks || (body.resume ? 14210000000 : 0),
        resumed: !!body.resume, runtime_ticks: 26400000000, heartbeat_s: 10,
        audio_index: body.audio_index === undefined ? 1 : body.audio_index,
        subtitle_index: body.subtitle_index === undefined ? -1 : body.subtitle_index,
        tracks: {audio: [{index: 1, title: 'English AAC', channels: 2}], subtitles: [{index: 3, title: 'English SRT', text: true}]},
        chapters: body.resume ? [{name: 'Cold open', start_ticks: 0}, {name: 'The ferry', start_ticks: 3790000000}] : [],
        stream: '/api/play/sessions/S' + w.n + '/stream'}));
    }
    if ((m = /^\/api\/play\/sessions\/(S\d+)\/stream$/.exec(url))) {
      return Promise.resolve(Resp(200, {url: STREAM_URL, protocol: opt.protocol || 'hls', play_method: 'remux',
                                        headers: {Authorization: AUTH}}));
    }
    if (/\/progress$/.test(url)) return Promise.resolve(answers.progress ? answers.progress(url) : Resp(204));
    if (/\/stop$/.test(url)) return Promise.resolve(Resp(204));
    return Promise.resolve(Resp(404, {detail: 'Not Found'}));
  };
  function FakeHls(config) {
    this.config = config; this.handlers = {}; this.loaded = null; this.media = null; this.destroyed = false;
    this.subtitleTracks = opt.subtitleTracks || []; this.subtitleTrack = -1; this.subtitleDisplay = null;
    this.startLoads = 0; this.recovers = 0;
    w.hls.push(this);
  }
  FakeHls.isSupported = function () { return opt.supported !== false; };
  FakeHls.Events = {MANIFEST_PARSED: 'hlsManifestParsed', ERROR: 'hlsError'};
  FakeHls.ErrorTypes = {NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError', OTHER_ERROR: 'otherError'};
  FakeHls.prototype.on = function (ev, fn) { this.handlers[ev] = fn; };
  FakeHls.prototype.emit = function (ev, data) { this.handlers[ev] && this.handlers[ev](ev, data); };
  FakeHls.prototype.loadSource = function (u) { this.loaded = u; };
  FakeHls.prototype.attachMedia = function (v) { this.media = v; };
  FakeHls.prototype.destroy = function () { this.destroyed = true; };
  FakeHls.prototype.startLoad = function () { this.startLoads += 1; };
  FakeHls.prototype.recoverMediaError = function () { this.recovers += 1; };
  w.Hls = FakeHls;
  var listeners = {};
  w.video = {currentTime: 0, paused: true, ended: false, plays: 0,
    addEventListener: function (n, f) { (listeners[n] = listeners[n] || []).push(f); },
    fire: function (n) { (listeners[n] || []).forEach(function (f) { f({type: n}); }); },
    play: function () { this.plays += 1; this.paused = false; return Promise.resolve(); },
    canPlayType: function () { w.events.push(['canPlayType']); return 'maybe'; }};
  Object.defineProperty(w.video, 'src', {set: function (v) { w.srcSet.push(v); }, get: function () { return ''; }});
  w.setInterval = function (fn, ms) { var id = w.nextTimer++; w.timers[id] = {fn: fn, ms: ms}; return id; };
  w.clearInterval = function (id) { delete w.timers[id]; };
  w.tick = function () { Object.keys(w.timers).forEach(function (k) { w.timers[k].fn(); }); };
  w.sendBeacon = function (url, body) { w.beacons.push({url: url, body: body, type: typeof body}); return true; };
  w.player = P.createPlayer({itemId: 'abc', kind: 'web', profile: P.deviceProfile('web', function () { return false; }),
    fetch: w.fetch, Hls: FakeHls, video: w.video, sendBeacon: w.sendBeacon, setInterval: w.setInterval,
    clearInterval: w.clearInterval, on: function (ev, data) { w.events.push([ev, data === undefined ? null : data]); }});
  return w;
}

function xhrHeaders(h, url) {
  var set = {};
  h.config.xhrSetup({setRequestHeader: function (k, v) { set[k] = v; }}, url);
  return set;
}

function leak(w) {   // the token anywhere but the hls.js header
  var bad = [];
  w.calls.forEach(function (c) { if ((c.url + c.raw).indexOf(TOKEN) >= 0) bad.push('fetch ' + c.url); });
  w.beacons.forEach(function (b) { if ((b.url + b.body).indexOf(TOKEN) >= 0) bad.push('beacon'); });
  w.events.forEach(function (e) { if (JSON.stringify(e).indexOf(TOKEN) >= 0) bad.push('event ' + e[0]); });
  if (JSON.stringify(stored).indexOf(TOKEN) >= 0 || stored.length) bad.push('storage');
  if (w.srcSet.length) bad.push('video.src');
  return bad;
}

var out = {};

async function happy() {
  var w = world();
  await w.player.start();
  await settle();
  var r = {};
  r.urls = w.calls.map(function (c) { return c.method + ' ' + c.url; });
  r.startBody = w.calls[0].body;
  var h = w.hls[0];
  r.hlsCount = w.hls.length;
  r.loaded = h.loaded; r.attached = h.media === w.video;
  r.startPosition = h.config.startPosition;
  r.sameOrigin = xhrHeaders(h, 'https://jf-public.test:8443/videos/abc/hls1/main/0.mp4');
  r.otherOrigin = xhrHeaders(h, 'https://elsewhere.test/x.m3u8');
  h.emit('hlsManifestParsed', {});
  await settle();
  r.plays = w.video.plays;
  r.subtitleDisplay = h.subtitleDisplay;
  w.video.fire('play');
  await settle();
  w.video.currentTime = 60;
  w.tick();
  await settle();
  w.video.paused = true; w.video.currentTime = 61.5; w.video.fire('pause');
  await settle();
  w.video.currentTime = 300; w.video.fire('seeked');
  await settle();
  r.progress = w.calls.filter(function (c) { return /progress$/.test(c.url); }).map(function (c) { return [c.url, c.body]; });
  r.timerMs = Object.keys(w.timers).map(function (k) { return w.timers[k].ms; });
  w.video.currentTime = 321.25;
  r.beaconSent = w.player.beacon();
  r.beaconAgain = w.player.beacon();
  await w.player.stop();
  await settle();
  r.beacons = w.beacons;
  r.stopFetches = w.calls.filter(function (c) { return /stop$/.test(c.url); }).length;
  r.timersAfter = Object.keys(w.timers).length;
  w.tick(); await settle();
  r.progressAfterStop = w.calls.filter(function (c) { return /progress$/.test(c.url); }).length - r.progress.length;
  r.events = w.events.map(function (e) { return e[0]; });
  r.resumed = w.events.filter(function (e) { return e[0] === 'resumed'; }).map(function (e) { return e[1]; });
  r.session = w.events.filter(function (e) { return e[0] === 'session'; })[0][1];
  r.leaks = leak(w);
  return r;
}

async function backStops() {
  var w = world();
  await w.player.start(); await settle();
  w.video.currentTime = 90;
  await w.player.stop(); await settle();
  var r = {stops: w.calls.filter(function (c) { return /stop$/.test(c.url); }).map(function (c) { return [c.url, c.body, c.keepalive]; })};
  r.beacon = w.player.beacon();
  r.beacons = w.beacons.length;
  r.leaks = leak(w);
  return r;
}

async function forgotten() {
  var calls = 0;
  var w = world({answers: {progress: function () {
    calls += 1;
    return calls === 1 ? Resp(404, {error: {code: 'session_unknown', message: 'No such playback session.'}}) : Resp(204);
  }}});
  await w.player.start(); await settle();
  w.video.currentTime = 700; w.video.paused = false;
  w.tick(); await settle();
  var starts = w.calls.filter(function (c) { return c.url === '/api/play/sessions'; });
  return {starts: starts.map(function (c) { return c.body; }), hls: w.hls.length, firstDestroyed: w.hls[0].destroyed,
          sid: w.player.state().sid, stops: w.calls.filter(function (c) { return /stop$/.test(c.url); }).length,
          leaks: leak(w)};
}

async function failedBeat() {
  var w = world({answers: {progress: function () { return Resp(502, {error: {code: 'upstream_error', message: 'x'}}); }}});
  await w.player.start(); await settle();
  w.tick(); await settle();
  return {sid: w.player.state().sid, errors: w.events.filter(function (e) { return e[0] === 'error'; }).length,
          starts: w.calls.filter(function (c) { return c.url === '/api/play/sessions'; }).length};
}

async function pickTracks() {
  var w = world({subtitleTracks: [{name: 'English'}]});
  await w.player.start(); await settle();
  w.video.currentTime = 1234.5;
  await w.player.switchTracks(1, -1);   // unchanged: nothing happens
  await settle();
  var before = w.calls.length;
  await w.player.switchTracks(2, 3);
  await settle();
  var after = w.calls.slice(before).map(function (c) { return [c.method + ' ' + c.url, c.body]; });
  w.hls[1].emit('hlsManifestParsed', {}); await settle();
  return {after: after, oldDestroyed: w.hls[0].destroyed, hls: w.hls.length,
          sub: w.player.state().sub, audio: w.player.state().audio, subTrack: w.hls[1].subtitleTrack,
          subDisplay: w.hls[1].subtitleDisplay, leaks: leak(w)};
}

async function unsupported() {
  var w = world({supported: false});
  await w.player.start(); await settle();
  return {calls: w.calls.length, hls: w.hls.length, errors: w.events.filter(function (e) { return e[0] === 'error'; }).map(function (e) { return e[1]; }),
          src: w.srcSet.length};
}

async function fileProtocol() {
  var w = world({protocol: 'file'});
  await w.player.start(); await settle();
  return {hls: w.hls.length, src: w.srcSet.length, stops: w.calls.filter(function (c) { return /stop$/.test(c.url); }).length,
          errors: w.events.filter(function (e) { return e[0] === 'error'; }).map(function (e) { return e[1]; })};
}

async function cannotPlay() {
  var w = world({answers: {start: function () {
    return Resp(409, {error: {code: 'cannot_play', message: 'Jellyfin can’t play this here.', reason: 'NoCompatibleStream'}});
  }}});
  await w.player.start(); await settle();
  var offline = world({answers: {start: function () { return Promise.reject(new TypeError('Failed to fetch')); }}});
  await offline.player.start(); await settle();
  return {urls: w.calls.map(function (c) { return c.url; }), errors: w.events.filter(function (e) { return e[0] === 'error'; }).map(function (e) { return e[1]; }),
          offline: offline.events.filter(function (e) { return e[0] === 'error'; }).map(function (e) { return e[1]; })};
}

async function fatalErrors() {
  var w = world();
  await w.player.start(); await settle();
  var h = w.hls[0];
  h.emit('hlsError', {fatal: false, type: 'networkError'});
  h.emit('hlsError', {fatal: true, type: 'networkError'});
  h.emit('hlsError', {fatal: true, type: 'mediaError'});
  var errorsBefore = w.events.filter(function (e) { return e[0] === 'error'; }).length;
  h.emit('hlsError', {fatal: true, type: 'networkError'});
  await settle();
  return {startLoads: h.startLoads, recovers: h.recovers, errorsBefore: errorsBefore,
          errors: w.events.filter(function (e) { return e[0] === 'error'; }).map(function (e) { return e[1]; }),
          destroyed: h.destroyed, stops: w.calls.filter(function (c) { return /stop$/.test(c.url); }).length};
}

function profile() {
  var hevc = P.deviceProfile('web', function (t) { return /hvc1|ec-3/.test(t); });
  var phone = P.deviceProfile('phone', function () { return false; });
  return {web: hevc, phone: phone};
}

function keys() {
  var cases = [[' ', 'BODY'], ['k', 'DIV'], ['ArrowLeft', 'BODY'], ['ArrowRight', 'BODY'], ['ArrowUp', 'BODY'],
               ['ArrowDown', 'BODY'], ['f', 'BODY'], ['m', 'BODY'], ['Escape', 'BODY'], ['x', 'BODY'],
               [' ', 'BUTTON'], ['Enter', 'A'], ['ArrowLeft', 'INPUT', 'range'], ['f', 'INPUT', 'text'], [' ', 'INPUT', 'range']];
  return cases.map(function (c) { return P.keyAction(c[0], c[1], c[2]); });
}

function taps() {
  var acts = [], timers = {}, id = 0;
  var setT = function (fn, ms) { id += 1; timers[id] = fn; return id; };
  var clearT = function (i) { delete timers[i]; };
  var runTimers = function () { Object.keys(timers).forEach(function (k) { var f = timers[k]; delete timers[k]; f(); }); };
  var tap = P.makeTapper(setT, clearT, function (a) { acts.push(a); }, 280);
  tap(100, 400, 1000); runTimers();                        // one tap: toggle
  tap(350, 400, 5000); tap(360, 400, 5200);                // double tap right: fwd, no toggle
  runTimers();
  tap(20, 400, 9000); tap(30, 400, 9100); tap(25, 400, 9300); runTimers();   // left double, then a third: back, back
  tap(20, 400, 12000); tap(380, 400, 12100); runTimers();  // left then right quickly: two single taps -> one toggle
  return acts;
}

(async function () {
  out.happy = await happy();
  out.back = await backStops();
  out.forgotten = await forgotten();
  out.failedBeat = await failedBeat();
  out.tracks = await pickTracks();
  out.unsupported = await unsupported();
  out.file = await fileProtocol();
  out.cannot = await cannotPlay();
  out.fatal = await fatalErrors();
  out.profile = profile();
  out.keys = keys();
  out.taps = taps();
  out.clock = [P.clock(0), P.clock(61.9), P.clock(1421), P.clock(3725)];
  process.stdout.write(JSON.stringify(out));
})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = tmp_path_factory.mktemp("player") / "harness.js"
    script.write_text(HARNESS % {"player": json.dumps(str(PLAYER)), "token": json.dumps(TOKEN)}, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_start_then_stream_then_hls_with_the_header_only_to_the_stream_origin(run):
    r = run["happy"]
    assert r["urls"][:2] == ["POST /api/play/sessions", "POST /api/play/sessions/S1/stream"]
    body = r["startBody"]
    assert body["item_id"] == "abc" and body["device"]["kind"] == "web" and body["resume"] is True
    assert "start_ticks" not in body and "audio_index" not in body and "subtitle_index" not in body
    tp = body["device"]["profile"]["TranscodingProfiles"][0]
    assert tp["Protocol"] == "hls" and tp["Container"] == "mp4" and tp["Context"] == "Streaming"
    assert r["hlsCount"] == 1 and r["attached"] and r["loaded"].startswith("https://jf-public.test:8443/videos/abc/")
    assert r["startPosition"] == pytest.approx(1421.0)          # the member's resume point, in seconds
    assert r["sameOrigin"] == {"Authorization": r["sameOrigin"].get("Authorization")}
    assert r["sameOrigin"]["Authorization"].endswith('Token="tok-js-SECRET-42"')
    assert r["otherOrigin"] == {}                               # never to another host
    assert r["plays"] == 1 and r["subtitleDisplay"] is False    # subtitles off (-1) by the member's default
    assert r["resumed"] == [14210000000] and "session" in r["events"]
    assert r["session"]["words"] == "Remux" and [c["name"] for c in r["session"]["chapters"]] == ["Cold open", "The ferry"]
    assert r["leaks"] == []


def test_progress_on_the_heartbeat_and_at_once_on_play_pause_and_seek(run):
    r = run["happy"]
    sent = [(url, b["position_ticks"], b["paused"]) for url, b in r["progress"]]
    assert all(url == "/api/play/sessions/S1/progress" for url, _, _ in sent)
    assert sent == [(sent[0][0], 0, False), (sent[0][0], 600_000_000, False), (sent[0][0], 615_000_000, True),
                    (sent[0][0], 3_000_000_000, True)]
    assert r["timerMs"] == [10_000]


def test_pagehide_sends_one_beacon_and_nothing_after(run):
    r = run["happy"]
    assert r["beaconSent"] is True and r["beaconAgain"] is False
    assert r["beacons"] == [{"url": "/api/play/sessions/S1/stop", "body": '{"position_ticks":3212500000}', "type": "string"}]
    assert r["stopFetches"] == 0 and r["timersAfter"] == 0 and r["progressAfterStop"] == 0


def test_back_to_joey_stops_once_with_keepalive(run):
    r = run["back"]
    assert r["stops"] == [["/api/play/sessions/S1/stop", {"position_ticks": 900_000_000}, True]]
    assert r["beacon"] is False and r["beacons"] == 0 and r["leaks"] == []


def test_a_forgotten_session_starts_a_new_one_at_the_position(run):
    r = run["forgotten"]
    assert r["starts"][1]["start_ticks"] == 7_000_000_000 and "resume" not in r["starts"][1]
    assert (r["starts"][1]["audio_index"], r["starts"][1]["subtitle_index"]) == (1, -1)
    assert r["hls"] == 2 and r["firstDestroyed"] and r["sid"] == "S2" and r["stops"] == 0 and r["leaks"] == []


def test_a_failed_heartbeat_is_not_fatal(run):
    assert run["failedBeat"] == {"sid": "S1", "errors": 0, "starts": 1}


def test_a_track_pick_stops_and_restarts_at_the_same_point(run):
    r = run["tracks"]
    urls = [u for u, _ in r["after"]]
    assert urls == ["POST /api/play/sessions/S1/stop", "POST /api/play/sessions", "POST /api/play/sessions/S2/stream"]
    assert r["after"][0][1] == {"position_ticks": 12_345_000_000}
    new = r["after"][1][1]
    assert (new["start_ticks"], new["audio_index"], new["subtitle_index"]) == (12_345_000_000, 2, 3)
    assert "resume" not in new
    assert r["oldDestroyed"] and r["hls"] == 2 and (r["audio"], r["sub"]) == (2, 3)
    assert r["subTrack"] == 0 and r["subDisplay"] is True and r["leaks"] == []


def test_no_hls_support_says_so_and_starts_nothing(run):
    r = run["unsupported"]
    assert r["calls"] == 0 and r["hls"] == 0 and r["src"] == 0
    assert r["errors"] and "iOS 17.1" in r["errors"][0]


def test_never_native_hls_or_a_video_src(run):
    r = run["file"]
    assert r["hls"] == 0 and r["src"] == 0 and r["stops"] == 1
    assert r["errors"] == ["This file can’t play in the browser yet."]
    assert "canPlayType" not in PLAYER.read_text(encoding="utf-8") and ".src =" not in PLAYER.read_text(encoding="utf-8")


def test_api_and_network_errors_are_words_and_no_stream_is_asked(run):
    r = run["cannot"]
    assert r["urls"] == ["/api/play/sessions"] and r["errors"] == ["Jellyfin can’t play this here."]
    assert r["offline"] and "Can’t reach Joey" in r["offline"][0] and "Failed to fetch" not in r["offline"][0]


def test_hls_fatal_errors_retry_once_then_stop_with_words(run):
    r = run["fatal"]
    assert (r["startLoads"], r["recovers"], r["errorsBefore"]) == (1, 1, 0)
    assert r["errors"] == ["Playback stopped. Try again, or go back to Joey."] and r["destroyed"] and r["stops"] == 1


def test_device_profile_asks_for_hls_with_what_the_browser_decodes(run):
    web, phone = run["profile"]["web"], run["profile"]["phone"]
    tp = web["TranscodingProfiles"][0]
    assert tp["VideoCodec"] == "h264,hevc" and tp["AudioCodec"] == "aac,mp3,eac3" and tp["MaxAudioChannels"] == "6"
    assert phone["TranscodingProfiles"][0]["VideoCodec"] == "h264" and phone["TranscodingProfiles"][0]["MaxAudioChannels"] == "2"
    subs = {s["Format"]: s["Method"] for s in web["SubtitleProfiles"]}
    assert subs["subrip"] == subs["vtt"] == subs["ass"] == "Hls" and subs["pgssub"] == subs["dvdsub"] == "Encode"
    assert phone["Name"] == "Joey player phone"


def test_desktop_keys(run):
    assert run["keys"] == ["toggle", "toggle", "back", "fwd", "volup", "voldown", "full", "mute", "close", None,
                           None, None, None, None, "toggle"]


def test_phone_taps_toggle_and_double_taps_seek(run):
    assert run["taps"] == ["toggle", "fwd", "back", "back", "toggle"]


def test_clock_words(run):
    assert run["clock"] == ["0:00", "1:01", "23:41", "1:02:05"]


def test_the_page_script_keeps_the_token_out_of_storage_cookies_and_logs():
    src = PLAYER.read_text(encoding="utf-8")
    for bad in ("localStorage", "sessionStorage", "document.cookie", "console.", "indexedDB"):
        assert bad not in src, bad
    assert "disableRemotePlayback = true" in src and "preferManagedMediaSource: true" in src


def test_vendored_hls_is_the_pinned_build():
    import hashlib
    data = (REPO_ROOT / "hub" / "static" / "hls.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == "72b87a6e58db623feca73ab370970c1126ec06eb3dcd0a67fd14b47b6340b820"
    assert len(data) == 543_243
    assert "Apache License" in (REPO_ROOT / "hub" / "static" / "LICENSE-hls.js.txt").read_text(encoding="utf-8")
