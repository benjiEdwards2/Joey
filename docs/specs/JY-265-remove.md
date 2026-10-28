# JY-265 Remove on title pages: remove the request, or remove the content

Status: **ready** (2026-10-28). Phases 0 and 1 building on `feat/JY-265-remove-p1`. Phases 2, 3 and 4 are later items
(each its own branch and PR, section 6). Spec drafted from `origin/main` (3837450).
Size: **L** (live system writes that delete media). Builder Opus; two Sonnet reviewers, then one Opus verifier.

B.'s picks, 2026-10-28: "JY-265: Q1A · Q2A · Q3A · Q4A · Q5A · Q6A · Q7A · Q8A · Q9A · Q10A".
Live risk: Radarr / Sonarr / Seerr / Jellyfin writes, including file deletes.
Area: `hub/media_remove.py` (new), `hub/templates/media_film.html` (the More fold), `hub/templates/media_remove*.html`
(new), `hub/guest.py` (route tables), `hub/media_store.py` (one new STEP), `connectors/feeds/arr.py` (per-season sizes),
`hub/media_follow.py` (unfollow hook), `tests/hub/fake_arr.py` (new).
Needs: JY-264 (engine seam) before phase 2 ships, so a re-downloaded show's ratings and diary re-attach.
Options page: `JY-265-options.html` (same folder).

B., 2026-10-28: "In more, can you please add a remove button which would remove the request or remove the content. Then providing a selection criteria to confirm the removal of something or which seasons, sessions to remove."

"Sessions" most likely means **episodes** (a show's seasons and episodes). This spec reads it that way; Q10 confirms.

---

## 0. This changes a standing rule

Until now Joey has never deleted media, and that was on purpose:

- The MediaHub gap analysis (2026-10-05) put "one-library file deletes" out of scope on purpose.
- The Requests page's Remove (2026-10-08, `hub/media_requests.py`) deletes the Seerr request and, only when nothing is
  on disk, unmonitors the title. Its docstring says: "Nothing is ever deleted in Radarr / Sonarr: no file, no entry."
- The Server proposals evaluation (2026-10-19, P1) proposed a Free space list with "Radarr/Sonarr delete with
  confirm". B. accepted the defaults on 2026-10-22, and the default was "P1 lists candidates only, no delete". So
  `/server/space` (P1a) has no delete button by design: "nothing here deletes".
- Follow show (F5) and `docs/connector-contract.md` also say "never deletes".

**JY-265 deliberately ends that rule** for one path: a household Remove on a title page, behind a flag, a strong
confirm, the arr recycle bin and an audit log. Everything else keeps the old rule. Free space stays list-only. Its rows
link to the title page, and Remove is there. Once B. accepts, the docs that say "Joey never deletes" get a dated
amendment: `hub/media_requests.py` docstring, `docs/connector-contract.md`, `hub/README.md`, and `docs/PLAN.md`
(orchestrator).

History note (2026-10-13): Radarr's logs showed B. deleting The Notebook (`DELETE /api/v3/movie/38?deleteFiles=true`)
from the Radarr web UI. That is the job this item brings into Joey, with a safety net.

---

## 1. The two actions

### 1a. Remove request

What it does today on the Requests page (`POST /media/requests/{rid}/remove`), now reachable from the title page:

1. Seerr `DELETE /api/v1/request/{id}` (404 = already gone = removed).
2. When **nothing is on disk**: unmonitor the Radarr movie or Sonarr series (PUT of the app's own resource with
   `monitored: false`). The entry and its history are kept.
3. When **something is on disk** (Available or Partly available): the arr entry is left as it is, and the confirm says
   so: "The request goes. The 2 seasons on disk stay. Use Remove content to delete them."
4. **An active download** for the title (an arr queue row, joined to qBittorrent by `download_id`) is cancelled
   through the arr app: `DELETE /api/v3/queue/{id}?removeFromClient=true&blocklist=false`. Joey never sends
   qBittorrent a delete itself.

Q4 asks whether "nothing on disk" should delete the arr entry instead of unmonitoring it. The recommendation is to
keep today's behaviour, so the two Remove request buttons agree.

### 1b. Remove content

This always goes through Radarr's and Sonarr's own APIs, never the filesystem. The arr app moves the files into its
recycle bin (section 3.3).

| What | Calls (in order) | Afterwards |
|---|---|---|
| Whole film | Live `GET /api/v3/movie?tmdbId=` (still there, same file id and size as the confirm showed?), then `DELETE /api/v3/movie/{id}?deleteFiles=true&addImportExclusion=false` | Entry gone (Q3 A). With Q3 B: `DELETE /api/v3/moviefile/{fileId}` + PUT `monitored: false` |
| Whole series | Live `GET /api/v3/series/{id}` + `GET /api/v3/episodefile?seriesId=`, then `DELETE /api/v3/series/{id}?deleteFiles=true&addImportListExclusion=false` | Entry gone (Q3 A). Joey's Follow for the show is removed first; otherwise its 6-hour re-apply turns monitoring back on |
| Seasons | Live `GET /api/v3/episodefile?seriesId=`, then `DELETE /api/v3/episodefile/bulk {"episodeFileIds": [...]}` for the files in those seasons, then PUT the series with `seasons[n].monitored = false` for each removed season (every other field kept), then `PUT /api/v3/episode/monitor {"episodeIds": [...], "monitored": false}` | The series stays. The removed seasons stay unmonitored, so Sonarr won't fetch them again. Follow's re-apply leaves seasons alone (`media_follow.py:415`) |
| Episodes | Live `GET /api/v3/episodefile?seriesId=`, then `DELETE /api/v3/episodefile/bulk` for the picked files, then `PUT /api/v3/episode/monitor` `monitored: false` for the picked episodes | Season monitoring is unchanged, so new episodes still come |

After any content remove:

- **Seerr.** For a whole title, `DELETE /api/v1/media/{mediaId}` ("Clear data"), so Seerr stops saying Available and
  the title can be requested again. Its open requests are deleted first (1a step 1). For seasons or episodes Seerr is
  left alone; its availability sync catches up.
- **Jellyfin.** `POST /Library/Media/Updated` with `{"Updates": [{"Path": <the arr path>, "UpdateType": "Deleted"}]}`
  for each removed movie folder, series folder or episode file. This is the same targeted call the arr apps' own
  Jellyfin connection makes. If it fails, Joey falls back to `POST /Items/{seriesId}/Refresh?Recursive=true` (series)
  or does nothing (whole film: Jellyfin's realtime monitor or its scheduled scan removes it), and the result says
  "Jellyfin will catch up on its next scan". Phase 0 checks whether the arr apps already have a Jellyfin connection.
  If they do, Joey's call is a harmless duplicate and stays as the belt-and-braces.
- **Hub.** Drop the item's caches (`media_files`, `media_season_state`, `media_requests` lookups, `media_discover`
  film body, `media_quality`) and hide removed rows at once with `media_hidden` until the next snapshot.

Every write step is recorded on its own (section 3.4). The first failed step stops the run and the result names the
step in words ("Sonarr deleted 16 files; Jellyfin refresh failed: it will catch up on its next scan").

---

## 2. Selection UI

### 2.1 Entry point
The title page's **More** fold (`media_film.html`, `details.fold.heromore`) gets one more line: **Remove…** (a
`.btn` with the danger outline). It shows on film, series, season and episode pages, for the household member allowed
by Q1, when the title is in Seerr or the arr apps. It links to:

- `GET /media/remove/{kind}/{tmdb}` (a full page, not an inline panel: a series list is too long for the fold, and a
  page gives the TV a clean focus order). From a season or episode page it opens with that season or episode
  pre-ticked (`?season=2`, `?episode=<arr episode id>`).

The page has two steps, **Pick** and **Confirm**. Both work without JS (plain forms with a 303), and HTMX swaps the
body.

### 2.2 Pick (what can go)

Head: poster, title, then one line in words: "On disk · 48.2 GB · 3 seasons · 30 episodes" or "Requested · nothing on
disk yet".

**What to remove**, as radio cards. Only the ones that apply are shown:

1. **Request only.** "Stop the request. Nothing on disk is touched." Shown when a Seerr request exists.
2. **Whole film** or **Whole show.** Every file, the arr entry and the request.
3. **Seasons** (TV). A list of seasons with ticks. Each row: "Season 2 · 10 of 10 episodes · 16.3 GB · watched", from
   Sonarr's per-season `statistics.sizeOnDisk` and `episodeFileCount` (cached, section 3.5) and the household's watch
   state (Jellyfin snapshot). Specials are listed last as "Specials".
4. **Episodes** (TV). The same seasons, each opening into its episodes with ticks: "E03 · Name · 1.6 GB · watched".
   Only episodes with a file can be ticked. Missing ones show "not downloaded" and are greyed out.

Helpers: **Tick watched seasons** (seasons every household member has finished) and **Clear**. A sticky total sits at
the bottom: "Selected: 2 seasons · 20 episodes · 32.5 GB". The **Next** button stays disabled while nothing is ticked.

### 2.3 Confirm (exactly what goes)

The confirm step does a **live read** (this is the explicit step, like Approve; never a render). It reads the arr entry
and episode files and the Seerr request, then lists exactly what will go:

- "Sonarr deletes 20 files · 32.5 GB" and the list of files as words ("S01E01–E10 · S02E01–E10"; long lists fold
  after 12 lines with "and 8 more").
- "Sonarr stops searching for Seasons 1–2."
- "The request from Georgina (Seasons 1–3) is removed." (when it applies)
- "Files go to Sonarr's recycle bin and are kept for 7 days, so the space frees up when it empties." (Q6)
- "Your ratings, diary and poster stay." (always)
- Warnings when they apply, from section 4: watching now, downloading, seeding, multi-episode file.

Buttons: **Cancel** (first, and the default focus) and **Delete 20 files** (danger). The confirm carries a signed
token, an HMAC over the selection plus the file ids and sizes it showed, valid for 10 minutes. The POST re-reads and
refuses with "This changed since you looked. Check again." if the files differ.

**Whole film or whole show needs a stronger confirm** (Q5): phone and desktop type the title (case-insensitive, ignoring
punctuation); the TV holds OK on the danger button for 3 s, with a progress ring. Seasons and episodes use the plain
confirm unless the selection is every season on disk. That counts as whole show and gets the strong confirm.

### 2.4 Device flows

**Desktop (>= 1024 px).** Two columns: poster and summary on the left; the radio cards and season list on the right.
Seasons open in place.

**Phone (375 px).** One column. Radio cards stack. Season rows are 56 px tall with the tick on the left and the size on
the right. Tapping a season row's chevron opens its episodes. The total plus Next is a sticky bar above the tab bar.
The confirm is a full page. The typed-title box uses `autocapitalize=off`.

**TV (1920, D-pad).** Focus order: radio cards → season rows → Next. On a season row, **OK** toggles the tick,
**Right** opens its episodes (focus moves to the first episode), **Left** or **Back** closes them and returns to the
season row. Rows are at least 64 px (the TV floor). The total stays visible at the bottom. On the confirm, focus starts
on **Cancel**. Down then Right reaches the danger button, and **holding OK for 3 s** fires it (a short press shows
"Hold OK to delete"). **Back** at any step goes to the previous step with focus kept (JY-187 Back memory). Typing is
never asked on the TV.

---

## 3. Safety

### 3.1 Who
- **Household only.** Friends never see the button. Every remove route is PRIVATE in `hub/guest.py`, so the media
  front gives friends the ordinary **404** page before the handler runs (byte-identical to any unknown path).
- **Which household member** is Q1. Recommended: **B. only** (owner `you`), as Approve / Decline and the quality
  switch are today: `her` sees no button and gets **403** on every remove route.
- **The TV.** Joey TV runs on the media front (`media.joeyhome.net`), where PRIVATE routes 404 for everyone. So Remove
  on the TV needs a `HOUSEHOLD_REMOVE` table, served to a signed-in household identity allowed by Q1, exactly as
  `HOUSEHOLD_PLAYER` (JY-057) does for the player. It sits behind its own flag `REMOVE_MEDIA_FRONT` (default off).
  This is Q7. The risk is that the media front has no Cloudflare Access, so a stolen TV session could delete. The
  answer: owner `you` only, the strong confirm, rate limits, the recycle bin and a Discord message per remove.

### 3.2 Flags
`MEDIA_REMOVE` (default off): every remove route 404s and the More line is hidden. `REMOVE_MEDIA_FRONT` (default off):
the TV path. CLAUDE.md rule 7: built and tested against fakes only. The first live run is B.'s accept on a title he
picks.

### 3.3 Recycle bin (the undo)
The NAS volume is RAID0, so there is no second copy. The recycle bin is the only way back.

- **What we know:** on 2026-10-13 both apps had a recycle bin, `/data/recycle-bin/radarr` and `/data/recycle-bin/sonarr`,
  emptied after 7 days (The Notebook sat there until about 19 October). That is from the archived DECISIONS; it has not
  been re-checked since.
- **Phase 0 checks it again**, read-only: `GET /api/v3/config/mediamanagement` on both apps (`recycleBin`,
  `recycleBinCleanupDays`).
- **Recommendation (Q6 A):** keep `/data/recycle-bin/{radarr,sonarr}` and 7 days. Joey **refuses content removes** when
  an app's `recycleBin` is blank ("Sonarr has no recycle bin set, so this can't be undone. Set one in Sonarr ›
  Settings › Media Management first."). It reads the setting at the confirm step and caches it for 1 hour.
- The recycle bin is on the same volume, so **space frees when the bin empties**. The confirm and the result say so,
  and the Free space page's total doesn't count it as freed until then.
- Undo is manual for now: move the folder back from the recycle bin, then use the app's "Rescan" (or Joey's Search now)
  on the title. Section 8 asks nothing about it; a later item could add "Restore" from the audit log.

### 3.4 Audit log
- media.db `media_removals` (a new `media_store.STEPS` entry): `id, at (UTC), owner, front (private|media), kind,
  tmdb_id, tvdb_id, title, scope (request|whole|seasons|episodes), picked (JSON: seasons / episode codes), files,
  bytes, request_ids, steps (JSON: one line per write with app, step and outcome or HTTP status), outcome
  (done|partial|refused|failed)`. It records titles and codes only: no paths, URLs or keys (CLAUDE.md standing rule).
- It is shown as a **Removed** list (last 30) at the bottom of `/server/space`: "Severance · Seasons 1–2 · 32.5 GB ·
  B. · 28 Oct 19:40 · done". That list adds no button, so Free space stays list-only.
- Each remove posts one Discord line to `SERVER_DISCORD_WEBHOOK` (Q9): "Joey removed Severance S1–S2 (32.5 GB) ·
  recycle bin 7 days".
- Rows are never deleted by Joey.

### 3.5 No live call on render
- The title page's More line comes from data already on the page (on server or requested). No arr call.
- The Pick step reads caches only. Whole-title and per-season sizes come from the arr snapshot: the connector's
  `library_sizes` gains `seasons: [{n, files, episodes, size_bytes}]` from the series list it already fetches (no extra
  call). Episode file sizes come from a kept `GET /api/v3/episodefile?seriesId=` (10-min TTL) that a cold page fills
  **after** the response (the `media_season_state.later` pattern), so the page shows "Sizes loading" and HTMX polls
  the fragment once.
- Live reads happen only on **Confirm** and on the final **POST**.

### 3.6 Rate limits
- One remove at a time (a process lock). A second POST while one runs gets "Another remove is running".
- At most **10 content removes per rolling hour** and **3 whole-title removes per hour**. Over that: "Too many removes
  in the last hour. Try again at 20:15." Request-only removes are not limited, as on the Requests page.
- Every POST is `same_origin` plus the signed confirm token, so a POST can't skip the confirm.

### 3.7 What Joey keeps
Removing content never touches media.db's own rows: **ratings, diary, rankings, plays, watchlist, follows (except the
whole-show unfollow above), episode ratings and JY-260's local poster store all stay**. A removed title shows as "Not
on server" with its rating, as off-server titles do today. If it comes back later, JY-260 re-applies its poster.
JY-264's `library_index` re-attaches ratings and diary keyed `jf:<SeriesId>` when the re-downloaded show gets a new
Jellyfin id. Until JY-264 ships they stay in media.db but would be orphaned on a re-download, which is why phase 2
waits for it.

---

## 4. Edge cases

| Case | What Joey does |
|---|---|
| **Requested, not downloaded yet** | Only "Request only" shows; content options say "Nothing on disk yet". Seerr DELETE + unmonitor (1a) |
| **Requested and downloading** (queue row) | Confirm warns "Downloading now: 42 %". The arr queue item is removed with `removeFromClient=true` (1a step 4), then the rest |
| **Partly downloaded season** | The season row says "6 of 10 · 9.8 GB · 4 not downloaded". Ticking the season deletes the 6 files and unmonitors all 10, so the 4 missing ones are never fetched |
| **Season still airing** | Removing a season that has episodes to come (season-state words) warns "5 more to come; they won't download". Episodes-only removes keep the season monitored |
| **Torrent still seeding** (qBittorrent, matched by `download_id` from arr history) | Hardlinked: the space only frees when the torrent stops too. Q8 A: Joey leaves qBittorrent alone and the confirm says "Up to 32.5 GB · 1 torrent still seeding holds a copy" |
| **Someone is watching it** | Jellyfin snapshot `playing` plus a live `GET /Sessions` on the POST. If any household or friend session plays a picked item: refused, "Georgina is watching S02E03 now. Try again when it stops." Not overridable |
| **Specials (Season 0)** | Listed last as "Specials". "Tick watched seasons" never ticks them. Whole show includes them |
| **Anime** | Listed by Sonarr's season and episode numbers (as the arr data has them), not absolute numbers. Nothing anime-specific is needed beyond the multi-episode rule |
| **One file holds two episodes** (E01–E02) | Ticking either ticks both, with the line "One file holds E01–E02" |
| **Film with an upgrade on the way** | Treated as downloading: the queue item is removed too |
| **Title missing from the arr app** (Jellyfin-only, added by hand) | No content remove (Joey only deletes through the arr apps). The More line hides, or shows "Request only" |
| **4K and 1080p of one film** | One Radarr, no `is4k` server (media_quality), so there is one entry and one file. Nothing extra |
| **Followed show** | Whole show: unfollow first (else the 6-hour re-apply re-monitors it). Seasons and episodes: the follow stays |
| **On a watchlist / Everyone's watchlist** | Left as is. The confirm notes "On Georgina's watchlist", and RQ3 "Request all" could request it again |
| **Arr or Seerr unreachable** | Pick still renders from caches; Confirm says "Sonarr can't be reached. Nothing was removed." |
| **Partial failure** | Stops at the first failed write. The audit says `partial` with every step. The result names what happened and what didn't |

---

## 5. Options for scope

| | A: Phased (recommended) | B: Everything at once | C: Request + whole film only |
|---|---|---|---|
| What ships first | Remove request + whole film / whole show, private front | Request, whole, seasons, episodes, TV | Request + whole film; no TV series deletes |
| Seasons / episodes | Phase 3 | Same PR | Never (Sonarr UI) |
| TV | Phase 4, own flag | Same PR | Never |
| Risk | Each write path is proven live before the next | One big L PR, hard to review; the first live use tests every path at once | Lowest, but misses what B. asked for ("which seasons, sessions") |
| B.'s accepts | 4 small | 1 big | 1 |

**Recommendation: A.** The deletes are the riskiest writes Joey has made. Whole-title deletes are one arr call each
and cover the Free space use case (watched films, finished shows) at once. Seasons and episodes add the episode-file
cache, the per-season sizes and the multi-file rules. The TV adds a new media-front household route that deserves its
own review.

---

## 6. Phases (option A)

Every test runs against fakes. No test reaches a live app. New `tests/hub/fake_arr.py` (Radarr + Sonarr), built from
real, redacted response shapes captured read-only in phase 0: movie, series with `seasons[].statistics`, episodefile,
queue, `config/mediamanagement`, and the DELETE / bulk / monitor answers. It extends `fake_seerr.py` (request DELETE,
media DELETE) and `fake_jellyfin.py` (`/Library/Media/Updated`, `/Items/{id}/Refresh`, `/Sessions`).

**Phase 0: read-only facts (S, needs B.'s go for live reads).**
- step: capture redacted shapes of the arr calls above and read `recycleBin` and `recycleBinCleanupDays` on both apps,
  plus whether each app has a Jellyfin connection (`GET /api/v3/notification`); check Seerr 3.5.1 has
  `DELETE /api/v1/media/{id}`.
- verify: a dated note in this spec with the answers; fixtures committed under `tests/hub/fixtures/arr_*.json`. No
  writes (every call is a GET).

**Phase 1: Remove request from the title page + the audit log (M).**
- step: `hub/media_remove.py` with routes `GET /media/remove/{kind}/{tmdb}` (Pick, Confirm), `POST .../remove`; scope
  "Request only" reusing `media_requests.delete_request` + `stop_search` and the queue cancel; `media_removals` STEP;
  the More line; `MEDIA_REMOVE` flag; PRIVATE in guest.py; the Removed list on `/server/space`; the Discord line.
- verify: tests that (1) friends get the 404 page on every route, flag on or off; (2) `her` gets 403 (Q1 A); (3) flag
  off gives a 404 and no More line; (4) a pending request is DELETEd in fake Seerr and the fake Radarr entry is
  unmonitored when nothing is on disk, left alone when a file exists; (5) a queue row is removed with
  `removeFromClient=true`; (6) one audit row per POST, no path or URL in it; (7) a page render makes zero upstream
  calls (call counters on every fake); (8) a POST without a valid confirm token is refused. Budgets: title page p95 is
  unchanged (<= 150 ms warm).

**Phase 2: whole film / whole show (L, after JY-264). Later item: its own branch, PR and brief.**
- step: the content path for `whole`: live re-read, the recycle-bin check, Follow removal, arr DELETE with files,
  Seerr media clear, Jellyfin `Media/Updated` with fallback, cache drops, `media_hidden`; the strong confirm (typed
  title on phone and desktop); rate limits; the watching-now refusal.
- verify: tests that (1) fake Radarr gets `DELETE /movie/{id}?deleteFiles=true&addImportExclusion=false` exactly once;
  fake Sonarr gets the series DELETE once; (2) a blank `recycleBin` refuses with nothing deleted; (3) the wrong typed
  title refuses; (4) a file id changed since Confirm refuses ("This changed"); (5) a fake Jellyfin session playing the
  item refuses; (6) the 4th whole-title remove in an hour refuses; two parallel POSTs, one refused; (7) a followed
  show is unfollowed before the DELETE; (8) Jellyfin `Media/Updated` gets the series path; on a 500, `/Items/{id}/Refresh`
  is called and the result word says so; (9) ratings, diary and poster rows are unchanged after the remove; (10) a
  Seerr failure after the arr DELETE gives outcome `partial` with both steps recorded. Live accept: B. removes one
  watched film of his choice from the preview slot. Joey's result, Radarr's recycle bin folder and the audit row are
  checked read-only.

**Phase 3: seasons and episodes (M). Later item: its own branch, PR and brief.**
- step: the connector adds `library_sizes.sonarr[].seasons`; the cached episode-file read (filled after the
  response); the Seasons and Episodes cards; "Tick watched seasons"; the bulk episodefile DELETE, the season unmonitor
  PUT and the episode monitor PUT; the multi-episode and partial-season rules; specials last.
- verify: tests that (1) the bulk DELETE carries exactly the picked file ids; (2) the series PUT changes only
  `seasons[n].monitored` for the removed seasons (every other field byte-equal); (3) `episode/monitor` gets the picked
  episode ids with `monitored: false`; (4) ticking E01 of a two-episode file ticks E02 and the confirm says so; (5) a
  partly downloaded season deletes its 6 files and unmonitors all 10 episodes; (6) every season on disk picked gives
  the whole-show strong confirm; (7) the Pick render with a cold cache makes zero calls and shows "Sizes loading";
  (8) the connector test pins the new `seasons` shape. Budgets: Pick page p95 <= 150 ms warm.

**Phase 4: the TV (M). Later item: its own branch, PR and brief.**
- step: the `HOUSEHOLD_REMOVE` table + `REMOVE_MEDIA_FRONT` flag in guest.py; the TV layout (64 px rows, Right / Left /
  Back, focus starts on Cancel), hold-OK-3 s on the danger button, no typing.
- verify: tests that (1) on the media front with the flag on, owner `you` is served, `her` gets 403 (Q1 A), a friend
  and a signed-out visitor get the byte-identical 404 page; flag off gives a 404 for everyone; (2) the TV confirm form
  carries no typed box and the hold control posts only after the hold (a short press posts nothing); (3) the guest
  route-table test classifies every new route. TV sitting (B.'s hands, grouped with the next TV window): the Severance
  fake on the preview, D-pad through Pick → Confirm → Cancel, then one real season of B.'s choice.

Each phase: one branch `feat/JY-265-pN-slug`, one PR, docs (`hub/README.md`, `docs/hub-changelog.md`,
`docs/connector-contract.md` for phase 3, and the "never deletes" amendments in phase 2).

---

## 7. Size

**L overall** (it deletes live media). Phase 0 S, phase 1 M, phase 2 L, phase 3 M, phase 4 M. About 1,200–1,600 lines
of code and tests across the four build phases, most of it in tests and the fake arr. Reviews: two Sonnet reviewers
and an Opus verifier on phases 2 and 4; one Sonnet reviewer on phases 1 and 3.

---

## 8. Questions for B.

| # | Question | Options | Recommended |
|---|---|---|---|
| Q1 | Who in the household can remove? | A: B. only (owner `you`); Georgina gets no button, 403. B: both of you | **A**, as Approve / Decline and the quality switch |
| Q2 | Scope | A: phased (request + whole title, then seasons / episodes, then TV). B: everything at once. C: request + whole film only | **A** |
| Q3 | Whole film / whole show: what happens to the arr entry? | A: deleted with its files (no import exclusion, so it can be requested again). B: files deleted, entry kept unmonitored | **A**: Radarr / Sonarr and Free space stay honest; Seerr shows it as requestable |
| Q4 | Remove request when nothing is on disk | A: as today: unmonitor, keep the arr entry. B: delete the arr entry (no files) | **A**, so the Requests page and the title page behave the same |
| Q5 | Strong confirm for whole film / whole show | A: type the title on phone / desktop, hold OK 3 s on the TV. B: hold 3 s everywhere. C: type everywhere (no TV) | **A** |
| Q6 | Recycle bin | A: required, `/data/recycle-bin/{radarr,sonarr}`, 7 days; Joey refuses content removes without it. B: required, 14 days (space frees a week later). C: not required | **A** |
| Q7 | Remove on Joey TV | A: yes, owner `you` only, via a household route on the media front behind its own flag (phase 4). B: private front only (phone / desktop), no TV | **A**: you asked for it in More, and More is on the TV |
| Q8 | A torrent still seeding the same files | A: leave qBittorrent alone; the confirm says "up to N GB, a torrent still holds a copy". B: also remove the finished torrent and its data through the arr download id | **A**: no new qBittorrent write; the seeding limits clear it |
| Q9 | A Discord line per remove | A: yes, to the Server webhook. B: no, the audit list is enough | **A** |
| Q10 | "Sessions" in your message | A: episodes. B: something else (tell me) | **A** |

Reply format (the options page builds it): `JY-265: Q1A · Q2A · Q3A · Q4A · Q5A · Q6A · Q7A · Q8A · Q9A · Q10A`.

B. answered on 2026-10-28: "JY-265: Q1A · Q2A · Q3A · Q4A · Q5A · Q6A · Q7A · Q8A · Q9A · Q10A". Every answer is the
recommended one.

---

## 9. Phase 0 facts (2026-10-28)

`scripts/check_recycle_bin.py` ran once from the laptop (ssh into joey-hub, the hub's own env, one
`GET /api/v3/config/mediamanagement` per app; nothing written):

```
PASS  Radarr: recycle bin set: yes · path: /data/recycle-bin/radarr · cleanup days: 7
PASS  Sonarr: recycle bin set: yes · path: /data/recycle-bin/sonarr · cleanup days: 7
PASS  recycle bin: radarr=yes, sonarr=yes
```

So Q6 A already holds on the live apps: both bins are set, at 7 days. No arr setting was changed. If a bin is ever
blank, setting it is a separate step that needs B.'s OK.

Fixtures (`tests/hub/fixtures/`): `arr_radarr_movie.json`, `arr_sonarr_series.json` (with `seasons[].statistics`),
`arr_sonarr_episodefile.json`, `arr_radarr_mediamanagement.json`, `arr_sonarr_mediamanagement.json` and
`seerr_request_delete.json`. Only `recycleBin` and `recycleBinCleanupDays` were read live. The other shapes come from
the Radarr v5 / Sonarr v4 v3-API resource schemas and Seerr 3.5's request route, with invented values; each file says
so. Seerr's decline answer was already captured (`seerr_decline.json`, WP-B4). Not done in phase 0, left for phase 2:
the arr Jellyfin-connection check (`GET /api/v3/notification`), the queue shape and the Seerr `DELETE /api/v1/media/{id}`
check.

## 10. Phase 1 as built (2026-10-28)

From the builder brief, which narrows section 6's phase 1:

- Flag `REMOVE_API` (`on` turns it on; default off), not `MEDIA_REMOVE`.
- Q1 A with the brief's wording: owner `you` on the private front only. Georgina's view gets the same ordinary 404
  page as friends, not a 403.
- The Remove page (`GET /media/remove/{kind}/{tmdb_id}`, `?step=confirm&scope=request`) reads the cached jellyseerr
  rows only. The live re-read happens on the POST alone (no live read on Confirm).
- The POST carries the request ids the Confirm step showed. It is refused with "This changed since you looked" when
  they no longer match the cached rows, or when a live request belongs to another title. There is no HMAC token; the
  POST is same-origin, as every Joey write.
- The remove reuses `media_requests.delete_request` and `media_requests.stop_search` (Q4 A). No queue cancel: the
  brief says phase 1 does exactly what the Requests page does and deletes no file, so the download cancel moves to
  phase 2.
- One remove at a time, at most 10 per rolling hour.
- Audit table `media_removals` (media_store step 6) and one Discord line per remove to `SERVER_DISCORD_WEBHOOK`. The
  line names the title only, never the requester, a path or a URL.
- Not built in phase 1: the Removed list on `/server/space` (it would touch the Server area; proposed for phase 2) and
  Remove on season or episode pages.
- 2026-10-28: `tests/hub/test_episode_ratings.py`, `test_media_follow_shows.py`, `test_media_store.py` and
  `test_to_rate_skip.py` now expect `SCHEMA_VERSION == 6` (was 5). The new step moved the version; no check was weakened.

## Shipped notes
