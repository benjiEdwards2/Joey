# JY-264 Engine seam: one Jellyfin adapter + a `library_index`

Status: ready (this PR builds phases 1-3; phases 4-6 later)
Size: M
Live risk: NAS write (rewrites `media.db` rows after a Jellyfin rebuild; backup first, audit, undo)
Area: `hub/library_index.py`, `hub/library_reattach.py` (new), `hub/media_store.py` (one STEPS entry), `hub/tasks.py` (one loop line), `hub/media_plays.py` + `hub/media_item.py` (one upsert call each), `connectors/feeds/jellyfin.py` + `connectors/schema/data/jellyfin.schema.json` + `config/sample_snapshots/jellyfin.json` (additive row keys), `docs/connector-contract.md` (dated note), `tests/hub/test_library_*.py`, `tests/hub/fake_library.py`; built also: `hub/guest.py` (drop `path` on the media front), `deploy/.env.example`, `deploy/preview/` + `scripts/joey_preview.py` (`LIBRARY_INDEX` forced off in previews), `hub/README.md`
Needs: none
Options page: none (phases 1-3 add no screen; the report is the CLI output and the `reattach_run` row)
Date: 2026-10-28 (spec draft 2026-10-28, marked ready 2026-10-28)

## B.'s picks and words (2026-10-28)

B., 2026-10-28: "Jy 58 all recommended and jy 264." The ask was "JY-264 all recommended · JY-058 all recommended",
so every question below takes its recommended option:

1. **Q1 = A.** After a rebuild, rewrite the old `jf:` keys to the new `jf:` ids.
2. **Q2 = A.** Strong matches (provider id, path) apply on their own, with undo; title + year and ambiguous matches only go into the report.
3. **Q3 = A.** Jellyfin user ids stay out of this item.

Builder brief scope: phases 1-3 only (P1 index, P2 matcher + dry-run report, P3 apply + backup + audit + undo,
including the JY-260 poster store folders). P4-P5 (the adapter move) and P6 come later.

B., 2026-10-28: "Can you show me the hardening items and can we lock them in if nothing changes."
Source idea: JY-261 study, section 4 ("the first small, reversible step").

**Goal.** A Jellyfin library rebuild (library removed and re-added, a fresh Jellyfin install, a move to the box in
JY-059 without its `/config`) gives every film, series, season and episode a new Jellyfin id. Today that silently
orphans B.'s and Georgina's show ratings, diary, rankings and play history. After JY-264, Joey notices the id change,
reports what it would re-attach, re-attaches it, and can undo it. Separately, every Jellyfin HTTP call in the hub goes
through one adapter module, so the next Jellyfin API break is fixed in one file.

**Out of scope.** Moving keys to `tmdb:`/`tvdb:` (JY-261 option C, step 2); Jellyfin **user** ids (friend owners
`jf:<user id>`, Seerr's `jellyfinUserId`, player tokens); the connector process's own HTTP client; scripts under
`scripts/`; any live write to Jellyfin.

---

## 1. The problem, made concrete

Counted from code, not from live data.

**Where a Jellyfin item id is stored (8 tables, 15 columns, one folder tree):**

| Store | Column(s) holding a Jellyfin item id | Written by | What breaks after a rebuild |
|---|---|---|---|
| `rating` | `item_key` (`jf:<SeriesId>` for every show rating, `jf:<SeasonId>` / `jf:<EpisodeId>` for season and episode level, `jf:<Id>` for a film with no TMDB id) | `media_item.py:392` (series key is always `jf:`), connector `_jf_key` | Show, season and episode ratings vanish from item pages, To rate, Wrapped |
| `diary` | `item_key`, `show_key`, `season_key` | `media_db.sync_diary_from_history`, `media_plays.friend_diary`, manual adds | Every Jellyfin-sourced TV diary row stops grouping under its show; the item page's diary dates go blank |
| `ranking` | `item_key` | rankings page | Ranked shows lose their poster/title link |
| `nextup_hidden` | `series_key`, `episode_id` | `media_db.hide_next_up` | Hidden Next Up rows come back |
| `rating_skip` | `key` | To rate Skip / Skip show | Skipped shows reappear in To rate |
| `watchlist` | `item_key` (rarely `jf:`; usually `tmdb:`) | watchlist | Only the `jf:` rows orphan |
| `play` | `jf_id`, `item_key`, `show_key`, `season_key`, `episode_key` | recorder `media_plays.play_from_session` | History, most-played, Wrapped, `watch_count`, `show_runtimes` split one title into "before" and "after" |
| `poster` | `jf_id` (primary key) | JY-260 poster job | Joey posters stop being served; the write-back runs again from scratch |
| Poster store on disk | folder name `<POSTERS_DIR>/<jf_id>/` | `media_posters_store.save` | Same as above; the `orig.<ext>` backup is stranded |

Not affected: `episode_rating` (IMDb keys), `media_follows` / `media_follow_adds` (TMDB ids), `setting`, the awards
tables, the image disk cache (rebuilt on demand), and owner columns (user ids, not item ids).

**Also broken but not stored:** URLs `/media/item/{jf_id}` (bookmarks, the TV shell's deep links) and the snapshot's
`jf_id` fields (rebuilt on the next fetch).

**Which keys are safe already.** Films with a TMDB id are `tmdb:<id>` (connector `_jf_key`). Library show rows in the
snapshot are `tmdb:`/`tvdb:` (`_shows`), but the rating written from the item page and every history-derived diary
row use `jf:<SeriesId>` because the episode payload carries no series provider id. So the exposure is: **every TV
rating at every level, every TV diary row, all of `play`, all of `poster`, and films with no TMDB id.** In practice
that is most of what B. has entered since F7/F8.

**Finding to flag (not fixed here):** the same show has two keys today, `tmdb:`/`tvdb:` in the library list and
`jf:` on ratings and diary. `media_home.py:402` and `media_because.py:81` already bridge them by `jf_id`. The index
below gives a proper bridge; unifying the keys is JY-261 C work.

---

## 2. The `library_index` design

### 2.1 Table (in `media.db`, new `media_store.STEPS` entry, user_version 5 -> 6)

```
library_index(
  jf_id         TEXT PRIMARY KEY,   -- Jellyfin item id, 32 hex
  kind          TEXT NOT NULL,      -- movie | series | season | episode
  title         TEXT,
  year          INT,
  path          TEXT,               -- file (movie, episode) or folder (series, season); NULL when unknown
  tmdb_id       TEXT, tvdb_id TEXT, imdb_id TEXT,
  series_jf_id  TEXT,               -- season, episode
  season        INT, episode INT,   -- season, episode
  version_of    TEXT,               -- multi-version: the primary item's jf_id, else NULL
  first_seen_at TEXT, last_seen_at TEXT,
  gone_since    TEXT,               -- set when absent from a complete library fetch; cleared if it comes back
  superseded_by TEXT                -- set by a re-attach apply: the new jf_id
)
indexes: (tmdb_id), (tvdb_id), (imdb_id), (path), (series_jf_id, season, episode)
```

Rows are never deleted. A vanished id keeps its row with `gone_since`, which is exactly what the re-attach needs.

### 2.2 How it is filled (no new live polling)

| Source | Gives | Change needed |
|---|---|---|
| Jellyfin snapshot library lists (`movies`, `shows`, her two), refreshed at most every `JELLYFIN_LIBRARY_EVERY_S` (900 s) | movie + series rows | Connector adds `Path` to `MOVIE_FIELDS` / `SHOW_FIELDS` and three additive, optional row keys `path`, `tvdb`, `imdb` (`tmdb` already in `item_key`). Additive optional keys are allowed under `docs/connector-contract.md` with a dated contract note, like the arr and qBittorrent additions |
| Snapshot history, resume, next up (already fetched with `SeriesId`, `SeasonId`, `ParentIndexNumber`, `IndexNumber`, `ProviderIds`) | season + episode rows for everything watched | Hub-side read only; add `Path` to `ITEM_FIELDS` and the history `Fields` |
| Play recorder sightings (`/Sessions`, already polled every 60 s) | episode rows, the moment something plays | Upsert one row per sighting from the `NowPlayingItem` it already has |
| Item page GET (`media_item.FIELDS` already asks for `Path`, `ProviderIds`) | any item a person opens | Upsert on a cache miss only |

The hub-side writer is one function, `library_index.sync_from_snapshot(envelope)`, called where the hub already loads
the Jellyfin snapshot, and skipped unless `library_fetched_at` changed since the last sync (so at most every 15 min).
Upserts update `last_seen_at`, provider ids and path; they never blank a known value with a missing one.

**Absence rule.** An id is marked `gone_since` only when it is missing from a library fetch that was **complete**:
the list's `TotalRecordCount` is at most `LIBRARY_FETCH_LIMIT` (2,000) and the call did not fail. Episodes and seasons
are never marked gone from the library list (it holds none); they are re-matched through their series (section 2.3).

### 2.3 Matching rule after a rebuild (old id -> new id)

Tiers, first hit wins, same `kind` only:

| Kind | Tier 1 (provider id) | Tier 2 (path) | Tier 3 (title + year) |
|---|---|---|---|
| movie | `tmdb_id`, then `imdb_id` | exact `path` | normalised title + year, unique |
| series | `tvdb_id`, then `tmdb_id`, then `imdb_id` | exact folder `path` | normalised title + year, unique |
| season | parent series matched, then same season number | folder `path` | none |
| episode | parent series matched, then same season + episode number; `tvdb` episode id if present | exact file `path` | none |

Seasons and episodes of a matched series are resolved with **one** `/Shows/{new_series_id}/Episodes` call per
affected series, only during a re-attach run (bounded, not polling).

Path matching compares the path after stripping a configurable prefix (`LIBRARY_PATH_PREFIXES`), so a move from
`/data/media/...` on the NAS to `/mnt/media/...` on the box still matches.

### 2.4 Collisions and multi-version items

- **Two new candidates for one old id** (same TMDB id in two libraries, or a 4K and a 1080p copy indexed as separate
  items): try the next tier as a tie-break (path, then title+year). Still two: **no re-attach**; listed as
  "ambiguous" in the report for B.
- **Two old ids for one new candidate** (a duplicate that Jellyfin has since merged): both re-attach to the same new
  id; primary-key clashes are handled by the conflict rule in section 3.3.
- **Multi-version items** (Jellyfin groups `Movie (1080p).mkv` and `Movie (2160p).mkv` into one item with alternate
  versions): index the primary and record each alternate's id with `version_of = <primary>`. Re-attach always targets
  the new primary. Joey rows never point at an alternate today; if one does, it moves to the primary.
- **Tier 3 matches** are reported separately and treated as weak (see Q2).

---

## 3. The re-attach job

### 3.1 When it runs

Inside `sync_from_snapshot`, after the upsert. A **rebuild is suspected** when at least one indexed movie or series
that any Joey table references has `gone_since` set on **two consecutive complete fetches** and a tier-1 or tier-2
candidate exists under a new id. A **guard** holds the run while the library is still scanning: the new list's count
must be within 5 % of the previous complete fetch's count on those two fetches. Nothing runs on a single fetch.

It can also be run by hand: `python -m hub.library_reattach --dry-run | --apply | --undo <run_id>` (one script, PASS/FAIL
lines, log file), for the JY-059 move.

### 3.2 Dry-run report (always first)

Every run writes a dry-run first, stored in `reattach_run` and shown as one Server-page attention line plus a page at
`/server/reattach/<run_id>`:

- per tier: old id, new id, kind, title, matched on what;
- per table/column: how many rows would change;
- ambiguous (no action), unmatched (no action), weak tier-3 matches (held unless Q2 says otherwise);
- conflicts that will be skipped (section 3.3).

### 3.3 Apply, safety and undo

- **Never deletes a row.** Apply is `UPDATE <table> SET <col> = 'jf:<new>' WHERE <col> = 'jf:<old>'` (and the bare
  `jf_id` columns), one transaction for the whole run, across the 15 columns in section 1.
- **Conflicts:** when an update would break a primary key or unique constraint (B. already rated the new id, a diary
  row for the same day exists under the new key), that one row is left as it is and recorded as a conflict. Nothing
  is merged or overwritten.
- **Before apply:** an SQLite online backup of `media.db` to `/data/backups/media-pre-reattach-<run_id>.db`.
- **Audit tables** (new, same STEPS entry):
  `reattach_run(id, started_at, mode, trigger, summary_json, applied_at, undone_at)` and
  `reattach_change(run_id, table_name, row_ref, column, old_value, new_value)`, one row per changed cell.
- **Poster store:** the folder `<old>/` is **copied** (not moved) to `<new>/` and a `poster` row for the new id is
  inserted with the old row's fields; the old row and folder stay. Whether the existing JY-260 write-back then pushes
  the poster to the new Jellyfin item follows its own rules, unchanged.
- `library_index.superseded_by` is set on each old row.
- **Undo** (`--undo <run_id>` or a button on the run page): replays `reattach_change` in reverse, but only where the
  cell still holds `new_value`; anything since changed is skipped and listed. Copied poster folders and rows are
  removed by undo (they are the only things apply created). Undo is itself a logged run.

---

## 4. The adapter module

**Recommendation: widen `hub/media_jellyfin.py`** rather than add a new file. It is already "the one place that reads
JELLYFIN_URL / JELLYFIN_API_KEY", tests fake upstreams at `hub.media_jellyfin.requests`, and nine modules already
import it. It gains `post`, `delete`, `get_bytes` (images) and `auth_header(token=None)` (the 12.2 `MediaBrowser`
form), plus the contract's "facts this rests on" as its docstring.

**Where calls are today** (approximate grep at 3837450; phase 4 confirms it with a test gate):

| Group | Modules | Their own Jellyfin HTTP today |
|---|---|---|
| Already via the adapter's `get` only | `guest.py`, `identity.py`, `media_watchlist_everyone.py` | none |
| Read paths with some own HTTP | `media_item.py`, `media_files.py`, `media_plays.py`, `media_posters.py`, `media_season_state.py`, `media_rank.py`, `server_space.py` | `/Users/{uid}/Items...`, `/Shows/{id}/Episodes`, `/Shows/{id}/Seasons`, `/Items/{id}/RemoteImages`, `/Sessions`, `/System/Info/Public` |
| Images | `images.py` | `/Items/{id}/Images/Primary`, `/Backdrop/0` |
| Writes | `media_resume.py`, `media_posters_write.py`, `player_api.py` | `UserData`, `PlayedItems`, image upload, `/Sessions/Playing*` |
| Auth (highest risk) | `guest_auth.py`, `media_guest_requests.py` | `/QuickConnect/*`, `/Users/AuthenticateBy*`, `/Users/Me`, `/Sessions/Logout`, `/Devices*` |
| Not moved | `connectors/feeds/jellyfin.py`, `connectors/feeds/media_status.py`, `scripts/*` | separate process / tooling |

**Order:** reads, then images, then writes, then auth. One PR per group.

**Shim, so each PR changes no behaviour:** each module keeps its local helper names (`_get`, `_post`, ...). In the
PR the helper body becomes a one-line delegate to `media_jellyfin`; call sites are untouched. Same URL, params,
headers, timeouts and exception types (the adapter re-raises what `requests` raised, and `RuntimeError("HTTP nnn")`
as `get` does today). Error logging stays in the caller, exception type only.

**Ratchet test:** `tests/hub/test_engine_seam.py` greps `hub/` for `JELLYFIN_URL`, `JELLYFIN_API_KEY` and
`MediaBrowser` outside `media_jellyfin.py`, against an allowlist that each PR shrinks. It ends empty.

---

## 5. Phases (step -> verify)

All tests run against the fake Jellyfin. **Fake changes (phase 1):** extend `tests/hub/fake_jellyfin.py` with a small
library fixture (3 films incl. one without a TMDB id and one with two versions, 2 series with seasons and episodes,
real 12.2 response shapes) and a `rebuild(drop_provider_ids=(), move_prefix=None, partial=False)` method that
re-mints every item id while keeping provider ids and paths (optionally dropping some ids, changing the path prefix,
or returning a half-scanned library). Plus a seeded `media.db` fixture holding rows in all 15 columns.

| # | Step | Verify |
|---|---|---|
| P1 | `library_index` table + STEPS entry; connector adds `Path` + `path`/`tvdb`/`imdb` row keys (contract note); `sync_from_snapshot`, recorder and item-page upserts; absence rule | Fixture snapshot fills the index with every kind; a second sync with the same `library_fetched_at` writes nothing; a truncated fetch (count > limit) marks nothing gone; connector fixture snapshot diff shows only the additive keys; existing suite green |
| P2 | Matcher + detection + guard + dry-run report (`reattach_run`, run page, attention line, CLI `--dry-run`) | `rebuild()` then two syncs: report maps every seeded old id to its new id with the right tier; `partial=True` holds the run; one sync alone holds it; `drop_provider_ids` falls to path; `move_prefix` still matches via prefixes; two-version film targets the primary; an injected duplicate is "ambiguous"; **media.db byte-identical after a dry-run** |
| P3 | Apply + backup + audit + conflicts + poster copy + undo | After apply: every seeded row in the 15 columns points at the new id, row counts per table unchanged, no row deleted; a pre-seeded conflict row is untouched and listed; backup file exists; undo restores the pre-apply DB content (table-by-table compare); undo after a later edit skips that cell and lists it; item page, To rate, Diary, History render the old ratings against the new ids (TestClient) |
| P4 | Adapter widened (`post`, `delete`, `get_bytes`, `auth_header`) + ratchet test with today's allowlist; reads group moved | Adapter unit tests against the fake (status, headers, timeouts, exception types); moved modules' existing tests pass unchanged; ratchet allowlist shrinks |
| P5 | Images, writes, auth groups moved (3 PRs) | Per PR: existing tests unchanged and green; the guest sign-in suite (fake 12.2 Quick Connect) green; ratchet allowlist empty after the last PR |
| P6 | Docs: `docs/connector-contract.md` note, `hub/README.md` (adapter rule, re-attach CLI), HITLIST close-out | Doc review in the item's reviewer pass |

P1 to P3 and P4 to P5 are independent tracks but touch the same `hub/media_*` area, so they run one after the other.

---

## 6. Size and risks

| Phase | Size | Builder (size table) |
|---|---|---|
| P1 index + fill | S (2 days) | Sonnet + 1 Sonnet reviewer |
| P2 matcher + dry-run | S (2 days) | Sonnet + 1 Sonnet reviewer |
| P3 apply / audit / undo | M (3 days): it rewrites user data | Opus + 1 Sonnet reviewer |
| P4 adapter + reads | S (1 to 2 days) | Sonnet + 1 Sonnet reviewer |
| P5 images, writes, auth | S/M (2 to 3 days), auth PR is the care point | Opus for the auth PR, Sonnet for the rest |
| P6 docs | S (half a day) | Sonnet |
| **Total** | **M, about 2 weeks** (JY-261 said about 1 week; the undo and the auth move are what add the second) | |

**Risks**
1. **False re-attach** (wrong old -> new mapping) moves ratings onto the wrong title. Mitigation: tier order, kind
   check, ambiguity = no action, two-fetch + count guard, undo, backup.
2. **A half-scanned library looks like a rebuild.** Mitigation: the complete-fetch rule and the 5 % count guard.
3. **Library over 2,000 items** makes "absent" meaningless. Mitigation: the `TotalRecordCount` check; nothing is ever
   marked gone from a truncated list (raising the limit is a separate item if it ever trips).
4. **Episodes never watched are not in the index.** They hold no Joey rows, so nothing to orphan; watched ones are
   indexed by the recorder and history.
5. **Snapshot data change** breaks a consumer. Mitigation: additive optional keys only, fixture diff in P1.
6. **Auth move regresses friends' sign-in.** Mitigation: last in order, shim (no call-site change), the existing
   fake 12.2 sign-in suite, Opus builder.
7. **User ids also change** on a fresh install (friend owners, Seerr mapping, player tokens). Not covered here; see Q3.

---

## 7. Questions for B.

**Q1. After a rebuild, rewrite the old `jf:` keys to the new `jf:` ids, or switch them to `tmdb:`/`tvdb:` keys now?**
A) Rewrite to the new `jf:` ids: everything else in Joey keeps working exactly as today. B) Switch to provider keys:
fewer future breaks, but it touches every reader of those keys (about 15 modules) and is JY-261 C's step 2.
*Recommend A.* The index already holds the provider ids, so B stays a later, separate item.

**Q2. When a rebuild is detected, apply the re-attach on its own or wait for you?**
A) Apply provider-id and path matches on their own, hold title+year matches and ambiguous ones for your tap, and show
the report with an Undo button. B) Always wait for your tap on the report. C) Dry-run only; Claude applies by hand.
*Recommend A.* Strong matches are near-certain, and undo plus the backup cover the rest. Ratings stay visible without
anyone having to act.

**Q3. Jellyfin user ids (friends' accounts, Seerr mapping, player tokens) also change on a fresh install. Cover that here?**
A) No. JY-059 moves Jellyfin with its `/config` copied, which keeps every id, and a line goes into the JY-059 spec.
B) Yes, add a user-id re-map to this item (about +3 days, auth area). *Recommend A.* A copied `/config` avoids the
problem, and this item's re-attach still covers item ids if the copy is ever skipped.

---

## Sources read
`HITLIST.md` (JY-261, JY-264), `JoeyTV/review/JY-261/JY-261-replace-jellyfin-study.md`, `hub/media_db.py`,
`hub/media_store.py`, `hub/media_plays_db.py`, `hub/media_plays.py`, `hub/media_jellyfin.py`, `hub/media_item.py`
(rating keys, diary dates), `hub/media_posters.py`, `hub/media_posters_store.py`, `hub/media_watchlist_db.py`,
`hub/media_follow.py`, `hub/media_episode_ratings.py`, `connectors/feeds/jellyfin.py`, `connectors/base.py`,
`docs/connector-contract.md` (additive-key precedent), `tests/hub/fake_jellyfin.py`, and a grep of `jf:` key minting
and Jellyfin endpoints across `hub/`. Not checked: live row counts (by design), whether any live `watchlist` row is
`jf:`, and Jellyfin 12.2's exact alternate-version payload (P2 captures a real redacted sample for the fake).

## Shipped notes

PR, commit and deploy: filled at close-out.

**Phases 1-3, as built (2026-10-28).**
- `hub/library_index.py`: media.db step 6 (user_version 5 -> 6) adds `library_index`, `library_index_state` and the
  audit tables `reattach_run` / `reattach_change` (column `column_name`, since `column` is an SQL keyword; `reattach_run`
  also has `undo_of`). One extra column on `library_index`: `gone_fetches` (how many complete fetches in a row missed
  the id), which the two-fetch rule needs. Filled from the snapshot's movie / show lists (you + her), its up next /
  now playing / recent history episode rows, Joey's own `play` and `diary` rows (they carry series, season and episode
  ids with numbers; not proof the id still exists, so they never clear `gone_since`), the recorder's `/Sessions`
  sightings and the item page's Jellyfin read. Those two only remember the item in memory (at most 500); the hub loop
  writes them, so a page render still opens one connection per thread and never creates media.db. The loop
  (`LIBRARY_INDEX=off` stops it) looks every minute and syncs only when `library_fetched_at` moved on. The media
  front never writes the index.
- Complete fetch: the hub sees no `TotalRecordCount`, so "complete" = the list is present and shorter than 2,000
  rows. A list of exactly 2,000 counts as truncated (stricter than the spec; nothing is marked gone from it).
- Guard: the last two complete fetches must both be within 5 % of a baseline count; the baseline moves only on a
  fetch where nothing new went missing. A half-scanned library holds; a library that grows or shrinks by more than 5 %
  in the rebuild holds until it is stable for two fetches.
- `hub/library_reattach.py`: matcher, dry run, apply, undo, `auto()` and the CLI (`python -m hub.library_reattach
  --dry-run | --apply | --undo <run_id>`, PASS / FAIL lines, appends to `library_reattach.log` beside media.db). The
  CLI accepts ids gone from one fetch (the JY-059 move); `auto()` needs two.
- Columns rewritten: the 15 in section 1, plus the `poster` image-ref column (`jf:<id>`) of rating, diary, ranking,
  rating_skip, watchlist and play, so re-attached rows keep their picture. `poster` rows and poster store folders are
  copied to the new id, never moved.
- An undone run's ids are not re-applied by `auto()` (B. undid it on purpose); `--apply` by hand still can.
- Connector: `Path` added to the movie / series library `Fields`; rows gain optional `path`, `tvdb`, `imdb`
  (`docs/connector-contract.md` note, schema properties, `config/sample_snapshots/jellyfin.json` regenerated: only
  the two `tvdb` keys moved). Outside the area: `hub/guest.py` drops `path` from rows on the media front, so friends
  never get a NAS file path.

**Review fixes (2026-10-28, PR #265 reviewer A):**
- Undo removes a copied poster row or folder only while it is exactly what the run created (a row snapshot and a
  file fingerprint in `reattach_change.detail`); anything the poster job changed since is kept and listed.
- A copied poster row starts with no Jellyfin write-back state (`wrote`, `live_*`, `orig_*`, locks, `manual`,
  failures reset) and the old item's `orig.*` file is not copied: that state belongs to the old id.
- Poster folders are copied inside the apply transaction, through a temp folder renamed into place; any failure
  removes the copies and marks the run `apply-failed`.
- Never applied, reported as ambiguous: two old ids landing on one new id (and the seasons / episodes of such a
  series), two new episodes with one season + episode number (or one path), a season number with two season ids,
  and a path match whose known provider ids disagree.
- Auto cap (refined by the orchestrator the same day): an automatic run may move more than 25 % of the indexed
  items only when every change is a provider-id match (films and series on tmdb / tvdb / imdb; their seasons and
  episodes by number under such a series), nothing in the run is ambiguous (no tie, no many-to-one) and the library
  count is identical on the two complete fetches. That is the full-rebuild case, and it applies on its own. Any
  other run over 25 % applies nothing and stores a report (`capped`).
- Until the report has a screen: `scripts/joey_reattach.py report | dry-run | apply RUN_ID | undo RUN_ID` runs the
  hub CLI over ssh with `docker exec joey-hub` (household only, B.'s NAS key). `apply RUN_ID` applies a stored
  report only while a fresh plan still makes exactly its matches. The CLI output carries run ids, counts, kinds,
  titles and tiers: no Jellyfin ids, no paths, never the NAS host.
- Pre-reattach backups: the newest 5 are kept.

**Not built here (later phase or follow-up):**
- The `/server/reattach/<run_id>` page, the Server attention line and the Undo button (they are screens and need an
  options page). Today the report is the `reattach_run.summary_json` row, the CLI output and the log file.
- Multi-version items: `version_of` exists and alternates are excluded from candidates, but nothing fills it yet
  (the 12.2 alternate-version payload sample is still to capture).
- Seasons and episodes Joey never saw (no play, diary, snapshot row or item page) are not in the index, so a rating
  on one of them is reported as unmatched rather than re-attached.

**Test pins updated:** `SCHEMA_VERSION == 5` -> `6` in four media.db tests (step 6 is new); the connector's library
`Fields` pin and the show-row key set gain `Path` / the optional `tvdb` key. No test removed or weakened.
