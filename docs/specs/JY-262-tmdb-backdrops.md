# JY-262 TMDB backdrops: the first on Home, the second on the title page

Status: shipped 2026-10-28
Size: M
Live risk: none beyond a normal hub deploy (templates are unchanged; which backdrop URL the friends' TV pages ask for changes on the next deploy). No `tv/` change, no TV release.
Area: `hub/media_backdrop.py` (new), `hub/images.py` (the `/img` ref grammar), `hub/media_item.py` (a backdrop count on the item read), `hub/media_film.py` (the title page's backdrop line), `hub/tv_home.py` (the Home hero chain), `tests/hub/test_tmdb_backdrops_jy262.py` (new).
Needs: JY-259 phase 1 (PR #247, merged 2026-10-28).

B., 2026-10-28: "For the main image or background of the movie or series shown when highlighted or as a main image, etc. I would like the background to be used from TMBD. This can use the first background as the home page or carousel image, then if you go into the show. It shows the second background image or such."

## What changes

Jellyfin already stores a title's TMDB backdrops as Backdrop images at index 0, 1, 2... (`BackdropImageTags` on the item).

| Page | Draws | Fallbacks, in order |
|---|---|---|
| Home hero and the 16:9 Continue watching row (TV) | Jellyfin backdrop **0** | the cached TMDB backdrop (when this viewer's cached item read says Jellyfin holds none) → the blurred poster (JY-259) |
| Title page hero (film, series; an episode or season page uses its show's) | Jellyfin backdrop **1** | backdrop 0 when Jellyfin holds only one, or the count is not known → the cached TMDB backdrop when Jellyfin holds none |
| Off the server (Discover, requests): the title page | the cached TMDB backdrop (Seerr's `backdropPath`) | none |

- TV mode first. The title page hero also exists on web and phone (`media_film.html`, one template), so it takes the same index there; nothing else on web or phone changes.
- The count comes from the item read (`media_item`, the viewer's own cached read on the media front). An older cached read, a snapshot row or a fake without the key counts as "not known" and draws index 0, which every item with a backdrop has. An empty `BackdropImageTags` counts as none.
- `/img` gains `jfb:<id>/<n>` (n = 1 to 9) for Jellyfin backdrop n; plain `jfb:<id>` stays backdrop 0, so every cached file and warm-up entry keeps its name. Only `jfb` takes an index.
- No live call on render: the choice reads the item read and the Seerr title cache only. The image itself is a separate `/img` request through the existing proxy and its 30-day disk cache.

### The image width: 1280
Every backdrop is asked for at `?h=1280`, which the proxy maps to 1280 wide (Jellyfin `maxWidth=1280`, TMDB `w1280`).
- TMDB's size ladder is w300, w780, w1280, original. There is no 1920; the next step up is `original`, which is often 3840 wide and several MB. 1280 is the largest size that is never a 4K file.
- The TCL draws 1920 device px. 1280 is a 1.5x upscale, under the hero scrim (`.94` to `.55` dark gradient) and the bottom fade; the softening does not show. On the TV the backdrop is mood, not detail.
- It is the size the warm-up already fetches for backdrop 0 (`media_warmup.BACKDROP_H`) and that web uses, so Home and web share one cache entry per title. A 1280 JPEG at q85 is about 150 to 350 KB.

## Steps (step -> verify)
1. `media_backdrop`: the index choice (`jellyfin`, `title_page`, `count_of`) -> `test_home_draws_index_0_and_the_title_page_index_1`, `test_the_title_page_chain_jellyfin_then_row_then_tmdb`, `test_the_count_comes_from_backdrop_image_tags`.
2. `media_item` records `backdrops` (the art item's count; the show's for an episode or season) -> `test_the_item_read_records_how_many_backdrops_jellyfin_holds`.
3. `/img` reads `jfb:<id>/<n>` from `/Items/<id>/Images/Backdrop/<n>` -> `test_the_proxy_takes_a_backdrop_index_only_on_jfb`, `test_the_proxy_reads_the_indexed_backdrop_at_tv_width_with_the_key_in_a_header`.
4. The title page and the Home hero use them -> `test_the_tv_title_page_draws_the_second_backdrop`, `test_a_title_with_one_backdrop_draws_it_and_one_with_none_draws_no_jellyfin_backdrop`, `test_the_home_hero_skips_a_jellyfin_backdrop_the_cached_read_says_is_missing`, `test_the_web_and_phone_title_hero_makes_the_same_choice`.
5. Safety -> `test_no_image_url_carries_a_key_or_token`, `test_no_socket_opens_on_a_warm_title_page_render`, `test_each_friend_sees_backdrops_from_their_own_reads_only`.
6. Captures of the Home and a title page at 1920x1080 and 960x540 dpr 2 into `C:\Users\b.edwards\Desktop\Claude\JoeyTV\review\JY-262\` (`JoeyTV\scripts\jy262_backdrop_shots.py`; the placeholder art names the backdrop index it was asked for).

## Friends
A friend's backdrops come from their own reads only: the item read is cached per viewer (`media_item._ck`), the Home hero reads that viewer's cache (`media_item.peek`), and the backdrop is media data (an image ref, a size, a blur flag). No watch state, no other viewer's read.

## Out of scope
- TMDB's second backdrop for titles that are not on the server. The cached Seerr title body carries one backdrop (`backdropPath`) and no image list; a second needs a new TMDB or Seerr read, which this item does not add. Such a title page draws the first.
- Warming backdrop 1. The warm-up keeps warming backdrop 0; the first visit to a title page fetches backdrop 1 once through the proxy, then it is on disk for 30 days.
- The 16:9 Continue watching tile still asks `h=1280` for a film's backdrop (JY-259's warmed size) on a 316 device px tile.
- `tv/`, the phone and web Home, the "Part of" banners.

## Questions for B.
1. Off-server titles (Discover, requests) draw the same TMDB backdrop on the title page as anywhere else, because the cache has only the first. Want a follow-up item that reads TMDB's image list (one cached read per title) so they get a second too?
2. Warm backdrop 1 in the nightly library pass (one extra request per title per day where it is missing), or leave it to the first visit?

## Accept checklist
- [ ] On the TCL, Home's hero shows a title's first backdrop and its title page a different (second) one.
- [ ] A title with one backdrop shows it on both; a title Jellyfin has no backdrop for shows the TMDB one.
- [ ] Captures in `JoeyTV\review\JY-262\` (1920x1080, 960x540 dpr 2): audit 0 tiny, 0 x-scroll.
- [ ] Web and phone title pages: same choice, nothing else changed.

## Follow-up: the top two ranked TMDB backdrops (2026-10-28, branch `feat/JY-262-ranked-backdrops`)

B. 2026-10-28, earlier: "when you grab the TMDB options. Could you please grab both the first and second top rated". After comparing the two options on real TMDB images (American Hostage, https://claude.ai/artifact/VQ2pLT4EYKmkLxkNRY7oBh), he chose A:

> "Background: A"

> "Use A where there are two posters."

As built:
- **Fetch (the JY-260 poster pass).** For each film and series (not seasons), `GET /Items/{id}/RemoteImages?type=Backdrop&providerName=TheMovieDb&includeAllLanguages=true` through Jellyfin (the poster request form; RemoteImages looks the item up without a user, so the read key needs no `userId`, unlike `GET /Items/{id}` in the JY-260 hotfix). At most monthly per title (`BACKDROPS_TTL_S`), inside the pass's limit, memory gate and backoff; `POSTERS_BACKDROPS=off` turns the step off.
- **Rank.** Text-less backdrops (no language; Jellyfin sends `""`) when any exist, else all; then CommunityRating, then VoteCount, then width, highest first; art only from image.tmdb.org; a URL once.
- **Store.** The top two as 1280-wide JPEGs (fetched at TMDB `w1280`, never `original`; q85) in the poster store: `<id>/<ver>.backdrop1.jpg` / `backdrop2.jpg` + the `backdrop1` / `backdrop2` pointers; `ver` hashes the source URL and the size, so a new pick is a new `&v=` URL. A slot TMDB no longer fills is cleared. They survive a poster re-render.
- **`/img`.** `jfs:<id>/<1|2>` serves the stored backdrop when `&v=` is its published version (HIT_CACHE); otherwise (no `v`, a stale one, not stored, `POSTERS=off`) Jellyfin's own backdrop 0 / 1 as before, short-cached when a `v` was given. Never warmed (local files).
- **Use.**

  | Page | Draws |
  |---|---|
  | Home hero and carousel (TV; the hero that follows focus) | stored **backdrop1** → the JY-262 chain |
  | Title page (film, series; season and episode pages use their show's pair) | stored **backdrop2** → backdrop1 → Jellyfin backdrop 1 → 0 → cached TMDB |

  The title page hero (`media_film.html`) and `_pagehead.html` carry `&v=` (Jinja `img_v`); the TV tiles already did.
- **No network on render**: the choice reads local store pointers only. Friends: joey-media mounts the store read-only, so they get the same stored backdrops for the titles they can see.
- Samples (read-only; real TMDB lists through Jellyfin, art from the TMDB CDN at w1280): `JoeyTVeview\JY-262anked\` — The Mandalorian and Grogu, Troy, Silo: `*-home.jpg` (backdrop1), `*-title.jpg` (backdrop2), `contact-sheet.jpg`, `samples.log`.
- Tests (`tests/hub/test_ranked_backdrops_jy262.py`): the ranking (text-less first, rating, votes, width, TMDB only, dedupe, language fallback), w1280, the pass storing 2 / 1 / 0 (films and series, not seasons; monthly; kept over a re-render; a failure changes nothing; the switch), which page draws which (Home 1, title page 2, one stored, none = today's chain, a season or episode page = its show's pair, `POSTERS=off`), `/img` with and without `v` and a hostile ref, the TV title page and Home hero on the friend front, and no network on render.

## Shipped notes
- Closed out with `scripts/joey.py close-out`.
- PR: #250, squash-merged as `7737283` (7737283f6494f6731d7063f3e45e9a805ca18b0a).
- Deploy: skipped: --deploy no
- Accept: in chat: "B., orchestrator session, 2026-10-28: "For the main image or background of the movie or series shown when highlighted or as a main image, etc. I would like the background to be used from TMBD. This can use the first background as the home page or carousel image, then if you go into the show. It shows the second background image or such.""
- Follow-ups: none
