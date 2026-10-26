# JY-053 Playback-session endpoints (contract first)

Status: building
Size: M
Live risk: none while `PLAYER_API` is off (the default, and how this item ships). Turned on, progress and stop write the household's playback state to Jellyfin: that switch belongs to JY-054, live.
Area: `hub/player_api.py` (new), one router line in `hub/main.py`, the PRIVATE entries in `hub/guest.py`, `tests/hub/test_player_api.py` (new), two placeholders in `tests/hub/test_guest_routes.py`, `docs/playback-contract.md` (new), this spec, `hub/README.md`, `docs/connector-contract.md` (the twentieth exception), `deploy/.env.example` (three commented keys)
Needs: JY-050 (shipped). Informed by JY-051 (building; its inventory measured PlaybackInfo on 12.2)
Options page: none: no screen. The player screens are JY-052.

## Problem
HITLIST: "Contract before the players." JY-054 (web and phone) and JY-057 (TV shell) need one hub API to start a
playback session, get the stream, report progress, stop, and list tracks, so Joey plays the film itself instead of
handing off to the Jellyfin app (JY-050). JY-050 fixed the scope (B., 2026-10-24, "all recommended"): household only,
direct play then remux then transcode, the household follows its Jellyfin bitrate setting, Jellyfin's saved track
defaults, Jellyfin as the one resume record, start within 5 s on the LAN and 10 s remote. JY-051's draft fixed the
plumbing: the 12.2 `Authorization: MediaBrowser ... Token="..."` header only, and streams straight to Jellyfin's own
host (`jellyfin.joeyhome.net:8443`), never the Cloudflare tunnel.

The contract itself is `docs/playback-contract.md`. This spec says what was built and what B. decides.

## Acceptance criteria
1. `docs/playback-contract.md` covers the five endpoints (start with a device profile, stream hand-out, progress and
   heartbeat, stop, audio and subtitle tracks), auth per front, the Jellyfin 12.2 mapping of each, the header, the
   public stream host, error shapes, timeouts and budgets.
2. The endpoints are built in `hub/player_api.py` behind `PLAYER_API`, off by default. Off, every route answers
   byte for byte what an unknown path answers, for every caller, before any Jellyfin call.
3. Private front: no Access identity = 401; `you` and `her` are served as their own Jellyfin user. Media front: every
   route is the ordinary 404 (PRIVATE in `hub/guest.py`); if the routes are moved to GUEST, a friend still gets 403.
4. The hub never sends the admin key for a play, never puts a token in a URL it hands out (Jellyfin's `ApiKey` /
   `api_key` removed), and hands out stream URLs only on `JELLYFIN_PUBLIC_URL`.
5. Each Jellyfin-calling endpoint has a connect and read timeout; a timeout is `504 upstream_timeout` with
   `retry: true`, proven on a real socket that never answers.
6. Hub overhead p95 <= 50 ms per endpoint with a fake Jellyfin.
7. Logs carry no token, URL, user name or e-mail.
8. Tests first and red, then green; `tests/hub/` stays green; no live Jellyfin call in any test.
9. No UI and no template change: nothing user-visible changes while the flag is off.

## Data
No media.db change, no snapshot read. Sessions live in the hub process (`player_api.SESSIONS`). New env (hub only,
listed commented in `deploy/.env.example`): `PLAYER_API` (off), `JELLYFIN_PLAYER_TOKEN_YOU`, `JELLYFIN_PLAYER_TOKEN_HER`;
`JELLYFIN_PUBLIC_URL` (already in `media.env`) is now read by the private hub too, for the player only.

## Performance budget
Rule 7 holds: no page render calls Jellyfin; these are player API calls. Hub page render p95 <= 50 ms applies to the
hub's own time per call (measured with the fake Jellyfin; numbers in the PR). Jellyfin's own time is bounded by the
timeouts in the contract (start 2 s connect / 4 s read). Press to first frame (5 s LAN, 10 s remote) is measured in
JY-054 with the flag on, inside joey-hub on the NAS.

## Options and the pick
None: no screen.

## Out of scope
Any player or screen (JY-052, JY-054, JY-057); resume and watched beyond what Jellyfin does with the reports (JY-055);
the track picker UI (JY-056); friends (JY-058); turning the flag on, making the player tokens, any live call (JY-054);
the transcode box (JY-049, JY-059).

## Accept checklist
Nothing to try on a preview: the flag is off and there is no screen.
- Read `docs/playback-contract.md` and answer the four questions below (or "all recommended").
- In the PR: the test output, and that with the flag off `/api/play/sessions` answers `404 {"detail":"Not Found"}`
  like any unknown path.

## Questions for B.
Each was not settled by the JY-050 answers. The recommendation (A) is what is built. Q4 was added in review round 1.

**1. Which Jellyfin sign-in does a household play use on joeyhome.net?**
A) One Jellyfin token per person (`JELLYFIN_PLAYER_TOKEN_YOU` / `_HER` in the NAS env), made once in JY-054 by a script
that signs a "Joey player" device in with a Quick Connect code you approve on your phone. Plays and resume land on your
own Jellyfin user. B) Each browser signs in to Jellyfin itself (Quick Connect on the player, like friends on Joey Media),
so every device is its own Jellyfin device; needs a sign-in screen in JY-054. C) The hub's admin key with your user id.
*Recommend A: no screen needed, works today with the flag off, and B can replace it later behind the same code path.
C is out: the stream needs a credential the player holds, and the admin key must never reach a browser.*

**2. How does the player prove itself to Jellyfin for the video?**
A) Header only: the hub hands the player the `Authorization` header and a URL with no key in it; the TV (ExoPlayer) and
the web player (hls.js) send the header on every request. A plain `<video src>` cannot, so web direct play goes
through hls.js or Jellyfin's remux, which JY-051's PC rows will show the cost of. B) Also allow the token in the URL
(`ApiKey=`), as Jellyfin's own web client and the JY-051 study page do, so a plain `<video>` can direct-play; the
token then sits in the browser's history, its media cache and the edge's access log.
*Recommend A: matches the JY-051 brief ("the header only") and keeps tokens out of logs; revisit only if JY-051 shows
web direct play matters.*

**3. Where does the TV shell's player call these?**
The Joey TV shell loads Joey Media (`media.joeyhome.net`), where friends also sign in. A) Keep the routes private now;
JY-057 moves them to the media front for the household alias only (friends still refused, 403). B) Open them on the
media front for the household now. *Recommend A: nothing on the friends' host changes until a player uses it, and the
handler already refuses friends and plays as the signed-in household user there.*

**4. How does a browser play a file it could direct-play, and show external subtitles?**
A `<video src>` or `<track src>` cannot send the header (review round 1). A) Browsers never direct-play: the hub asks
Jellyfin for HLS (a remux, video and audio copied, low CPU) and the web profile asks for subtitles inside the HLS
stream, so hls.js sends the header for every byte. Costs a remux for the 4 % of files a browser could take as they are
(the JY-051 inventory). B) A short-lived per-session stream token in the URL, scoped to that one stream: Jellyfin has
no scoped tokens, so SWAG on :8443 would check it with `auth_request` against the hub (over the LAN, not the tunnel)
and add the real header itself before passing to Jellyfin; a SWAG change, built in JY-054 with the deploy review.
C) The hub proxies the video. *Recommend A: no new credential or edge change, no token in any URL; B only if the JY-051
PC rows show the remux hurts the 5 s start. C is out: video would cross the Cloudflare tunnel and the hub's 200 MiB.*

## Notes for JY-054
- The `/stream` answer's `headers.Authorization` carries the member's **full** Jellyfin token, not one scoped to the
  stream. The player keeps it in memory only (never `localStorage`, a cookie, a URL, a log or an error report) and
  fetches it again from `/stream` after a reload.
- Close the tab with `navigator.sendBeacon` to `/stop` (text/plain JSON; the contract's endpoint 4).

## Review round 1 (2026-10-26)
Security review FAIL, one must-fix: with the flag off, a wrong method on a real path answered 405 with an `Allow`
header. Fixed with a method-agnostic 404 catch-all under `/api/play/` (PRIVATE in `hub/guest.py`), pinned by
`test_a_wrong_method_on_a_real_path_is_404_never_405`. Should-fixes: `Content-Length` checked before the body is read;
sendBeacon stop documented and tested; the web path defined (Q4, A built: browsers never direct-play); a null subtitle
default answered as -1; the full-token note above; `_uids` written under the lock. Red first: 5 failed, 56 passed
against the previous module.

## Shipped notes
Not yet.
