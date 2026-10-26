# Playback contract (JY-053)

The agreement between Joey's players (JY-054 web and phone, JY-057 TV shell) and the hub. The hub owns the session and
talks to Jellyfin; the player owns the video element and the bytes. Spec: `docs/specs/JY-053-playback-contract.md`.
Code: `hub/player_api.py`. Tests: `tests/hub/test_player_api.py` (fake Jellyfin, no live call).

Status: built 2026-10-26 behind `PLAYER_API`, **off**. Changing a request or response field is a dated line in the spec
plus the tests, never a silent edit: the players are built against this page.

## The flag

`PLAYER_API=on` (hub env; case and spaces forgiven) turns the API on. Any other value, or unset, is off. Off, every
route below answers exactly what an unknown path answers (`404 {"detail":"Not Found"}` on the private front, the
ordinary Joey 404 page on the media front), before auth, body parsing or any Jellyfin call. Nothing a user can see
changes while it is off. The flag is read on every request: no restart is needed to turn it off. A wrong method on a
real path, any other path under `/api/play/`, and bare `/api/play` land on a method-agnostic catch-all that answers the
same 404, so there is never a `405`, an `Allow` header or a `307` to `/api/play/` to say a route exists (review rounds
1 and 2, 2026-10-26).

## Who may call

Household only (JY-050 Q2 A). Friends stay on the official Jellyfin app until JY-058.

| Front | Caller | Answer |
|---|---|---|
| Private (`joeyhome.net`, Cloudflare Access) | `you` or `her` (Access email) | served, as that member's own Jellyfin user |
| Private | no Access identity, or `OWNER_EMAIL_YOU` unset | `401 not_signed_in` |
| Media (`media.joeyhome.net`) | anyone, friend or household alias, signed in or not | the ordinary Joey 404: every route is `PRIVATE` in `hub/guest.py` |
| Media, once JY-057 moves the routes to `GUEST` (Q3) | household alias | served with the alias's own session token |
| Media, once moved | friend (`jf:<id>`) | `403 not_allowed` (the handler checks too, so moving the routes never opens them to friends) |

Every POST also passes the hub's `same_origin` guard (a cross-site POST is `403 cross_site`).

## Jellyfin identity and the header

- **Private front (Q1 A):** each household member has one Jellyfin access token of their own, made once by signing a
  "Joey player" device in, kept in the NAS env as `JELLYFIN_PLAYER_TOKEN_YOU` / `JELLYFIN_PLAYER_TOKEN_HER`. Never the
  admin `JELLYFIN_API_KEY`. The user id comes from `GET /Users/Me` with that token, kept 1 h. Unset = `503 not_configured`.
- **Media front (after JY-057):** the signed-in session's own token and user id (`Identity.jf_token`, `jf_user_id`).
- Every call sends the Jellyfin 12.2 header and nothing else (no `X-Emby-*`, no key in a query):
  `Authorization: MediaBrowser Client="Joey", Device="Joey player <kind>", DeviceId="<id>", Version="0.1.0", Token="<token>"`.
  `DeviceId` is `joey-player-<owner>` on the private front (one Jellyfin device per member) and the browser's
  `__Host-jm_dev` on the media front.
- Hub to Jellyfin goes to `JELLYFIN_URL` (the LAN address). Streams are handed out on `JELLYFIN_PUBLIC_URL`
  (`https://jellyfin.joeyhome.net:8443`, the SWAG edge), **never the Cloudflare tunnel**. Unset = `503 not_configured`.
- **No credential in a URL (Q2 A).** The hub strips `ApiKey` / `api_key` from every URL Jellyfin returns. The stream
  hand-out gives the player the header to send on every stream, playlist, segment and subtitle request (hls.js
  `xhrSetup`, ExoPlayer `setDefaultRequestProperties`).
- **The web path (Q4 A).** A plain `<video src>` or `<track src>` cannot send a header, so browsers (`kind` `web` and
  `phone`) never direct-play: the hub sends PlaybackInfo with `EnableDirectPlay: false` for them and ignores a direct-play
  offer, so even a browser-ready MP4 comes as Jellyfin's HLS remux (video and audio copied, low CPU), played by hls.js
  with the header. Subtitles reach a browser inside that HLS stream: the web profile lists every text format in
  `SubtitleProfiles` with `Method: "Hls"` (image formats, PGS and VobSub, are burned in by Jellyfin, as today). Nothing
  ever sits in a `<video src>` or `<track src>` URL. The TV (ExoPlayer) direct-plays with the header.
- **iPhone and iPad (B.'s phone is an iPhone 15 Pro).** The `phone` player is hls.js 1.5 or later over
  `ManagedMediaSource` (iOS 17.1+), with `disableRemotePlayback` set on the video element: no AirPlay for now. It never
  falls back to Safari's native HLS (`canPlayType('application/vnd.apple.mpegurl')` with the URL in `src`): native HLS
  sends no header, so every request would be a 401. iOS below 17.1 has no `ManagedMediaSource` and is unsupported until
  Q4 B (an edge-checked stream token) is built; the player says so in words instead of trying. AirPlay comes with Q4 B too.
- **The header carries the member's full Jellyfin token** (it is not scoped to one stream; Jellyfin has no scoped
  tokens). JY-054 and JY-057 keep it in memory only: never `localStorage`, a cookie, a URL, a log or an error report.

## Endpoints

All bodies are JSON (at most 64 KB: a larger `Content-Length` is refused before the body is read, and a chunked body
is cut off as soon as it passes 64 KB; the
`Content-Type` is not checked, so a `sendBeacon` text/plain body works). All answers carry `Cache-Control: no-store`. Ticks are Jellyfin ticks
(10,000,000 per second). Item ids are Jellyfin ids, 32 hex (dashes and upper case accepted, answered lower case).

### 1. Start a session: `POST /api/play/sessions`

Request:
```json
{"item_id": "dcd12e5b...", "device": {"kind": "web", "profile": {"...": "a Jellyfin DeviceProfile"}},
 "start_ticks": 0, "audio_index": 1, "subtitle_index": -1, "max_bitrate": 20000000}
```
`device.kind` is `web`, `phone` or `tv`; `device.profile` is required and passed to Jellyfin as is (what this device
decodes, built by the player). `start_ticks`, `audio_index`, `subtitle_index` (`-1` = off) and `max_bitrate` (bits/s) are
optional: left out, Jellyfin applies the user's saved defaults (JY-050 Q5 A) and the user's bitrate setting (Q3 A).

Jellyfin: `POST /Items/{id}/PlaybackInfo?userId=<uid>` with `UserId`, `DeviceProfile`, `EnableDirectStream`,
`EnableTranscoding`, `AllowVideoStreamCopy`, `AllowAudioStreamCopy` all true, `EnableDirectPlay` true for `tv` and
false for `web` and `phone` (Q4 A), `AutoOpenLiveStream` false, and the optional fields as `StartTimeTicks`, `AudioStreamIndex`, `SubtitleStreamIndex`,
`MaxStreamingBitrate`. The first `MediaSource` is used (no library item has more than one, JY-051 inventory).
(Plus `GET /Users/Me` once per token per hour on the private front.)

`201`, `Location: /api/play/sessions/<session_id>`:
```json
{"session_id": "...", "item_id": "...", "play_method": "direct", "media_source_id": "...", "container": "mp4",
 "runtime_ticks": 26400000000, "start_ticks": 0, "audio_index": 1, "subtitle_index": -1,
 "tracks": {"...": "as endpoint 5, without item_id and media_source_id"},
 "heartbeat_s": 10, "stream": "/api/play/sessions/<session_id>/stream"}
```
`play_method` (JY-050's words): `direct` = Jellyfin `SupportsDirectPlay` (`PlayMethod` DirectPlay); `remux` = a
`TranscodingUrl` with `SupportsDirectStream` (DirectStream: container changed, codecs copied); `transcode` = a
`TranscodingUrl` without it (Transcode: audio and/or video re-encoded). No direct play and no `TranscodingUrl`, or a
PlaybackInfo `ErrorCode`, is `409 cannot_play` with `reason` (Jellyfin's code, e.g. `NoCompatibleStream`).

### 2. Stream hand-out: `POST /api/play/sessions/{session_id}/stream`

No body, **no Jellyfin call**. `200`:
```json
{"url": "https://jellyfin.joeyhome.net:8443/Videos/<id>/stream?static=true&mediaSourceId=...&playSessionId=...",
 "protocol": "file", "play_method": "direct",
 "headers": {"Authorization": "MediaBrowser Client=\"Joey\", ..., Token=\"...\""}}
```
- `direct`: `/Videos/{id}/stream?static=true&mediaSourceId=&playSessionId=` (Jellyfin's direct file, range requests).
- `remux` / `transcode`: Jellyfin's `TranscodingUrl` (`/videos/{id}/master.m3u8?...`), key removed, on the public
  base; `protocol` is `hls` when `TranscodingSubProtocol` is `hls`, else `file`.
POST, not GET, because the answer carries the token: it can be fetched again any time in the session (a reload, a
player restart), never cached.

### 3. Progress / heartbeat: `POST /api/play/sessions/{session_id}/progress`

`{"position_ticks": 123450000, "paused": false}`. `204`. Every `heartbeat_s` (10 s) while the player is open, and at
once on pause, resume and seek. Jellyfin: the first call is `POST /Sessions/Playing`, later ones
`POST /Sessions/Playing/Progress`, body `ItemId`, `MediaSourceId`, `PlaySessionId`, `PositionTicks`, `IsPaused`,
`PlayMethod`, `CanSeek`, `AudioStreamIndex`, `SubtitleStreamIndex`. Jellyfin keeps the resume point and the watched
mark (JY-050 Q6 A), so the hub stores no progress; the play recorder sees these plays like any other Jellyfin client's.
A failed heartbeat is not fatal: the player carries on and sends the next one.

### 4. Stop: `POST /api/play/sessions/{session_id}/stop`

`{"position_ticks": 3000000000}`. `204`. Jellyfin: `POST /Sessions/Playing/Stopped` (same body, no `IsPaused`), which
also ends any transcode for that `PlaySessionId`. The session is gone after this call whatever Jellyfin answered.

When the tab closes, the web player sends stop with `navigator.sendBeacon(url, JSON.stringify({position_ticks}))`
from `pagehide`. That posts a `text/plain` body with the page's own `Origin`, which the hub accepts: every body is read as
JSON whatever its `Content-Type` (pinned by `test_stop_by_send_beacon_text_plain`). The beacon's answer is never read;
if it is lost, Jellyfin keeps the last heartbeat's position (at most 10 s old) and the hub forgets the session after
30 minutes.

### 5. Audio and subtitle tracks: `GET /api/play/items/{item_id}/tracks`

Jellyfin: `GET /Items/{id}/PlaybackInfo?userId=<uid>` (no device profile, read only). `200`:
```json
{"item_id": "...", "media_source_id": "...", "default_audio_index": 1, "default_subtitle_index": -1,
 "audio": [{"index": 1, "language": "eng", "title": "English AAC 2.0", "codec": "aac", "default": true, "channels": 2}],
 "subtitles": [{"index": 3, "language": "eng", "title": "English SRT", "codec": "subrip", "default": false,
                "forced": false, "external": true, "text": true, "delivery": "external",
                "url": "https://jellyfin.joeyhome.net:8443/Videos/.../Stream.vtt"}]}
```
`index` is Jellyfin's `MediaStream.Index`; subtitle `-1` = off, and a null Jellyfin default is answered as `-1`.
`text: false` (PGS, VobSub) means a burn-in transcode when chosen. `url` is for the TV only (ExoPlayer sends the
header); a browser takes subtitles from the HLS stream (Q4 A).
`delivery` and `url` come from Jellyfin when it has a delivery for that track (key removed). Changing a track mid-play
= stop this session and start a new one at the current position with the new `audio_index` / `subtitle_index`
(Jellyfin decides again whether that needs a transcode). JY-056 may add a lighter path.

## Sessions

Kept in the hub process only: a random `session_id`, its owner, the item, the media source, Jellyfin's
`PlaySessionId`, the play method and the stream URL. Never the token. A session belongs to its owner (anyone else gets
`404 session_unknown`), is forgotten after 30 minutes with no call, and a member's fifth session drops their oldest. A
hub restart forgets all of them: the player gets `404 session_unknown` and starts a new session at its position.

## Errors

Every refusal past the flag is one shape, with no Jellyfin URL, token, user name or title in it:
```json
{"error": {"code": "upstream_timeout", "message": "Jellyfin did not answer in time.", "retry": true}}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | body not JSON, wrong type, bad id or index, missing field |
| 401 | `not_signed_in` | no household identity |
| 403 | `not_allowed` | a friend |
| 403 | `cross_site` | a POST from another site |
| 404 | `session_unknown` | no such session for this caller (expired, stopped, restarted, someone else's) |
| 404 | `item_not_found` | Jellyfin 404 on the item |
| 409 | `cannot_play` | Jellyfin offers no way to play it with this profile; `reason` = Jellyfin's code |
| 413 | `too_large` | body over 64 KB |
| 502 | `upstream_unreachable` | no connection to Jellyfin (`retry: true`) |
| 502 | `upstream_refused` | Jellyfin 401/403 on the player's token |
| 502 | `upstream_error` | any other non-2xx (`retry: true` for 5xx) or an unreadable answer |
| 503 | `not_configured` | `JELLYFIN_URL`, `JELLYFIN_PUBLIC_URL` or the member's player token unset |
| 504 | `upstream_timeout` | Jellyfin did not answer inside the timeout (`retry: true`) |

## Timeouts and budgets

CLAUDE.md rule 7 holds: no page render calls Jellyfin. These are API calls the player makes after a press, each with at
most one Jellyfin call (two on the first start per token per hour, with `/Users/Me`).

| Endpoint | Jellyfin calls | Connect / read timeout | Worst case answer |
|---|---|---|---|
| start | PlaybackInfo (+ `/Users/Me` once an hour) | 2 s / 4 s (`/Users/Me` 3 s) | about 6 s, then 504 |
| stream | none | none | hub only |
| progress | Sessions/Playing or /Progress | 2 s / 3 s | about 5 s, then 504 |
| stop | Sessions/Playing/Stopped | 2 s / 3 s | about 5 s, then 504 |
| tracks | PlaybackInfo (GET) | 2 s / 4 s | about 6 s, then 504 |

- **Hub overhead** (everything but the Jellyfin wait): p95 <= 50 ms per endpoint, the hub page-render budget. Measured
  with the fake Jellyfin in `test_hub_overhead_is_inside_the_page_budget`; re-measured inside joey-hub when JY-054 turns
  the flag on.
- **Press to first frame** (JY-050 Q8 A: 5 s LAN, 10 s remote) is the player's budget: start + stream + Jellyfin's
  first bytes. The 4 s start timeout keeps a stuck Jellyfin inside the remote target with a word on screen.
- Memory: at most 4 sessions per member, a few hundred bytes each.

## Jellyfin 12.2 facts this rests on, and what is still to verify

Verified (JY-051 inventory, 2026-10-24): `POST /Items/{id}/PlaybackInfo?userId=` answers all 12 test files with the
12.2 header; the bare API key without a user is a 400. Still to verify in the JY-051 sitting or JY-054 (V):
- Jellyfin serves HLS playlists and segments to the header alone, with no `ApiKey` in the master URL (T2H uses it).
- `/Users/Me` and `/Sessions/Playing*` accept a user token with a constant `DeviceId` from several devices at once.
- `Sessions/Playing/Stopped` ends the transcode job on 12.2 (else the hub adds `DELETE /Videos/ActiveEncodings`).
- CORS on the :8443 edge for the browser player (JY-051: Jellyfin's own default, any origin).
- The HLS master playlist carries the chosen text subtitle as a WebVTT rendition that hls.js shows; 12.2 may need
  `EnableSubtitlesInManifest=true` on the `TranscodingUrl` (the hub would add it for `web` / `phone`).
- hls.js over `ManagedMediaSource` on the iPhone 15 Pro: starts, sends the header on every request, and plays HEVC
  remuxes (JY-051's phone leg).
