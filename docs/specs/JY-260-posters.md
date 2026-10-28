# JY-260 Automated custom posters (films and series)

Status: ready (2026-10-28); phase 1 building
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

What they mean for the build:

- **Q1B:** B. designs in Canva; joey-hub renders each poster with Pillow. No Canva account at run time.
- **Q2B:** after the pilot, auto-approve a text-less pick with at least 5 votes; fallbacks wait for review (phase 3).
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
- **Validation:** a bad template is refused as a whole with every problem listed by name. The review page shows the list, and nothing renders until it is fixed. The last good renders stay.
- **Starter kit:** layout 2 "Clear" with Geist (OFL, the hub's own font file) and layout 3's text positions. It also has `guide.png`, a safe-area overlay B. can drop into Canva as a reference layer.
- **Guide:** `docs/posters-template-guide.md` covers the step-by-step in Canva, the exports, the safe areas, changing the font and previewing before anything is applied.

## Phase 1 as built (no live writes)

1. **Renderer** (`hub/media_posters_render.py`): art + kit → JPEG q90. The title's lines always fit between `title_anchor` and `sub_anchor`, and the title auto-fits in this order:
   - it shrinks on one line from `max_size` to `wrap_at` (60);
   - it wraps to 2 balanced lines, then 3 (`max_lines`), each from the largest size that fits;
   - the last line count may go down to `min_size` (40), the hard floor;
   - only past the floor is it ellipsised, and then it is flagged: `truncated` in the sidecar, a warning in the log with a count only, and "Title cut short" on the review page.

   The scrim is one smooth gradient that starts at 56 %, with `solid` 1.2, so it is still darkening at the bottom edge: no seam and no flat band. The sub-line for a film is the year (Q7A). For a series, "Seasons a–b · yyyy–yyyy" sits behind `POSTERS_SERIES_SUB=on`, which is off by default (phase 2 switch). JPEG sources decode at reduced size (`draft`), so peak memory stays low. It also runs as a CLI for previews (`python -m hub.media_posters_render`).
2. **Pick** (`hub/media_posters.py`): `GET /Items/{id}/RemoteImages?type=Primary&providerName=TheMovieDb&includeAllLanguages=true` through `media_jellyfin.get`. Order: text-less (no language) first, then English, then any other; within each, more votes first, then more pixels. Art is fetched only from `https://image.tmdb.org/t/p/`, capped at 5 MB.
3. **Flag:** `POSTERS=off|dry|on`, default off. `dry` renders up to `POSTERS_PER_PASS` (30) titles per hourly pass into `<IMG_CACHE_DIR>/posters/` (one JPEG + one JSON sidecar per title) and lists them. `on` is phase 2: today it logs once and behaves exactly as `dry`. No code path writes to Jellyfin.
4. **Review page** `GET /media/posters`: household only, private front. The media front and friends get the 404 page, and so does everything while `POSTERS=off`. Original (`/img/jf:<id>?h=600`) and proposed (`/media/posters/img/<id>`) sit side by side, with the pick words and the template state. It reads local files only: no network on render.

**Phase 1 tests (written red first):** layout maths (anchors, margins, auto-fit, the 2-line wrap, the ellipsis), the text-less pick and its order, `template.json` validation (the starter passes; a bad one is rejected naming each problem), household-only page, no network on page render, no Jellyfin write call anywhere (a source scan plus a fake session that allows GET only).

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

**Phase 2 (the draft's phase 3): pilot write, 5 titles.** Hands bundle (one state window): B. creates `JELLYFIN_POSTER_API_KEY` in Jellyfin Dashboard → API Keys and appends it with `nas_scripts/append_env.sh`; recreate joey-hub. Claude sets `POSTERS=on` with `POSTERS_ALLOWLIST=<5 jf_ids>` → verify: the 5 show in Jellyfin web, Joey Media and Joey TV (`/img` cache for those refs purged, `jf:<id>` h=240/600); revert one and confirm the original is back; drift check runs clean the next day. B. says `accepted` on the pilot.
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
    - the placeholder art no longer has a straight-edged band.
  - The dry pass is its own hourly loop in `hub/tasks.py`, not part of `media_warmup`.


## Sources (read 2026-10-28)

canva.dev: Connect autofill guide, autofills create-job reference, brand-templates reference, exports create-job reference, asset-uploads reference, authentication guide; canva.com/pricing. developer.themoviedb.org movie-images reference + TMDB talk threads on `include_image_language=null`. Jellyfin: Python SDK ImageApi (`POST /Items/{itemId}/Images/{imageType}`, base64 body), Jellyfin/Emby forum threads on "Lock this item" and image replacement, jellyfin-plugin-webhook README (ItemAdded exists but has open "does not fire" issues #199/#252, hence polling). Local: `hub/media_warmup.py`, `hub/images.py`, `hub/media_write.py`, `hub/media_requests_approve.py`, `hub/tasks.py`, `deploy/.env.example`, `JoeyTV/review/nas-memory-2026-10-27.md`.
