# JY-260 Automated custom posters (films and series)

Status: ready (2026-10-28); phase 1 built; phase 2 built locally (GitHub paused), not deployed
Size: L (live Jellyfin write + a new secret; Phase 1 alone is M, built and labelled L)
Live risk: NAS write (Jellyfin item images, phase 2), secrets (one new `.env` key, phase 2). Phase 1: none.
Area: `hub/media_posters*.py` (new), `hub/posters_template/` (the starter template kit, new), `hub/templates/media_posters.html` (new), `hub/guest.py` (two PRIVATE rows), `hub/main.py` + `hub/tasks.py` (one router line, one loop line), `hub/static/control-surface.css` (a few non-token lines for the review pairs), `hub/requirements.txt` (pillow), `deploy/.env.example`, `deploy/docker-compose.yml` (one read-only template mount), `docs/posters-template-guide.md`, `tests/hub/test_media_posters*.py`
Needs: none (JY-222 is closed; this item replaces it)
Options page: `C:\Users\b.edwards\Desktop\Claude\JoeyTV\review\JY-260\JY-260-options.html`
Date: 2026-10-28 (spec draft 2026-10-28; B. picked and marked ready the same day)

## B.'s picks and words (2026-10-28)

> "JY-260: Q1B · Q2B · Q3A · Q4A · Q5A · Q6A · Q7A · Q8 layout 2 Geist · Q9A"

> "Fine with these. But I will also need to help create or alter the canva template once completed to refine it. That woul dbe ideal."

> "Ideally it sitting in the lower third woul dbe ideal."

> "Can you change it to include teh text position of layout three whilst keeping the layout two clear section."

B. refined the poster in Canva on 2026-10-28 (his export: a black 1000 × 1500 canvas, "TMDB POSTER ART (placeholder)" near the top, "MOVIE TITLE" in large regular capitals in the lower third, and "Seasons 1–4 · 2022–2025" directly under it), then said:

> "Go centre aligned please. then I am happy with that."

After seeing real TMDB art (2026-10-28), B. answered the approval and series questions:

> "go to 3 stars please"

> "Happy to auto approve 3 start and above"

> "I am fine with the season being available now. Only the year is not needed currently."

> "For a series overall, show that. but for a specific season. Show Season 2 for example."

- **1A (replaces Q2B's 5-vote rule):** a pick auto-approves when its TMDB rating (`CommunityRating`, 0–10) is at least **6.0**, which is 3 of 5 stars. Set by `POSTERS_AUTO_MIN_RATING`. Lower or unrated picks wait for B. on the review page. Phase 1 records the verdict per title (`auto` in the sidecar, "Auto-approve" or "Waits for review" on the page); the first write that acts on it is phase 2.
- **2A:** a series poster's sub-line is "Seasons 1–4", or "Season 1" with one season. Years are not shown. Only real seasons count: no specials (season 0), no unnumbered seasons, and no seasons without episodes on disk (`isMissing=false`). `LocationType` is not used, because on B.'s Jellyfin a real season with no season folder reports "Virtual".
- **Per-season posters:** each real Jellyfin Season item gets its own poster. It uses the TMDB season poster from `RemoteImages` on the Season item, falling back to the series' pick. The title is the series name and the sub-line is "Season 2". Specials are left alone. Seasons appear on the review page and in the dry-run list, straight after their series; a series' season list is re-read at most once a day.
- **Open finding (real-art set v2, 2026-10-28, for B.):** Jellyfin's `CommunityRating` on TMDB poster images is not a 0–10 film rating. The 10 picks in the set scored 0 to 3.3; none reached 6.0, so today every poster would wait for review. The threshold is unchanged until B. decides: keep it, lower it (`POSTERS_AUTO_MIN_RATING`), or rate on something else.

What it means for the starter kit (B.'s Canva layout, built 2026-10-28):
- **Title:** Geist **Regular** (weight 400; B. named no other font), capitals, `max_size` 95 px, top at 75 %, centred. A 2–3 line title still grows upward from the bottom anchor (`title_gap` 2 %, `title_top_limit` 62 %).
- **Year / seasons line:** directly under the title, top at 84 %, about 40 px below a 1-line title. Regular weight, white, centred. The no-overlap rule stands.
- **Shadow:** his export has none, but it was on black. The starter keeps only a very soft shadow (title 0.35, sub-line 0.3 opacity) so the text stays readable over bright art.
- **Art and fade:** the poster art and the smooth fade stay; the fade now starts at 50 %. His solid black is Canva flattening the gradient on import, not a design choice.

What they mean for the build:

- **Q1B:** B. designs in Canva; joey-hub renders each poster with Pillow. No Canva account at run time.
- **Q2B, replaced 2026-10-28 by 1A (below):** a pick auto-approves when its TMDB rating is at least 6.0 (3 of 5 stars). Lower or unrated picks wait for review.
- **Q3A:** the TMDB list comes from Jellyfin's `RemoteImages` proxy. No TMDB key.
- **Q4A:** the write path uses its own `JELLYFIN_POSTER_API_KEY` (phase 2, B.'s hands).
- **Q5A:** `LockData` + a daily drift re-apply (phase 2). No `poster.jpg` in media folders.
- **Q6A:** episode stills are left alone.
- **Q7A:** the film sub-line is the year.
- **Q8, layout 2 "Clear" with Geist, text in layout 3's positions:** full-bleed art, no frame or border, a soft scrim over the bottom ~40 % fading upward. Title top at 74 % of the height, sub-line at 88 %, left and right margins 6 %, centred. All of these live in `template.json`, so B. can move them without code.
- **Q9A:** the review order is recently added first, then alphabetical.
- **The template requirement:** the design comes from a template kit B. can open, refine in Canva and re-export with no code change (next section).

## The template kit

A folder of files. joey-hub reads it on every pass; a change to any file re-renders every poster.

- **Where:** NAS `/volume1/Docker/joey/posters/template/`, mounted read-only into joey-hub at `/data/posters/template` (`POSTERS_TEMPLATE_DIR`). An empty or missing folder means the starter kit shipped in the image (`hub/posters_template/`).
- **Canvas:** 1000 × 1500 px (2:3). Any 2:3 size from 600 × 900 to 2000 × 3000 is accepted.
- **Layers, bottom to top:** TMDB art (full bleed, cover-cropped) → scrim (`scrim.png` from Canva, or the `scrim_band` gradient when there is no file) → title → sub-line → optional `frame.png`.
- **`template.json`:** the title box (`title_anchor` = top of the title as a fraction of the height, `margin_x`, `max_size` / `min_size` in px, `max_lines` up to 3, `line_height`, `uppercase`, `tracking`, `weight`, `colour`, `shadow`), the sub-line box (`sub_anchor`, `size`, `weight`, `colour`, `opacity`, `tracking`), the font (`family` = the Google Font name, `file` = the font file in the folder), the scrim (`scrim` file name or null, `scrim_band` = where the fade starts, where it is solid, and the opacity), and the optional `frame` file.
- **Validation:** a bad template is refused as a whole with every problem listed by name. Until it is fixed, posters are made with the starter kit, and `/media/posters` shows "Your template was rejected" with the list (review fix, 2026-10-28; the draft kept the last good renders). File caps: `template.json` 64 KB, each PNG 10 MB, the font 5 MB.
- **Starter kit:** layout 2 "Clear" with Geist (OFL, the hub's own font file) and layout 3's text positions. It also has `guide.png`, a safe-area overlay B. can drop into Canva as a reference layer.
- **Guide:** `docs/posters-template-guide.md` covers the step-by-step in Canva, the exports, the safe areas, changing the font and previewing before anything is applied.

## Phase 1 as built (no live writes)

1. **Renderer** (`hub/media_posters_render.py`): art + kit → JPEG q90. The title's lines always fit between `title_anchor` and `sub_anchor`, and the title auto-fits in this order:
   - it shrinks on one line from `max_size` to `wrap_at` (60);
   - it wraps to 2 balanced lines, then 3 (`max_lines`), each from the largest size that fits;
   - the last line count may go down to `min_size` (40), the hard floor;
   - with `title_anchor_mode: "bottom"` (the starter), a 1-line title sits at `title_anchor` (74 %). A taller block grows upward so its bottom stays `title_gap` (2.5 %) above the sub-line, rising no higher than `title_top_limit` (62 %); the title box and the sub-line box never intersect (tested for 1, 2 and 3 lines, plus a pixel check);
   - only past the floor is it ellipsised, and then it is flagged: `truncated` in the sidecar, a warning in the log with a count only, and "Title cut short" on the review page.

   The scrim is one smooth gradient that starts at 56 %, with `solid` 1.2, so it is still darkening at the bottom edge: no seam and no flat band. The sub-line for a film is the year (Q7A). For a series it is "Seasons 1–4", or "Season 1" with one season, with no years (2A). A season item gets "Season N". JPEG sources decode at reduced size (`draft`), so peak memory stays low. It also runs as a CLI for previews (`python -m hub.media_posters_render`).
2. **Pick** (`hub/media_posters.py`): `GET /Items/{id}/RemoteImages?type=Primary&providerName=TheMovieDb&includeAllLanguages=true` through `media_jellyfin.get`. Order: text-less (no language) first, then English, then any other; within each, more votes first, then more pixels. Art is fetched only from `https://image.tmdb.org/t/p/`, capped at 5 MB.
3. **Flag:** `POSTERS=off|dry|on`, default off. `dry` renders up to `POSTERS_PER_PASS` (30) titles per hourly pass into `<IMG_CACHE_DIR>/posters/` (one JPEG + one JSON sidecar per title) and lists them. `on` is phase 2: today it logs once and behaves exactly as `dry`. No code path writes to Jellyfin.
4. **Review page** `GET /media/posters`: household only, private front. The media front and friends get the 404 page, and so does everything while `POSTERS=off`. Original (`/img/jf:<id>?h=600`) and proposed (`/media/posters/img/<id>`) sit side by side, with the pick words and the template state. It reads local files only: no network on render.

**Phase 1 tests (written red first):** layout maths (anchors, margins, auto-fit, the 2-line wrap, the ellipsis), the text-less pick and its order, `template.json` validation (the starter passes; a bad one is rejected naming each problem), household-only page, no network on page render, no Jellyfin write call anywhere (a source scan plus a fake session that allows GET only).

## Phase 2 (2026-10-28): every poster, stored locally, write-back behind the key

B.'s words, 2026-10-28, after the phase-1 real-art samples:

> "Love it for the posters. Continue. We can complete a full replacement of all and then store them local to help with loading pages quicker."

The orchestrator's reading (recorded as given):

1. **All** films, series and seasons get a custom poster, with no approval wait. This supersedes the rating auto-approve rule (1A above). `POSTERS_AUTO_MIN_RATING` stays, defaulting to 0; the review page stays for spot checks and per-item revert.
2. **Local store.** Finished posters are stored on the NAS under `/volume1/Docker/joey/posters/out/` (a new compose mount, read-write for the hub only), as pre-sized variants for the sizes Joey requests: TV rows, grids, phone and title page. `/img` serves the stored custom poster directly when one exists, which is faster than proxying and resizing, and falls back to today's path when none does. The files are versioned so a template change re-renders. Cache headers follow the existing `/img` behaviour.
3. **Jellyfin write-back (`POSTERS=on`)** is implemented but runs only when `JELLYFIN_POSTER_API_KEY` is set. B. has not created it yet. Before any write it backs up the original image and its ImageTag. It writes with `POST /Items/{id}/Images/Primary`, sets LockData per Q5A, re-applies daily if the image drifts, and is idempotent. Revert restores the original. With no key, the mode logs one clear line and does no writes.

Also from the brief: one full backfill pass, rate-limited, behind the existing memory gate (skip under 1,300 MB available), resuming after a restart, with progress in media.db, in the order recently added first then A–Z (Q9A). New titles come in through the snapshot poll. `POSTERS` defaults to `dry` after deploy (render into the store and serve from it); write-back stays off until the key exists.

### As built

- **Store** (`hub/media_posters_store.py`): one folder per Jellyfin item under `POSTERS_DIR` (default `/data/posters/out`):

  | File | What |
  |---|---|
  | `<ver>.full.jpg` | the 1000 × 1500 master, q90 (review page, write-back, `/img` h=1280) |
  | `<ver>.120.jpg`, `.240`, `.400`, `.600` | pre-sized 2:3 variants, q85: the heights `/img` is asked for posters (`_poster.html` 120 / 240, the `/img` default 400, TV tiles and the title page 600) |
  | `meta.json` | the sidecar (pick, sub-line, status, `ver`) |
  | `current` | the published version; no file = not served (reverted, or held back by a set rating floor) |
  | `orig.<ext>` | Jellyfin's original, saved before the first write-back; never pruned |

  `ver` hashes the template kit's version with the poster's words, so a template change or a new season gives a new file name; the old version's files are removed once the new one is published, and until then the old poster keeps being served. Every write is atomic.
- **`/img`** (`hub/images.py`) and the versioned URL (coordinator fix, 2026-10-28): Joey's poster macros (`_poster.html`, `_tv_tile.html` `art()`) add `&v=<ver>` to a `jf:` ref whose poster is published; the version comes from the store's `current` file at page-build time (Jinja `img_v` → `media_posters.url_version`, one local read, no network). `/img` serves `<current>.<h>.jpg` with the existing `HIT_CACHE` (30 days, immutable) only when `v` matches the published version, so a new poster or template is a new URL at once and old URLs stay cacheable. `v` must be 6–16 lower-case hex characters and is only compared with `current`, never used in a path; anything else is ignored. A `jf:` URL with no `v` (or a bad one) takes today's path, and so do `jfb:`/`tmdb:`/arr refs and `POSTERS=off`. A `v` that is no longer published (a page built just before a revert or re-render) gets today's image with the short fallback cache (1 h), so that URL never pins the wrong image. The review page's "Now" column has no `v`, so it keeps showing Jellyfin's own poster. joey-media mounts the store read-only, so friends get the same stored posters for the titles they can see.
- **Pass** (`hub/media_posters.py`): every film, series and real season (specials still skipped). A pass every 5 min (`TICK_S`) while the backfill has work left, hourly once it is through; `POSTERS_PER_PASS` (30) renders a pass with a 2 s pause. Per item state lives in media.db: `poster` (version, status, revert flag, backup ext + tag, live version + tag, lock flag, times, last error) and `poster_progress` (`last`, `at`, `backfill_done`). An item whose version is already recorded is passed over with no network call, which is what makes a restart resume where it stopped. The tables are created by the poster module on first write (no `media_store` schema step, so `SCHEMA_VERSION` stays 5). The memory gate is unchanged and a skipped pass is retried on the next 5-minute tick.
- **Write-back** (`hub/media_posters_write.py`, the only poster module that may call Jellyfin with anything but GET; a source-scan test holds the others to GET): runs only with `POSTERS=on` and `JELLYFIN_POSTER_API_KEY` set; `on` without the key logs once and writes nothing. Per item: backup (`GET /Items/{id}/Images/Primary`, no size params, into `orig.<ext>`, plus `ImageTags.Primary`; an item with no Primary is recorded as `none`) → upload (`POST /Items/{id}/Images/Primary`, base64) → `LockData: true` via `POST /Items/{id}` with the full item DTO, only if it was not already locked (`locked_by_us`) → read back the new tag. No backup, no write. Idempotent (same version + same tag = no call). Drift: once a day per item the live tag is compared; a change is re-applied once and logged. Revert: re-upload the backup byte-for-byte (or `DELETE` the Primary when there was none) and unlock what Joey locked; a revert asked for while the key is missing is carried out by the next pass that has it.
- **Review page**: per row "Revert to the original" / "Use the Joey poster" (POST, same-origin guarded, household only, PRIVATE in `hub/guest.py`); row words say "Reverted", "In Jellyfin" or "Held back: under the rating floor". The head line says whether posters are only served or also written, and says so when `on` lacks the key.
- **Settings**: `POSTERS` default `dry` (was off); `POSTERS_AUTO_MIN_RATING` default 0 (was 6.0); `POSTERS_DIR` default `/data/posters/out` (was `<IMG_CACHE_DIR>/posters`).

- **Review fixes (reviewer A FAIL at b69b2e3; coordinator 2026-10-28):**
  - *Every write is undoable.* `wrote` + `pending_ver` are recorded **before** each upload and `live_ver` straight after it; the lock and the tag read-back follow. A failed lock or read-back leaves `live_ver` set and `live_tag` empty, and the next pass finishes it without re-uploading. A crash between upload and record leaves `pending_ver`, and the next pass writes it again. A revert restores the backed-up original whenever `wrote` is set, and reports honestly: `reverted` only when Jellyfin has the original back (or nothing was written), else `pending` (no key / not `on`) or `error`; the next pass retries both.
  - *B.'s manual changes win* (**orchestrator default 2026-10-28; B. may override**). When the daily check finds a tag that is neither Joey's last upload nor the backed-up original, the item is marked `manual`: Joey stops re-applying and logs it once. The review page says "Manual: changed by hand in Jellyfin, left alone". Revert then stops serving the Joey poster but leaves his poster in Jellyfin; "Put the original back in Jellyfin" restores the pre-Joey original only on his explicit click; "Re-apply the Joey poster" clears `manual` and writes Joey's poster again. A tag back at the original (or no image) is still drift and is re-applied once a day. Caveat: a metadata refresh that downloads a *new* TMDB image also counts as manual.
  - *No starvation.* An item that fails 3 times in a row (render or write) backs off for 24 h (`fails`, `retry_at` in media.db; one log line) and is passed over without counting against `POSTERS_PER_PASS`. The review page shows "Failed 3 times: retried after …" on the row (or in a list above it for items never rendered), with "Try again now" (= re-apply, which clears the backoff). Any success resets the count.
  - Routes added: `POST /media/posters/{jf_id}/original` and `/reapply` (same guard, PRIVATE).
- **Verifier fixes (Opus verifier FAIL at 7bb42f2; coordinator 2026-10-28):**
  - *A revert is sticky and retried as a revert.* `reverted` is recorded first and only B.'s explicit "Use the Joey poster" / "Re-apply the Joey poster" clears it; no pass writes a reverted item. "Try again now" (`POST /media/posters/{jf_id}/retry`) repeats what failed: on a reverted item it is "Retry the revert" (clears the backoff and runs the revert again), on any other it only clears the backoff. Items never rendered that are backing off get the same button.
  - *Per-item lock.* Every write and every revert of an item runs under that item's lock: `poster.lock_owner` / `lock_until`, taken with one atomic `UPDATE` in media.db, so it holds across threads, the background loop and any other process on the file; a crashed holder's lock goes stale after 300 s. `apply` re-reads `reverted` under the lock. A web revert waits up to 10 s for an in-flight write, then restores; if the write is still running it records the intent and answers "Revert queued" (the next pass restores it).
  - *Confirmed restores.* A revert reports "reverted" only after a re-read: Jellyfin's Primary bytes equal the backup's (or, when there was none, no Primary is set). Otherwise `error`, and the next pass retries it.
  - *Page honesty (note 3).* A reverted row with a restore still owed says "Revert pending: Jellyfin still has the Joey poster until the restore is confirmed". After each action the page says what happened (`?done=` with a fixed word list: reverted / queued / pending / error / manual / cleared / reapplied).
  - *Cheap notes.* Queued reverts also run when the template is unusable or the store is unavailable (note 5). Columns added since 94b3c34 are added to an older `poster` table on first use (note 6; nothing was ever deployed, so this is a guard only). A season list that fails 3 times backs off like any item (note 7).

### Disk use (measured 2026-10-28)

On the 9 real TMDB sources in `JoeyTV\review\JY-260\real-samples\src\`: **388 KB per item on average, 527 KB at most** (master 312 KB; variants 3 / 9 / 21 / 42 KB for h = 120 / 240 / 400 / 600). Library, read-only from the NAS `jellyfin` snapshot: **50 films and 27 series** (546 episodes); the snapshot does not count seasons, so at 2–3 real seasons a series about 55–80 seasons, **about 130–160 items in all ≈ 50–65 MB** (worst case about 85 MB), plus the write-back backups (Jellyfin originals, ~50–100 KB each here) once the key exists. At 30 a pass every 5 minutes the first backfill takes under half an hour.

### Phase 2 steps (step → verify)

- Store + variants → verify: tests for every item type stored and published, each variant's pixel size, the master for h=1280.
- `/img` prefers the store → verify: tests that a stored `jf:` ref with its `v` is served with no upstream call and `HIT_CACHE`; that no `v`, a stale `v` (short cache), `POSTERS=off` and `jfb:` take today's path; that the two poster macros render `&v=<ver>` only for a published `jf:` poster; that a new template gives a new URL; and that hostile `v` values (`../`, encoded slashes, NUL, non-hex, too long, file names) are ignored.
- Versioning → verify: a template change re-renders every item under a new `ver`, the old files are gone and `/img` serves the new bytes.
- Backfill → verify: tests for the resume after a restart (no network for done items, `poster_progress`), Q9A order, the memory gate and the 5-minute / hourly tick.
- Verifier fixes → verify: tests for "Try again" on a failing revert retrying the revert (never a re-apply; the revert stays sticky), the page's "Retry the revert" and `?done=` words, a revert racing an upload (queued, then restored by the next pass, never reported "reverted" early), a revert waiting for the lock, a write refused while a revert holds the item, a stale lock expiring, an unconfirmed restore reported as `error`, queued reverts with a broken template, the older-table column migration and the season-list backoff.
- Review fixes → verify: tests for a failed lock and a failed read-back after the upload (recorded, finished next pass without a second upload, revertable), a crash between upload and record (still undone; reconciled next pass), a revert that cannot reach Jellyfin (`error`, retried), a hand-set poster (manual, never re-applied, kept by revert unless asked, re-apply wins), 3 write and 3 render failures (24 h backoff, pass limit freed), and the page words and actions.
- Write-back on a fake Jellyfin → verify: no write without the key (and none in `dry` even with it); backup before upload before lock; a failed backup or upload writes nothing and keeps the original; idempotent; drift re-applied once a day; revert byte-for-byte and unlocks; a pending revert completes once the key is back; no key, URL or title in the logs.
- Friends → verify: a signed-in friend gets the stored poster through `/img` and the 404 page for `/media/posters`, its image and both POST routes.
- Disk → verify: the per-item size measured on real art and the library counted from the snapshot (above).
- Store folder (coordinator fix, 2026-10-28) → `deploy/deploy.sh` `posters_dir()` runs `mkdir -p /volume1/Docker/joey/posters/out`, `chown 1000:1000`, `chmod 755` before `compose build` / `up`, every run (idempotent; repairs a root-owned folder; failure rolls back with "poster store dir"); documented in `docs/runbook.md` → Deploy. A deploy.sh change runs from the second deploy after it merges, so the first deploy with phase 2 needs the one-line `mkdir/chown/chmod` from the runbook run by hand first. Verify after deploy: the hub log shows the backfill passes and `posters: backfill complete`, no `PermissionError`; NAS available stays ≥ 1,200 MB.
- Write-back pilot (B.'s hands: create the key, append it with `nas_scripts/append_env.sh`; then `POSTERS=on`) → verify: the phase-2 pilot list under "Phases" below.

### Open points for B.

- **Browser caches: fixed** by the versioned URL above. Caveat: URLs built outside the two macros (none today) would get Jellyfin's poster, not the store's.
- **The `jellyfin` snapshot is the only target list,** so posters follow it: `tmdb:` refs (requests, Discover, awards) still show TMDB's own poster.
- **joey-media** reads `POSTERS` from `media.env`, not `.env`; it serves the store unless `POSTERS=off` is set there too.
- **UpdateItem** (`POST /Items/{id}`) is sent the full DTO read just before; the pilot should confirm on B.'s Jellyfin that nothing else on the item changes.

## One-screen summary

- **What:** every film and series in Jellyfin gets a Joey-made poster: a text-less TMDB poster from a template kit B. designs, with the title in the lower third (layout 3's positions over layout 2's clear art, B. 2026-10-28; the draft said centre line) (phase 2: "Seasons 1–5 · 2019–2024" under it for series). Written back to Jellyfin as the item's Primary image, so Jellyfin, Joey Media and Joey TV all show it.
- **Canva verdict:** usable, but not as the renderer. Canva's Connect API does have Autofill + Brand Templates + Export, and today's docs say they need **Canva Pro** (US$144/yr), not Enterprise (the "Enterprise only" line is older). It still means an OAuth app, a browser sign-in, single-use rotating refresh tokens stored on the NAS, 5 API calls and two polling loops per poster, and 500 exports per user per day. For a private two-person library that is a lot of moving parts for a template that changes once a year.
- **Recommendation: Option B.** Design the frame once in Canva (any plan, even Free), export it as PNG layers; the NAS renders each poster itself with Pillow (title text, later seasons/years). No Canva account at run time, ~0.5 s and ~40 MB transient per poster inside joey-hub, no new container.
- **Trigger:** poll, not a webhook. The hub already sees every new film/series within 15 min through the jellyfin snapshot (`media_warmup.library_targets`); a new `media_posters` loop diffs that list against a `posters` table. Requested titles need no special path: when Seerr fulfils one it lands in Jellyfin and the same poll picks it up. Backfill = the same loop, one title every 10 s, deploy-window only.
- **Safety:** `POSTERS=off|dry|on`. `dry` renders to `/data/posters/out/` and a private review page only. `on` writes only titles B. has approved on that page (or "approve all pending"). Every write first saves the original Primary image + its ImageTag, so one click reverts. Lock = Jellyfin `LockData` on the item + a drift check that re-applies if a refresh overwrote it.
- **Phase 1 writes nothing live.** First live write is a 5-title pilot B. picks.

## Problem

B. 2026-10-28, verbatim:

> "Posters for episodes, series, and movies. I want to obtain TMBD posters for movies, tv shows and series. The idea is a movies poster can be replaced with a custom one that we create. The flow is this. With any new, existing, or requested show pulled into Jellyfin. A movie shows up in Jellyfin, this prompts a request for a poster. The TMBD posters will be pulled, placed into a Canva template where it is placed. The text for the series/movie is placed on the centerlines. If it is a series or has multiple seasons, it places it below and the years it runs between (not urgent yet, can be done after). This then is savead to the movie or series as the poster. This is displayed on Jellyfin. I would like this to be automated."

HITLIST row (2026-10-28): "I have a later plan to update it with posters from tmbd that work well. (Create action for that)". JY-222 (TMDB + fanart.tv best-rated pick) was closed 2026-10-27 on "stay as current"; this item is a different idea (a Joey-made poster), so it does not reopen JY-222.

## Research findings

### 1. Canva (checked 2026-10-28 on canva.dev and canva.com/pricing)

| Thing | What the docs say today |
|---|---|
| Connect API | REST at `api.canva.com/rest/v1`. An "integration" is created in the Developer Portal (client id + secret, scopes, redirect URL). Private use needs no Canva review. |
| OAuth | Authorization Code + PKCE. B. signs in once in a browser; the NAS keeps the tokens. **Refresh tokens are single-use and rotate on every refresh**: the newest one must be saved atomically each time or the integration is locked out until B. signs in again. Access tokens are short-lived (lifetime not stated). Token calls must come from a backend (CORS-blocked in browsers). |
| Brand Templates | "Act on behalf of a user on a Canva plan that includes brand templates, such as Canva Pro, Canva Teams, or Canva Enterprise." Endpoints: list, get, get dataset (which fields are fillable), publish. |
| Autofill | `POST /autofills` with `brand_template_id` and `data` (`text` fields, `image` fields by `asset_id`). Async job; poll `GET /autofills/{job}`. Eligibility: Pro, Teams or Enterprise (Teams is closed to new sign-ups; "Business" replaces it). Scope `design:content:write`. **60 requests / min / user.** Unknown field names are silently skipped. "Usage limits will be introduced in the future." |
| Asset upload | `POST /asset-uploads`, raw bytes, `Asset-Upload-Metadata` header with a base64 name. Async. 30 / min / user. Scope `asset:write`. |
| Export | `POST /exports` (PNG/JPG, 40–25,000 px). Async; download URLs expire after 24 h. **500 exports / user / 24 h**, 75 per 5 min, 20 requests / min. Transparent-background PNG needs a paid plan. |
| Price | Pro US$144 / year (one person); Business US$250 / person / year; Enterprise "Let's talk". The autofill guide's older prerequisite line says Enterprise; the current API reference and the pricing table say Pro includes Brand Templates. **Treat "Pro is enough" as to be confirmed by B. in his own account before paying for anything** (the Developer Portal and a Free account are enough to see whether the Brand Templates list call returns 403). |

What B. would need for Option A: a Canva Pro subscription (or Business), a Canva integration (his hands: Developer Portal, scopes `design:content:write`, `design:content:read`, `asset:write`, `brand_template:read`), one browser sign-in, a brand template with three data fields (`poster` image, `title` text, `sub` text), and a token store on the NAS.

Per poster, Option A is: upload asset → poll → autofill → poll → export → poll → download → (then the same Jellyfin write as every other option). Roughly 8–10 HTTP calls and 10–30 s wall time, serialised. A ~600-title backfill fits in 2 days under the 500/day export cap.

### 2. TMDB images

- `GET /3/movie/{id}/images` and `/3/tv/{id}/images` with `include_image_language=null,en` return posters with `iso_639_1` (`null` = no language = text-less), `vote_average`, `vote_count`, `width`, `height`. **Needs a TMDB v3 API key** (free; B.'s hands to register, one `.env` key).
- Alternative with **no new key**: Jellyfin's own remote-image proxy, `GET /Items/{id}/RemoteImages?type=Primary&providerName=TheMovieDb&includeAllLanguages=true`, returns the same list (`Language`, `CommunityRating`, `VoteCount`, `Width`, `Height`, `Url`) through Jellyfin's bundled TMDB key. The image bytes are then fetched from `image.tmdb.org/t/p/original` (no key, as `/img` does today). To verify on the NAS in Phase 1 with one read-only GET.
- Seerr's `/api/v1/movie/{id}` gives only `posterPath` (the chosen one), not the list, so it is not enough.

### 3. Jellyfin write-back and locking

- Upload: `POST /Items/{id}/Images/Primary`, body = the image **base64-encoded** (not raw bytes), `Content-Type: image/jpeg` (or png). Admin authentication. Jellyfin dashboard API keys are admin-scoped, so the existing `JELLYFIN_API_KEY` very likely already can; the spec still asks for a **separate** key `JELLYFIN_POSTER_API_KEY` so the write path can be revoked on its own (Q4).
- Read the current image for the backup: `GET /Items/{id}/Images/Primary` with no size params returns the original; the item's `ImageTags.Primary` is the hash to store (changes whenever the image changes).
- Delete (revert path B): `DELETE /Items/{id}/Images/Primary` then re-upload the saved original.
- Lock: `POST /Items/{id}` (UpdateItem) with the full item DTO and `LockData: true` is the API form of "Lock this item to prevent future changes". `LockedFields` has no `Images` value (it lists Cast, Genres, Name, Overview, … only), so `LockData` is the only item-level lock. Forum reports say a manual "Replace all metadata + Replace existing images" refresh still overwrites locked items. Two guards, both in the spec: (a) `LockData: true` on write; (b) a drift check: each pass compares the live `ImageTags.Primary` with the one stored after our upload and re-applies at most once per title per day, logging it.
- "Save artwork into media folders" (library option) writes `poster.jpg` next to the media; Jellyfin then prefers the local file on every scan. Stronger, but it is a NAS file write inside the arr-managed folders and Sonarr/Radarr can also write `poster.jpg` there. Not recommended for the first version (Q5).
- Episodes: Jellyfin's episode Primary image is a 16:9 still, and Joey TV / Jellyfin draw episode rows with stills. A 2:3 custom poster there would break those rows. Default: **episodes out of scope**; the series poster carries the design (Q6).

### 4. The NAS

From `nas-memory-2026-10-27.md`: available RAM sits at ~1,380 MB after a few hours up; joey-hub is at ~108 MB of its 384 MiB cap; floor is 1,200 MB during any deploy or preview. Headless Chromium needs 300–500 MB resident and cannot run there. Pillow on a 1000 × 1500 RGB canvas is ~4.5 MB per buffer; with the source poster, the frame layers and text masks the transient peak is ~30–50 MB, released after each title. Serial, one title at a time, inside the existing hub thread model (`tasks._every`), with the same pause pattern as the warm-up.

## Options

| | A: Canva Autofill | **B: Canva design, NAS renders (recommended)** | C: In-house template, no Canva |
|---|---|---|---|
| Who designs the frame | B. in Canva, as a Brand Template with data fields | B. in Canva (any plan); exports 2 PNG layers + picks a font | Claude in CSS/Pillow from B.'s description; B. picks on an options page |
| Who renders each poster | Canva (cloud) | joey-hub, Pillow | joey-hub, Pillow |
| Cost | Canva Pro US$144/yr (to confirm Pro is enough; else Business US$250) | US$0 (Free works for export; transparent PNG export needs Pro — avoidable by designing opaque layers) | US$0 |
| Effort | L: OAuth + rotating token store + 3 async job pollers + Canva failure handling + the Jellyfin write | M: renderer + layout + the Jellyfin write; same write-path work as A | M: as B, minus the layer import; plus one more options round |
| Quality | Exactly Canva's rendering, any Canva font or effect | Pixel-exact for art layers; text set by Pillow in a font that must exist as a TTF/OTF (Google Fonts or Geist; not Canva-only fonts). Effects on text (shadow, outline, gradient) are coded, not drawn | Same as B, less art freedom |
| NAS RAM / CPU | ~0 extra (cloud renders); the poller is tiny | ~30–50 MB transient, ~0.5–1 s per poster (est.; measured in Phase 2) | Same as B |
| Failure modes | Token rotation lost → B. must sign in again; Canva outage or rate limit stalls the queue; "usage limits will be introduced"; template field renamed → silently skipped; export URL expiry | Font missing / text too long (handled: shrink then two lines); a layer file changed → re-render all (template_version) | Same as B |
| Re-skinning later | Edit the Brand Template; nothing to deploy | Export new layers, bump `template_version`, re-render | Code change + deploy |
| Where phase 2 text goes | Another data field in the template | Pillow, below the title | Same |

Chromium/HTML variant of B: rejected for the NAS (memory). It could only run on B.'s laptop as a manual batch, which is not "automated". Pillow is enough for centred text, a sub-line, a shadow and a band.

**Recommendation: B.** B. keeps Canva as the design tool he asked for; the runtime stays inside joey-hub with one new pip package (`pillow`) and no new container, account, token or daily cap. Option A stays documented so it can be swapped in later if B. wants Canva effects the renderer cannot do: the Jellyfin write path, the queue, the review page and the lock are the same in all three.

## The flow (Option B)

1. **See:** every pass, `library_targets(jellyfin snapshot)` gives every film and series (jf_id, kind, tmdb id). Titles not in `posters`, or whose `template_version`/text hash is stale, are queued. (New, existing and Seerr-requested titles all arrive this way; Seerr-fulfilled titles appear in Jellyfin like any other.)
2. **Pick the TMDB poster:** list posters; keep `iso_639_1 == null` with `width >= 1000`; sort by `vote_average` then `vote_count` then `height`. Fallback 1: any `null`-language poster of any size. Fallback 2: an English poster (text under text; flagged `fallback=en` on the review page so B. can skip it). Fallback 3: no TMDB id or no poster → skip, status `no_source`, never a write.
3. **Render:** fetch `t/p/original` (capped at 5 MB like `/img`), fit into the frame's poster window, draw the under-layer, the poster, the over-layer, then the title centred on the centre line (auto-fit: shrink to the window width, then break into two lines, hard cap three), phase 2: the sub-line. Output 1000 × 1500 JPEG q90 (~250 KB). Jellyfin and the TV ask h=600 at most, so 1000 × 1500 is plenty and keeps RAM low.
4. **Review (dry):** write to `/data/posters/out/{jf_id}.jpg`; the private page `/media/posters` lists pending titles, current vs new side by side, with Approve / Skip per row and "Approve all pending". Owner "you" only, private front, same-origin guard as `media_write`.
5. **Write (on):** for approved rows only, inside the deploy window: save original (`/data/posters/orig/{jf_id}.{ext}` + `ImageTags.Primary`) → upload → set `LockData` → read back the new `ImageTags.Primary` and store it → status `live`. One title per pass step, 10 s pause, at most `POSTERS_PER_PASS` (default 30) per pass.
6. **Keep:** daily drift check (tag changed → re-apply once, log), and a `Revert` button per row and `revert-all` CLI (re-upload the saved original, clear `LockData` if we set it).

## Acceptance criteria

1. With `POSTERS` unset or `off`, nothing runs and no new route exists in the private front's route list (test).
2. `dry` never calls any Jellyfin POST/DELETE (test: the fake upstream asserts on method).
3. The TMDB pick prefers text-less, then votes, then size, with the three fallbacks in order (unit tests on a fixture list).
4. A render of a 2000 × 3000 source takes ≤ 2 s on the laptop and the peak RSS delta of the hub during a pass is ≤ 60 MB (measured on the NAS in Phase 2, number in the PR).
5. Titles of 8, 25 and 45 characters all stay inside the frame window; the 45-character one breaks to two lines (snapshot tests on the PNG bounding boxes).
6. A write saves the original and the tag first; a simulated failed upload leaves `posters.status = 'error'` and the original untouched (test).
7. `revert` restores the saved original byte-for-byte to the fake Jellyfin (test).
8. Drift: a changed live tag triggers exactly one re-apply per day (test with a clock).
9. The review page renders at desktop, iPad, phone and TV sizes with the hub's tokens (smoke test + options page shots).
10. Nothing logs a URL, key or user name (grep test over the module, as the other media modules have).
11. Budgets: review page warm p95 ≤ 150 ms (media list budget); joey-hub ≤ 200 MiB during a pass; NAS available ≥ 1,200 MB.

## Data

New table in `media.db`: `posters(jf_id TEXT PRIMARY KEY, kind TEXT, tmdb_id INT, source_path TEXT, source_lang TEXT, template_version INT, text_hash TEXT, status TEXT  -- pending|approved|skipped|live|error|no_source|reverted, orig_ext TEXT, orig_tag TEXT, live_tag TEXT, rendered_at TEXT, written_at TEXT, last_error TEXT)`. Files: `/data/posters/{out,orig}/`. Snapshots read: `jellyfin` (library lists). Env: `POSTERS=off|dry|on` (default off), `JELLYFIN_POSTER_API_KEY`, `TMDB_API_KEY` only if Q3 picks TMDB direct, `POSTERS_PER_PASS`, `POSTERS_PAUSE_S`.

## Performance budget

Media list / item page p95 ≤ 150 ms (the review page); joey-hub ≤ 200 MiB; NAS available ≥ 1,200 MB during the first NAS dry-run pass and the pilot write. Measured with `scripts/budgets.py` where it exists, else `docker stats` sampled every 5 s through a pass, numbers in the PR.

## Phases (step → verify)

The phases were re-cut on 2026-10-28 with B.'s picks. Phase 1 below is the builder brief of that date, and it replaces the draft's phases 1 and 2. The draft's phase 3 onward stays as written; read "Phase 3" there as the first live phase (phase 2 in the brief).

**Phase 1: renderer, pick, template kit, dry cache, review page. No live writes.**
- Add `pillow` → verify: the hub image builds, and the size change is in the PR.
- Renderer + kit → verify: layout tests (anchors, auto-fit, wrap); 6 samples rendered into `JoeyTV\review\JY-260\p1-samples\`; peak RAM measured.
- Pick → verify: unit tests on a `RemoteImages` fixture.
- `POSTERS=dry` → verify: a dry pass on fakes renders, writes sidecars and makes GET calls only.
- `/media/posters` → verify: household-only and no-network tests; B. reviews the samples.

- Seasons and the rating rule (2026-10-28) → verify: tests for 1 vs many seasons, "Season N" items, specials skipped, the 6.0 rule with its setting; a real-art sample set with 2 series and 2 season posters.

**Phase 2 (the draft's phase 3): pilot write, 5 titles.** Writes cover films, series and their Season items. Auto-approved rows (rating ≥ 6.0) go without review after the pilot. Hands bundle (one state window): B. creates `JELLYFIN_POSTER_API_KEY` in Jellyfin Dashboard → API Keys and appends it with `nas_scripts/append_env.sh`; recreate joey-hub. Claude sets `POSTERS=on` with `POSTERS_ALLOWLIST=<5 jf_ids>` → verify: the 5 show in Jellyfin web, Joey Media and Joey TV (`/img` cache for those refs purged, `jf:<id>` h=240/600); revert one and confirm the original is back; drift check runs clean the next day. B. says `accepted` on the pilot.
**Phase 4: backfill + steady state.** Remove the allowlist; the loop writes approved rows at 1 per 10 s, deploy-window only; new titles flow through dry → review → approve (or Q2's auto-approve) → verify: `posters` counts in the hub log per pass; NAS available stays ≥ 1,200 MB; no errors after a week.
**Phase 5 (B.'s "not urgent"): the sub-line.** Series: "Seasons 1–5 · 2019–2024" from the Jellyfin item (`ChildCount`, `ProductionYear`, `EndDate`/`Status`: "2019–" while running); films: year only or nothing (Q7). Bump `template_version` → every series re-renders → review → write.
**Phase 6 (optional): episodes.** Only if Q6 picks B or C.

## Out of scope

Episodes (unless Q6 says otherwise); backdrops/logos; fanart.tv; writing `poster.jpg` into media folders; a Canva account or token store (Option A, kept as a documented swap); Georgina's or friends' views (they see the Jellyfin image like everyone).

## Accept checklist (B., on the preview)

1. `/media/posters` opens on phone and desktop; rows show current vs new; Approve / Skip work; "Approve all pending" asks once.
2. In `dry`, the Jellyfin item is unchanged after a pass (B. opens one title in Jellyfin web).
3. Pilot: the 5 titles show the new poster in Jellyfin web, Joey Media and Joey TV rows.
4. Revert on one title restores the old poster within one pass.
5. A Jellyfin "Refresh metadata" (default mode) on a pilot title keeps the custom poster.

## Questions for B.

**Q1. Which option?** A (Canva Autofill, Pro subscription, cloud renders) / **B (design in Canva, NAS renders with Pillow)** / C (no Canva). Recommendation: **B**.

**Q2. Steady-state approval after the pilot.** A: every new title waits on the review page until approved / **B: auto-approve when the pick is a text-less poster with ≥ 5 votes; only fallbacks (English poster, low votes) wait for review** / C: auto-approve everything. Recommendation: **B**.

**Q3. Where the TMDB list comes from.** **A: Jellyfin's `RemoteImages` proxy, no new key** / B: TMDB direct with a free `TMDB_API_KEY` (B.'s hands, one more secret). Recommendation: **A**, falling to B if the Phase 1 GET shows Jellyfin's proxy hides `Language`/votes.

**Q4. The write key.** **A: a separate `JELLYFIN_POSTER_API_KEY` (revocable on its own)** / B: reuse `JELLYFIN_API_KEY`. Recommendation: **A**.

**Q5. The lock.** **A: `LockData` on the item + daily drift re-apply** / B: also "Save artwork into media folders" (poster.jpg beside the file; a NAS file write into arr folders). Recommendation: **A**.

**Q6. Episodes.** **A: leave episode stills alone** / B: episode gets the series frame with "S02 · E05 · Episode name" (a 2:3 image in 16:9 rows) / C: later item. Recommendation: **A**.

**Q7. Film sub-line in phase 5.** **A: year only ("2019")** / B: nothing under a film title / C: year · runtime. Recommendation: **A**.

**Q8. Frame and font (the options page).** Layout 1 (band: dark band across the centre, title in it) / **Layout 2 (clear: poster full-bleed, title on the centre line with a soft scrim)** / Layout 3 (frame: inset poster with a border, title in the lower third). Font: Geist (already the hub font, OFL, works in Pillow) or a Google font B. names from Canva. Recommendation: **Layout 2, Geist**.

**Q9. Review order for the backfill.** **A: Recently added first, then alphabetical** / B: alphabetical. Recommendation: **A**.

## Shipped notes

Phase 1 (draft PR, 2026-10-28, not merged or deployed):
- Measured on the laptop (`scripts/posters_samples.py`): one render of a 2000 × 3000 JPEG source raises the process peak by 13.0 MB (RSS 26.9 MB before, peak 39.9 MB after). After the fix round: +13.1 MB, 120–142 ms per render, posters 49–94 KB. The NAS numbers come with phase 2.
- Hub image: Pillow 12.2.0 adds a 7.1 MB wheel, 19.5 MB unpacked (manylinux x86_64).
- Samples: `C:\Users\b.edwards\Desktop\Claude\JoeyTV\review\JY-260\p1-samples\` (6 posters, a contact sheet and `samples.log`). They use placeholder art. The series samples have the phase-2 sub-line switched on, to show it.
- Builder notes for review:
  - The routes are always registered, and the handlers 404 while `POSTERS=off`, as `PLAYER_API` does. So criterion 1, "no new route", reads as "no served route".
  - Fix round, coordinator 2026-10-28:
    - long titles are never cut above the floor (up to 3 lines, floor 40 px);
    - the scrim is one gradient with no seam;
    - the placeholder art no longer has a straight-edged band;
    - a 3-line title no longer sits on the sub-line: the bottom-anchor mode with `title_gap` (second fix round).
  - Review hardening (two reviews PASS; coordinator 2026-10-28):
    - decode caps: a JPEG is drafted and must decode to at most 8 M pixels; a PNG or WebP to at most 4 M; headers over 64 M are refused before decoding. One render stays under about 30 MB.
    - titles are capped at 120 characters (flagged), and the line split uses prefix sums, so a 600-word title lays out in well under 1 s;
    - a rejected kit falls back to the starter kit, with a notice on `/media/posters`;
    - file-size caps: json 64 KB, PNG 10 MB, font 5 MB;
    - a pass is skipped, and logged, when NAS available memory (the `system` snapshot's `ram_free_gb`) is under 1,300 MB or unknown.
  - The dry pass is its own hourly loop in `hub/tasks.py`, not part of `media_warmup`.


## Sources (read 2026-10-28)

canva.dev: Connect autofill guide, autofills create-job reference, brand-templates reference, exports create-job reference, asset-uploads reference, authentication guide; canva.com/pricing. developer.themoviedb.org movie-images reference + TMDB talk threads on `include_image_language=null`. Jellyfin: Python SDK ImageApi (`POST /Items/{itemId}/Images/{imageType}`, base64 body), Jellyfin/Emby forum threads on "Lock this item" and image replacement, jellyfin-plugin-webhook README (ItemAdded exists but has open "does not fire" issues #199/#252, hence polling). Local: `hub/media_warmup.py`, `hub/images.py`, `hub/media_write.py`, `hub/media_requests_approve.py`, `hub/tasks.py`, `deploy/.env.example`, `JoeyTV/review/nas-memory-2026-10-27.md`.
