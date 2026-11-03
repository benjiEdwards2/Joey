# JY-301 Download controls (pause, resume, delete) on Activity > Downloads

Status: spec
Size: M
Live risk: yes, qBittorrent writes (pause, resume, delete torrents and optionally their files)
Area: new `hub/media_download_actions.py` (routes + qBit client calls, modelled on `hub/server_quiet.py`), `hub/templates/media_downloads.html` and a row partial, `hub/guest.py` (route tables), `connectors/feeds/qbittorrent.py` (carry the torrent hash into each row), `hub/README.md`, `tests/hub/`, `tests/connectors/`
Needs: none (QBIT_URL / QBIT_USER / QBIT_PASS already reach the hub for the P4 cap toggle)
Options page: no, follows the existing row-action pattern (two-step confirm like `_arr_sweep.html` and the P4 cap)

## Problem
B., 2026-11-02: "are you able to allow me to stop, start, or cancel anything from this page? Can we leverage more of the Qbittorrent api to work better?"

## What the code does today
- The qBittorrent feed (`connectors/feeds/qbittorrent.py`) is read only: it logs in, reads `torrents/info` and `transfer/info` every 2 minutes, writes the `qbittorrent` snapshot (up to 20 active rows, a finished-24 h list, seeding counts, speeds, the cap).
- `/media/downloads` reads that snapshot (merged with the arr queue by `media_downloads.merge_downloading`). Rows show a state word ("Downloading", "Stalled", "Paused", "Queued"). There is no action on any row.
- The hub already writes to qBittorrent once: `hub/server_quiet.py` (P4 cap) logs in server-side, sends one call, confirms, redirects. GET explains, POST sits behind `same_origin`, the password never reaches the browser, a log line or a flash. This spec reuses that shape and its `_login` helper.
- qBittorrent runs inside the VPN container's network, so the hub reaches it by the VPN container's name on `QBIT_URL` (`docs/network.md`); no new port, route or tunnel rule.
- Route gating: `hub/guest.py` lists what friends may reach. Owner-only routes (P4 cap, approve / decline) are simply left off that list, so friends get the ordinary 404.

## qBittorrent Web API v2 used
All calls are server-side from the hub, one short-lived session per action.
- `POST /api/v2/auth/login` (form username + password, `Referer` set to the base). 5.x: 204 + `SID` cookie; older: 200 "Ok."; the cookie is the proof.
- `GET /api/v2/torrents/info?hashes=<h>` to confirm a torrent still exists and read its state before and after.
- `POST /api/v2/torrents/pause` and `/torrents/resume` (form `hashes=<h1|h2>` or `all`). qBittorrent 5.x renames these `stop` / `start`; the client tries the new name first and falls back to the old one on 404.
- `POST /api/v2/torrents/delete` (form `hashes=<h>`, `deleteFiles=false|true`).
- Hashes are validated as 40 or 64 hex characters before any call; `all` is accepted only by the pause-all / resume-all routes.

## Behaviour
- Owner only. Private front: per-row buttons by state: Pause (downloading, stalled, queued), Resume (paused), Remove (any). Header buttons: "Pause all", "Resume all" (two-step confirm, shows the count).
- Remove is a two-step fold: first choice "Remove from queue, keep files" (default, `deleteFiles=false`); a second fold, "Also delete downloaded files", asks again with the size and name before `deleteFiles=true`. Both are POST behind `same_origin`; GET only explains.
- After a write the hub re-reads `torrents/info` for that hash, redirects back to `/media/downloads` with a flash word ("Paused", "Resumed", "Removed", "Files deleted"), and overlays the confirmed state until a newer snapshot lands (same idea as the P4 cap).
- Failure words: "qBittorrent is not reachable", "Login refused", "Already gone". No URL, user, password or hash in any flash or log line.
- Friends: the routes are not in `hub/guest.py`, the buttons do not render, the page stays read only. TV: `/media/downloads` on TV renders no buttons (D-pad has no safe confirm); `test_tv_*` untouched.
- The arr queue rows with no matching torrent show no buttons; the Sonarr / Radarr entry is never touched.
- Flag: `DOWNLOAD_CONTROLS=1` in the hub env; unset hides every button and 404s the routes, so the feature ships dark.

## Acceptance criteria
1. A fake qBit (tests) records every call; pause, resume and delete each send exactly one correct call with the right hash.
2. Delete without files sends `deleteFiles=false`; delete with files sends `true` only after the second confirm POST; a single POST can never send `true`.
3. Pause all / resume all send `hashes=all`; per-row routes reject `all`, empty, malformed and over-long hashes (400, no upstream call).
4. 5.x `stop` / `start` and older `pause` / `resume` both work against the fake (404 fallback tested).
5. Login refused, upstream down and unknown hash each give the named flash and no state change.
6. Every POST rejects a cross-site Origin (403); GET never writes.
7. Friend and unauthenticated-front requests to the new routes get 404; friend page HTML has no action buttons; TV page has none.
8. With the flag unset: no buttons, routes 404.
9. No secret, URL, user or hash appears in logs or flashes (test greps captured logs).
10. Connector snapshot rows carry `hash`; the frozen envelope schema is unchanged (additive field) and `tests/connectors/` stays green.
11. Page render p95 <= 50 ms warm; no new background polling; actions <= 3 s.
12. No test runs against the live qBittorrent; the one live check is B.'s accept (below).

## Data
Additive `hash` per row in the `qbittorrent` snapshot. No new tables.

## Performance budget
Hub page p95 <= 50 ms, Media page p95 <= 150 ms, joey-hub memory unchanged. Numbers measured on the preview go in the PR.

## Out of scope
Adding torrents, categories and tags, priority or queue order, per-torrent speed limits, recheck, force-start, sequential download, deleting from Sonarr / Radarr, seeding rows.

## Accept checklist (one live window, on a throwaway test torrent B. adds)
- [ ] Pause then Resume changes the word on the row within one page load.
- [ ] Remove (keep files) drops the row and leaves the file.
- [ ] Remove with files deletes both.
- [ ] Pause all then Resume all returns everything to how it was.
- [ ] Friend login shows no buttons.

## Questions for B.
1. Allow delete-with-files at all? A. yes, behind the second fold (recommended), B. no, remove from queue only.
2. Pause all / resume all: A. include (recommended), B. per-torrent only.
3. More of the API now? A. no, this spec only (recommended), B. also an alt-speed (turtle) toggle beside the P4 Quiet / Full cap, C. also per-torrent speed limits.
4. Show extra read-only detail from `torrents/info` on each row (seeds, ratio, added date, save path)? A. no (recommended), B. add seeds and ratio.
5. Should the arr-queue "remove and blocklist" be a separate later item? A. yes (recommended).

## Shipped notes
