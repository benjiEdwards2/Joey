# hub

The Joey web app: FastAPI + Jinja + HTMX, one container (`joey-hub`, port 8000). It is the READ side of the connector
contract (it never fetches a feed itself, with the numbered live-call exceptions in `docs/connector-contract.md`) plus
a small write side kept in one SQLite file (`media.db`: ratings, diary, watchlist, follows, awards, plays, server
history). Areas are config, not code: `config/areas.yaml` drives the top bar, hub tiles and `/a/<id>` pages. The dated
history of how each part got its shape is in `docs/hub-changelog.md`; the look is `docs/style-guide.md`.

## Module map

| Module | Owns |
|---|---|
| `main.py` | App creation, middleware, `/static` mount, router includes, Hub page (`/`), Area pages (`/a/{id}`, `/server`), `/healthz`, `/whoami`; re-exports the moved names so old `hub.main.X` paths keep working |
| `shell.py` | What every router imports instead of `hub.main`: THE one `Jinja2Templates` instance and its globals (`static_v`, `weather_place()`, `img_letters`, `identity`, `from_lan(request)`, `duration`; `shelf_max` is set by `media_home`), the registry holder (`load_areas`, `registry`), `get_snapshots` (once per request), the owner view, `build_status`, `find_detail_source`, `render_page` / `not_found_page` (the one base context and 404), `ShellMiddleware` (Cache-Control + request log), `Compress` (gzip) |
| `tasks.py` | The app lifespan (loads the registry) and the background loops, all through `_every` |
| `weather.py`, `upcoming.py` | Weather glimpse (E5: rain words `rain_words`, the 7-day row), `/weather` forecast + Windy radar embed; the Next 7 days list and hub card (E5: media releases from the arr calendar behind `show_media_releases`) |
| `today.py` | The hub's Today line (E5, 2026-10-13): one sentence after the date from the hub's own data — rain timing · today's events · new arrivals · Server state when not fine |
| `media_home.py` | Shared Media helpers: one ratings read (`_ratings`, `score_for`), `view_jelly`, Media home shelves, rating inbox and waiting counts, the Media frame (`media_nav`), the hub's Media card |
| `media_pages.py` | The `/media/*` detail pages behind registry tiles (`_detail_page`): Live, Library, Downloads, Requests, Health, To rate, Diary (+ its Month in Review card), Wrapped, Movies / TV grid, Tonight |
| `media_wrapped.py` | Month in Review + Wrapped (E6, 2026-10-13): one month's / year's summary from media.db (diary, plays, ratings, award wins) + the jellyfin snapshot's runtimes and years; the data-source rules are its docstring; kept in memory per row signature |
| `guest.py` | The guest front (Joey TV WP-B1, 2026-10-21): `front()` (`JOEY_FRONT`), the GUEST / PRIVATE / RESERVED route tables, `allows()`, the `GuestGate` middleware, the media-mode snapshot scrub, `TV_UA_TOKEN`; see "Guest front" below |
| `guest_auth.py`, `guest_signin.py` | Guest sign-in on the media front (Joey TV WP-B2, 2026-10-21): the one Jellyfin auth client (session cookie, `/Users/Me` verdict cache, P1 refusals, password failure counter) and the five sign-in / sign-out routes; see "Guest sign-in" below |
| `ids.py` | Snapshot ids, `home_tz()` / `home_now()` (Australia/Melbourne), `areas_path()` |
| `store.py` | Snapshot reader: parse once per `(mtime_ns, size)`, `connected()`, `parse_utc()`, `ago_text()` |
| `registry.py`, `identity.py` | `areas.yaml` loader (fails fast, lists every violation); who is signed in (Cloudflare Access header) |
| `access_jwt.py` | `AccessGate` (Joey TV WP-A6a): verifies Cloudflare's signed `Cf-Access-Jwt-Assertion` (RS256, team JWKS, AUD) before the email header is believed; off unless `ACCESS_JWT_VERIFY` is set (enforce live since WP-A6a, 2026-10-21); `/healthz` and loopback exempt |
| `images.py` | `GET /img/{ref}` poster proxy (async; at most 6 upstream misses at once) with a 30-day disk cache and generated fallback cards |
| `upstream.py` | One keep-alive `requests.Session` per upstream (jellyfin, seerr, arr, omdb, tmdb) for the Media modules and `/img` |
| `server.py`, `server_updates.py`, `server_stack.py`, `server_alerts.py`, `server_history.py` | Server area bands; Update now / Update all / Ignore (live What's Up Docker call); Update and restart media stack (live stackctl call); Discord push of new Attention items; 24 h health history and the disk forecast (JY-031: computed once per `_server_tick` and kept in memory, `server_history.refresh_forecast`; the hub card reads `forecast_peek`, `/server`, `/server/space` and the Discord check read `forecast`) |
| `server_digest.py` | Overnight digest (P2, 2026-10-22): one Discord message a day from `DIGEST_AT` (07:30 hub-local) built from the snapshots (arrivals last 24 h, updates pending, fullest disk, services, stalled torrents); `media.db` `server_digest_sent`; `DIGEST=off` stops it; holds after a hub start until the services report up or 15 min pass (JY-254); the Server page's "Digest · sent 07:31" line |
| `boot.py` | Boot grace (JY-254, 2026-10-26): `STARTED` (hub start = NAS boot), `BOOT_GRACE` (15 min), `settled()`; the digest and the Server push alerts hold "Down" until a fresh all-up `media_status` sample or the grace has passed |
| `media_nav.py`, `media_library.py`, `media_downloads.py`, `media_files.py`, `media_rank.py`, `media_upgrades.py`, `media_upgrade_why.py` | Media section map; library list helpers (sorts, filters, suggestions); downloads join; file-quality strip; library rank; Below cutoff (arr cutoff unmet) + last library search; Why? / Grab anyway (arr interactive search) |
| `media_film.py`, `media_item.py`, `media_person.py`, `media_omdb.py`, `media_arr_search.py` | The Cinema film page, item data (JY-104: `show_runtimes`, the progress words' hours from the cached episodes' RunTimeTicks, else recorded plays), person pages, Metacritic pill, Search now |
| `media_episode_ratings.py` | TV episode flow ratings (WP-E1, 2026-10-16): per-episode IMDb ratings via OMDb (one call per season; vote counts for the current season only), TMDB fallback from the Jellyseerr season read; media.db `episode_rating` (v5); the film page's `film.ratings`, missing reads in the response's BackgroundTask |
| `media_discover.py`, `media_follow.py`, `media_requests.py`, `media_watchlist*.py` | Discover and request, Follow, Remove request, watchlist |
| `media_db.py`, `media_write.py`, `media_plays*.py`, `media_resume.py`, `media_hidden.py` | media.db schema, rate / skip / log / search routes, play recorder and History (E5: `show_runtimes` for the progress words), resume actions, hide-until-next-sweep |
| `media_awards*.py` | Awards: sync, parsers, seeds, store, pages, badges and icons |
| `media_warmup.py`, `media_backup.py` | Film-page cache warm-up (plus the Jellyfin item reads after each new jellyfin snapshot); nightly media.db backups |
| `seed_demo.py` | Writes demo snapshots for local runs |

Templates are in `templates/` (`base.html` is the frame; `media_*.html` and `_*.html` partials), assets in `static/`
(`static/joey.js` is the frame's script: boost guard, history replace, flash strip, pinch guard). Inside Media the top bar carries the Media section row instead of the Joey pills (`_media_tabs.html` `media_bar()`, nav-tidy 2026-10-13); no JS involved.
Routers are included in `main.py`; every write route carries `Depends(same_origin)` (403 unless htmx or same Origin).

## Routes

| Route | Module | Notes |
|---|---|---|
| `GET /` | main | Hub: the Today line under the greeting (E5), summary tiles, Next 7 days, weather glimpse, Recently watched |
| `GET /a/{area_id}` | main | Area page (`layout` grid, shelves or server; grid = tiles + Next 7 days, its Media sections removed 2026-10-09, decision 2); hidden areas still serve |
| `GET /server` | main | Server area (same page as `/a/server`) |
| `GET /weather` | weather | Weather page (Windy radar embed; the parked BOM radar was removed 2026-10-09, decision 5) |
| `GET /media/diary/year/{year}`, `/media/diary/year` | media_pages | Wrapped (E6, 2026-10-13): one year in words, a summary not a ranking; the bare path redirects to this year |
| `GET /media/{movies,tv}/awards/part/rows` | awards_pages | Awards ballot's deferred rows (2026-10-14): the films view's rows after the first 7 (JY-150, was 12), one htmx request on `revealed`, same `body` / `year` / `f` / `s` query |
| `GET /media/{movies,tv}/awards/part/categories` | awards_pages | Awards categories view's deferred cards (E7): one htmx request on `revealed`, same `body` / `year` / `unseen` query; `/awards?v=categories&all=1` is the whole view (no-JS fallback) |
| `GET /media/playing`, `/history`, `/library`, `/downloads`, `/requests`, `/apps` | media_pages | Media Activity section (was "Server", renamed 2026-10-09, decision 4): Live, To rate (`/media/history`), Library, Downloads, Requests, Health |
| `GET /media/diary` | media_pages | Activity > History: the watch diary (E6: the Month in Review card leads, linking the Wrapped page) (the Diary section folded into Activity 2026-10-13; By-year rankings removed 2026-10-09, decision 1). "Show: Mine / Everyone" 2026-10-13 — only owner "you" may list everyone's rows, each then named "You" / `OWNER_NAME_HER` in its meta line; her diary is always her own |
| `GET /media/{movies,tv}`, `/tonight`, `/to-rate`, `/watchlist`, `/awards` | main, watchlist, awards_pages | Library (grid / list), To rate, Awards tabs; Tonight and Watchlist serve by URL with no tab (2026-10-13). The library page (2026-10-13): a Suggestions carousel (`?s=new\|continue\|unwatched`, cookie `media_libsugg`), then one flat sorted grid / list narrowed by filter chips (`?f=`; films All · Continue watching · Not yet watched · Watched, shows All · Watching · Not started · Caught up · Finished) and 11 sorts (12 on TV: Most to watch); Grid / List is cookie `media_libview`; no grouping |
| `GET /media/server/history` | media_plays | Play stats: plays recorded from Jellyfin sessions (no tab since 2026-10-13; linked from the diary) |
| `GET /media/discover`, `/discover/search`, `/discover/service/{provider_id}`, `/media/following` | media_discover, media_follow | Discover shelves, search box, a streaming service's shelves, Following |
| `GET /media/search` | media_write | Title search behind the Log form |
| `GET /media/title/{kind}/{tmdb_id}`, `/media/item/{jf_id}`, `/media/person/{person_id}` | media_film, media_person | Film / series page by TMDB id or Jellyfin id; person page |
| `GET /media/title/{kind}/{tmdb_id}/part/{name}`, `/media/item/{jf_id}/part/{name}` | media_film | The film page's deferred sections (`all?p=…` = every pending one, out-of-band swaps) |
| `GET /media/title/{kind}/{tmdb_id}/request`, `/arr`; `/media/title/tv/{tmdb_id}/season/{n}` | media_discover, media_arr_search | Request form, Radarr / Sonarr search form, season list |
| `POST /media/title/{kind}/{tmdb_id}/request`, `/search` | media_discover, media_arr_search | Jellyseerr request; Search now (Radarr / Sonarr command) |
| `GET/POST /media/arr/sweep` | media_arr_search | Search missing / Search upgrades across Radarr + Sonarr (GET `?step=confirm` = the inline confirm card) |
| `POST /media/title/{kind}/{tmdb_id}/upgrade` | media_arr_search, media_upgrades | Search for upgrade: the title's Radarr `MoviesSearch` / Sonarr `SeriesSearch` (the button sits in the `/arr` fragment) |
| `GET /media/title/{kind}/{tmdb_id}/quality` | media_quality | "Quality · 1080p" + Switch, lazy-loaded under the hero's status line (`?step=confirm` = the inline confirm; no-JS 303 to the page's `?quality_ask=1`) |
| `GET /media/upgrades/why/{app}/{arr_id}` | media_upgrade_why | One Downloads › Upgrades row's Why? area (`?step=confirm` = the inline ask, `result`, `grab&pick=<n>` = a release's Grab confirm, `idle`); no call. No-JS: 303 to `/media/downloads?why=<app>:<id>&why_step=…`, which draws the same |
| `POST /media/upgrades/why/{app}/{arr_id}` | media_upgrade_why | Why?: the app's interactive search (`GET /api/v3/release?movieId=` / `?episodeId=`, 90 s, threadpooled), kept 1 h per row; 404 for a row not on the snapshot's list |
| `POST /media/upgrades/why/{app}/{arr_id}/grab` | media_upgrade_why | Grab anyway: `POST /api/v3/release {guid, indexerId}` for release `pick` of the kept answer (30 s); flash `?grab=sent|gone|expired|refused|unreachable` |
| `POST /media/title/{kind}/{tmdb_id}/quality` | media_quality | Switch quality: PUT the Radarr movie / Sonarr series with the new `qualityProfileId`, then `MoviesSearch` / `SeriesSearch` |
| `POST /media/rate`, `/media/rate/{key}/delete`, `DELETE /media/rate/{key}`, `POST /media/log` | media_write | Rate, un-rate, log a watch |
| `POST /media/rate/skip`, `/media/rate/skip-show`, `/media/rate/unskip` | media_write | To rate: Skip this entry / the whole show (media.db `rating_skip`, v4), Unskip (E5, 2026-10-13) |
| `POST /media/settings/rating_level`, `/media/settings/diary_scope` | media_write | Rating scale; diary scope (2026-10-13: `mine` / `everyone`, 403 for her) |
| `POST /media/watchlist/{add,remove}` | media_watchlist | Watchlist |
| `POST /media/follow/{kind}/{tmdb_id}[/unfollow]` | media_follow | Follow a person, a film series or a show (`kind` person / collection / show) |
| `POST /media/requests/{rid}/remove` | media_requests | Remove a Jellyseerr request |
| `POST /media/resume/{jf_id}/{watched,unwatched,reset,hide}` | media_resume | Move on from Continue watching |
| `GET/POST /server/updates/{name}/run`, `POST .../ignore`, `.../unignore` | server_updates | Update now (GET = confirm page), Ignore |
| `GET/POST /server/updates/all/run` | server_updates | Update all: every eligible pending row in turn, gluetun first (GET `?step=confirm` = the list) |
| `GET/POST /server/stack/run` | server_stack | Update and restart media stack through stackctl (GET `?step=confirm` = what happens) |
| `GET/POST /server/downloads/cap` | server_quiet | P4 (2026-10-22): Downloads "Quiet (5 Mbps) · Full speed" — qBittorrent's global download cap (GET `?mode=quiet\|full` = confirm; POST → `/server?cap=…#downloads`); env `QBIT_URL`/`_USER`/`_PASS` on the hub, `QUIET_MBPS` (5), `NAS_SLEEP_WINDOW` (22:00–07:00) |
| `GET /server/space` | server_space | Free space (P1a, 2026-10-22): the 10 biggest watched films + 10 biggest finished shows on disk, by size; list only, rows link to the item page |
| `GET /img/{ref:path}` | images | Poster / backdrop / cast proxy, sizes 120 / 240 / 400 / 600 / 1280 |
| `GET /healthz`, `/whoami` | main | Health JSON (container healthcheck, `deploy.sh` smoke); the Access email or `-` |
| `/static/*` | StaticFiles | `?v=` content hash and `/static/fonts/*`: `immutable` for a year; other un-versioned files: one hour |

## Guest front (`JOEY_FRONT`, Joey TV WP-B1, 2026-10-21)

One image, two processes. `joey-hub` runs with `JOEY_FRONT` unset or `private` (today's Joey, behind Cloudflare Access).
`joey-media` runs the same `life-hub` image with `JOEY_FRONT=media`, reached at `media.joeyhome.net` through the tunnel
(`deploy/README.md`). `hub/guest.py` is the single source of truth for what the media front serves; its module docstring
is the full contract.

- **`JOEY_FRONT`** is `private` (unset or blank) or `media`. `front()` reads it on every call; any other value raises
  `ValueError`, and the lifespan calls it first, so a typo stops the container at startup.
- **Deny by default.** Media front: `/` answers 303 to the guest home (`/a/<id>` of the first `layout: shelves` area,
  resolved at runtime); an allowed route without a signed-in identity answers 303 `/signin?next=` (only `/healthz` and
  `/static` are public); everything else, unknown paths included, gets the one ordinary Joey 404 page, byte-identical for
  every denied path. The media front ignores `Cf-Access-Authenticated-User-Email`. Private front: unchanged, except that a
  request whose Host is `MEDIA_PUBLIC_HOST` (default in code `media.joeyhome.net`) gets the 404, so a tunnel typo can never
  publish private Joey ungated.
- **Every new route must be classified in `hub/guest.py`.** Each (method, path template) must sit in exactly one of
  `GUEST` (guests may use it), `PRIVATE` (B. only) or `RESERVED` (denied until a later WP moves it to GUEST; `RESERVED` is empty since WP-B4: the sign-in routes left it in
  WP-B2, `/app/*` in WP-B8, the title Request routes in WP-B4). `tests/hub/test_guest_routes.py` walks `hub.main.app.routes` and **fails the suite on an
  unclassified route, naming it**. A new route is PRIVATE until someone decides otherwise; add it to `GUEST` only on
  purpose, and never put a private page behind it.
- **`/app` (Joey TV WP-B8, 2026-10-21):** `GET /app` and `GET /app/{rest:path}` (`hub/tv_app.py`: the TV app page, `version.json`,
  `latest.apk`, the versioned APKs) are GUEST and PUBLIC (no sign-in, Q37), media front only; on the private front they are the ordinary
  404. Headers are exactly those in the `hub/tv_app.py` docstring (`no-cache` on `version.json`, `no-store` on the `latest.apk` 302,
  `immutable` on a versioned APK). Operations: `docs/tv-release.md`.
- **One scrub point.** On the media front `shell.get_snapshots` keeps only `jellyfin`, `jellyseerr` and `arr`, each cut to
  an allow-list of keys with B.'s played state and the requester's name removed from rows. A module that serves a request
  must read snapshots through `shell.get_snapshots`, never `hub.store.get_snapshots` (a test enforces it).
- **No background loops** run on the media front (`tasks.lifespan` starts none, in code).
- **Frozen interfaces** (Joey TV plan §4 rule 9; WP-B2 and WP-B7 build on them, change them only with a dated decision):
  - `hub.identity.Identity(owner, name, email=None, jf_user_id=None, jf_token=None)`. The new fields default to `None`, so
    private-front constructions are unchanged. The owner-key format is `OWNER_KEY_RE` in `hub/identity.py` (WP-A2); `guest.py`
    imports it and never redefines it.
  - `guest.TV_UA_TOKEN = "JoeyTV/"`: the TV shell's user agent carries ` JoeyTV/<semver> (<versionCode>)` and the server
    matches the substring.
- **Dev seam.** `GUEST_DEV_OWNER` signs every media-front request in as that owner, only when `HUB_DEV=1` and
  `JOEY_FRONT=media` (one startup warning). It must be a well-formed owner key, `jf:` plus 32 lowercase hex
  (`OWNER_KEY_RE`); a looser value such as `jf:devfriend` now raises in the owner helpers (WP-B2, fail-closed). Compose
  must never carry it (a test pins that).
- `GET /healthz` adds `"front"`, and on the media front `"home": "/a/<shelves id>"` (read by the TV shell's back policy).

### Guest sign-in (Joey TV WP-B2, 2026-10-21)

`hub/guest_auth.py` is the one Jellyfin auth client of `joey-media`; `hub/guest_signin.py` holds the routes and
`templates/guest_signin.html` (+ `_guest_qc*.html`) the page. Jellyfin is the session store: the access token it returns
is the session, so disabling or deleting a friend in Jellyfin, or signing the device out, ends their Joey Media session.

- **Routes** (all GUEST and PUBLIC; every one is the ordinary 404 on the private front; POSTs carry `same_origin`):
  `GET /signin` (the page: Quick Connect code, password form as the fallback), `POST /signin/qc/start` (new code),
  `GET /signin/qc/poll` (htmx, every 3 s; sets the session cookie and `HX-Redirect`s once the phone approves),
  `POST /signin/password`, `POST /signout` (Jellyfin `/Sessions/Logout`, best effort, then the cookie is cleared and
  303 `/signin`). `GET /signout` is a 404: sign-out is POST only. Nothing else under `/signin` is served.
- **Sign-out deletes the friend's device (JY-190, 2026-10-25).** `/Sessions/Logout` leaves the Jellyfin device behind,
  and a friend capped at `MaxActiveSessions 2` could then not approve the next Quick Connect code (403). After the 303,
  a BackgroundTask (`guest_auth.remove_device`) deletes this browser's device (`__Host-jm_dev`) with the admin key, only
  for a friend (`jf:<id>`, never a household user) and only when `/Devices/Info` says that friend last used it through
  Joey Media. Best effort: a failure logs `guest: device not removed (...) jf:<id>` and the sign-out stands. The
  identity read before the logout waits at most `SIGNOUT_WHO_TIMEOUT` (3 s) (`test_guest_signout_device.py`).
- **Sign-out control (2026-10-22).** On every signed-in guest page the top-bar user chip (avatar initial + name) is a
  button opening a confirm `<dialog id="signout-dlg">` (`base.html`): "Sign out" is a plain full-page form POST `/signout`
  (`hx-boost="false"`), "Stay signed in" starts focused and closes it, as do Back on the TV (tv.js `joeyTV.back()`) and Esc.
  Not on `/signin`, not for a visitor who is not signed in, never on the private front (`test_guest_signout_chip.py`).
  Look = option D + pop-up P2 (`JoeyTV\mockups\signout-options.html`): the chip is one pill with an exit icon, labelled
  "Sign out <name>" (the name ellipsises; on TV the focused pill also shows "Sign out", and the section row never shrinks);
  the pop-up says what coming back takes and its "Sign out" is orange with the exit icon.
- **Private sign-out (2026-10-22).** On joeyhome.net, with an Access identity, the same chip button + confirm dialog ends in
  Cloudflare Access logout: "Sign out" is a plain GET link to `/cdn-cgi/access/logout` (`hx-boost="false"`; Cloudflare's
  edge serves it and clears `CF_Authorization`, no app route). Local preview keeps the static chip (`test_private_signout_chip.py`).
- **Cookies** (`HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure`, `__Host-` prefix): `__Host-jm_session` (the Jellyfin token,
  90 days absolute from sign-in, never extended), `__Host-jm_qc` (the Quick Connect secret, 10 min, never in the page),
  `__Host-jm_dev` (this browser's Jellyfin DeviceId, 400 days). `JOEY_COOKIE_SECURE=0` drops `__Host-` and `Secure` for
  plain-http previews only; unset or any other value = secure. Compose must never carry it (a test pins that).
- **Re-validation.** On each guest request the token is checked against Jellyfin `GET /Users/Me`; the verdict is kept
  60 s per token (one call at a time per token, so a page's poster burst shares it). A 4xx clears the cookie and goes to
  `/signin`. Jellyfin slow or down (timeout, 5xx) is a 503 page with the cookie kept and nothing cached; a verdict that
  WAS valid is still served up to 300 s past its 60 s while Jellyfin does not answer, never a verdict Jellyfin refused.
- **P1 refusals.** A valid Jellyfin user is refused (cookie cleared; at sign-in the fresh token is logged out at once)
  when the policy is missing, disabled, an administrator, or has remote access off: `joey-media` reaches Jellyfin from
  the LAN bridge, so Jellyfin never applies the remote-access flag to it and the hub enforces it. The admin can never
  hold a guest session.
- **Password failures.** 5 per username in 15 minutes (keyed by a hash of the lower-cased username), then the next try is
  refused without calling Jellyfin, so the guest path never reaches Jellyfin's own lockout (which disables the user).
  The counter is in-process: a `joey-media` restart resets it. A wrong password, a refused user and a resting username
  all read "Wrong username or password", after a 1 s delay. An unreachable Jellyfin is not counted.
- **Owner.** `hub.identity.owner_for_jellyfin(user id)` is the one mapping (B.'s alias user is `you`, anyone else
  `jf:<32 hex>`); the household lookup failing is a 503, never a guessed owner. Logs carry `jf:<id>` or a username-hash
  prefix, never a username, password, token or Quick Connect secret.
- **Fail-closed owners.** `media_db.owner_of` / `owner_filter` pass a well-formed `jf:<32 hex>` through and raise on any
  other `jf:` value. On the media front they also raise for anything that is not `you` / `her` / a friend key, so `both`,
  `None` and unknown views never fall back to B.'s rows; the plays, home-shelf, resume, `shell.resolve_owner_view` and
  diary-scope paths follow, and the media front reads only the signed-in user's own rows. The private front keeps its
  old meanings.
- **P3 binding.** On the media front every Jellyfin read and write for a viewer (resume, item reads, the user id) uses
  the signed-in user's own id and token, never the admin key or `JELLYFIN_USER`; the item cache is per viewer there.

### Requests (Joey TV WP-B4, 2026-10-21)

Friends request through Discover and every friend request waits for B.'s approval in Seerr (DECISIONS B #19).
`hub/media_guest_requests.py` holds the Seerr side; the one request POST stays `media_discover._send`.

- **Route.** `GET` + `POST /media/title/{kind}/{tmdb_id}/request` moved from RESERVED to GUEST (`RESERVED` is now empty).
  Requests, Remove request, Follow, Search now and Quality stay PRIVATE on the media front (Q19).
- **As the friend.** A `jf:` owner's request carries the admin `X-Api-Key` plus `X-Api-User: <their Seerr id>`, so Seerr
  creates it as them, pending. The id comes from `GET /api/v1/user?take=500` by `jellyfinUserId` (dash-less, lower case),
  cached 1 h. No Seerr user yet: one `POST /api/v1/user/import-from-jellyfin` for that friend only, on their first
  request (never on a page view), then one re-lookup; still none = "Requests aren't set up for you yet". A failed lookup
  sends nothing: never the bare key for a friend.
- **Pending only.** A friend whose Seerr user has ADMIN, MANAGE_REQUESTS or any AUTO_APPROVE bit is refused before sending
  (fix it in Seerr → Users → Permissions). On the media front no quality profile is sent or enforced and Sonarr never
  follows an "All seasons" request. B.'s own request (private front, or the household alias on the media front) is
  unchanged: admin key only.
- **Status, not controls.** Nothing on the media front approves, declines or removes. A friend sees their own requests
  (`GET /api/v1/request?requestedBy=<id>`, cached 60 s) as Requested / Approved / Declined on the title page and as
  Discover chips.
- **Discover screen** (WP-M screen 10): `media_discover_guest.html` + `_guest_discover_grid.html`: a search box and one
  poster grid (trending, popular films, popular TV, de-duplicated, max 36) with In library / Requested / Request /
  Declined chips. A poster opens `_guest_request_panel.html` (`?panel=1`) in a `<dialog>`; Request answers "Requested —
  waiting for approval" and updates the chip (`hx-swap-oob`). Done, Esc or the TV's Back close it and focus returns to
  the poster (`tv.js` `joeyTV.back()` honours the dialog's `_opener`). The answer panel keeps the poster, title and
  overview (`_request_title` reads the title before dropping its cache). In TV mode `tv.css` styles all of it to screen 10:
  the grid takes the six-column helper (`.poster-grid.reqgrid`), the one-tab sub-tab row is dropped, chips are In library
  teal / Requested amber / Request indigo (Declined grey), the panel is a 780 px card (150 px poster, 38 px title, 3-line
  synopsis, amber 22 px status line, Request then Done focused). Those rules live only in `tv.css` (`html.tv` scope, no
  `:hover`); the page's inline `<style>` carries none.

### Guest surface and TV mode (Joey TV WP-B3, 2026-10-21)

What a signed-in friend sees on the media front, and the 10-foot TV skin the Android TV shell loads.

- **Identity on the 404 and a friend's own Diary (JY-190, 2026-10-25).** The media-front 404 resolves the session first, so
  its user chip names the signed-in friend or household user (no session: not signed in; still one page for every denied
  or unknown path per visitor). The Diary's month card and Wrapped's summary read only the friend's own `jf:<id>` rows,
  and a friend's shows carry no progress words (those come from the household's Jellyfin lists), so a friend never sees
  a household number (`test_guest_surface.py`, `test_guest_month_card.py`).

- **The pages.** Home (`/a/<shelves id>`, JY-195): Continue watching and Recently watched (live reads of the
  viewer's own Jellyfin state with their own token, `hub/media_guest_home.py`), Recently added, and New on Joey this month /
  Top rated on Joey / Films under 100 minutes (the scrubbed snapshot only); an empty shelf is left out, a brand-new friend
  gets a welcome line; no hero, no household shelves. TV empty states: `_empty_state.html`. The section row is Movies, TV shows, Diary, Discover; the "Joey Media" title is the way Home (JY-248). Title pages draw no off-site links (the
  exposure crawl allows only the Jellyfin edge, YouTube and TMDB images).
- **The `shell.jellyfin_link` seam.** `hub/shell.py` `jellyfin_link(registry_href)` is the one base of every Jellyfin link a page
  draws (Play, "Open in Jellyfin", the `_deep_link` item links). On the media front it is `JELLYFIN_PUBLIC_URL` with its port kept
  verbatim (`:8443`: the TV shell's UrlPolicy matches scheme + host + port) and `None` when unset (no link rather than a LAN one);
  on the private front it is the registry href. Never build a Jellyfin link any other way.
- **The one-time "Set up Jellyfin" card (Q39).** Shown on the Overview until `?setup=done` (cookie `jm_setup`, one year); it
  carries `JELLYFIN_PUBLIC_URL` and `templates/area_shelves.html` wraps its `:port` in `<em>` (the whole address is also in the
  `aria-label`). In TV mode it is a full-screen card and `tv.js` keeps the D-pad on it while it is up.
- **The friend diary.** The play recorder (`hub/media_plays.py` `friend_diary`) writes one diary row, owned by `jf:<id>`, when a
  friend's play reaches `FINISHED_PCT` (90 %, `hub/media_plays_db.py`); one row per title per day, so later polls add nothing. B.'s
  and her diary still come from the Jellyfin history sweep.
- **TV mode** (`hub.media_front.tv_mode(request)`, Jinja global `tv_mode`; media front only, the private front ignores it). On when
  the user agent contains `guest.TV_UA_TOKEN` (`JoeyTV/`, the shell's ` JoeyTV/<semver> (<versionCode>)`) or the `tv=1` cookie is
  set; `?tv=1` sets that cookie (one year, `SameSite=Lax`) and `?tv=0` clears it, handled in `GuestGate` so it works on every
  media-front page, the 404 and `/signin`. `<html>` then carries class `tv` and the page links `/static/tv.css` and
  `/static/tv.js` (vendored, no external asset); neither is linked, and the private CSS bytes are unchanged, without it.
  - `tv.css` is the signed-off WP-M mockup (`JoeyTV/mockups/tv-mode.html`): 960 x 540 CSS px design viewport (1920 x 1080 at
    320 dpi), 21 px base type, 16 px floor, 48 / 27 px overscan margins, a 4 px white focus ring with 1.06 poster scale, **no
    `:hover` rule at all** (a test pins it), no phone tab bar. Per screen: Overview has no head band; Movies / TV shows are a
    sticky section row + sub-tabs over a six-column grid (no search / sort toolbar, no "New this week", no freshness lines); the
    title page is a 170 px poster beside title, facts, a three-line synopsis, Play / Trailer / Watchlist and the 1-10 rating chips
    (templates carry the extra lines only when `tv_mode(request)`, `media_film.html`). Every off-origin link except YouTube trailers
    and the Jellyfin hand-off (`/web/#/details?id=`) is hidden (Q41).
  - `tv.js` owns what a Chromium WebView lacks: geometric D-pad focus, first focus (`[data-first]`, else Play, else the first
    poster), clamped shelf centring, scroll-into-view under the sticky bars, focus restore after an htmx swap.
  - **`window.joeyTV.back()`** is the contract with the shell's BackPolicy (WP-B7): it closes an open `<dialog>` (the trailer
    modal) and returns `true`; with nothing to close it returns `false` and the shell goes back or exits. `joeyTV.focusFirst()`
    re-runs first focus.
  - A trailer on the TV is a plain navigation to its YouTube URL (the shell hands it to the YouTube app), not the in-page player.
  - **TV UI round (2026-10-25, JY-187 to JY-196, JY-248; hub only, no `tv/` change).** Where this section's older lines above differ
    (six-column grid, rating chips, an Overview pill), the lines below are current. Specs: `docs/specs/JY-187-*` to `JY-196-*`, `JY-248-*`.
    - **Back memory (JY-187).** `tv.js` keeps the last focused `<main>` link and scroll per URL in `sessionStorage` (`joeyTV.back`, at most 40
      URLs; never a top-bar or dialog focus) and restores them on Back, a boosted swap, `pageshow` and the shell's hand-off reopen. Up from
      the page lands on the open section's pill (`.toplinks a[aria-current]`). With no Play or poster, first focus is the current sub-tab.
      Down from the title buttons lands on the first rating control.
    - **Density B and compact chrome (JY-188).** Cards are 104 x 156 css px, eight across; the top bar is 64 px and the sub-tab row 40 px; only
      the focused card shows its meta line. Type floor 18 px. The title-page hero has a scrim, the 404 is a centred "No page here" with Back,
      and the sign-in password field no longer sits below the fold. Focus scale stays 1.06.
    - **Posters (JY-189).** TV mode fetches posters at `h=600` (the warm `POSTER_H` cache) on shelves, grids and Tonight. Tonight is a
      three-card `.poster-grid.big` inside the safe area with "Deal again" reachable.
    - **Server fixes (JY-190).** `POST /signout` for a friend revokes the token, then deletes that friend's own Jellyfin device after the
      response (never a household or other-app device), so the two-device cap no longer blocks the next Quick Connect. The 404 shows the signed-in
      identity. The Diary month card and Wrapped read only the friend's own rows.
    - **Series and episodes (JY-192).** Series, season and episode pages show a Seasons shelf and an Episodes shelf (16:9 stills through `/img/jf:<id>`,
      watched and progress words from the viewer's own state). OK on an aired episode hands it to Jellyfin. The episode page leads with the
      episode. Back on a season or episode goes to the series. Rating is a **Rate** button ("Rated 8") that opens the picker in a strip under the
      buttons; Back closes the strip.
    - **Title shelves and request page (JY-193).** One "More on Joey" shelf, on-server titles only. A title not on Joey is a request page with
      Request focused first (confirm, then "Requested", Back focused). The person page is a TV layout with an on-server shelf.
    - **Discover search (JY-194).** The friends' Discover shows a 56 px search field above the grid. Up from the first row reaches it, OK
      raises the keyboard, typing swaps in "Results · n", and Back returns to trending with the field focused.
    - **Home (JY-195, every device).** Continue watching, Recently added, New on Joey this month, Top rated on Joey, Films under 100 minutes,
      then Recently watched; empty shelves are left out, a brand-new friend gets a welcome line, an empty library gets one words-first state.
      TV empty states use `_empty_state.html` (no grey box).
    - **Awards and Diary (JY-196).** Awards on the TV are a ceremony chip row, the edition line and one poster shelf per category group (no
      picker or `<select>`). The Diary is a slim month row, All / Films / TV chips and month-grouped rows; "Log a watch", stats, milestones
      and the Mine / Everyone form are hidden. An unrated row says "OK to rate" and opens the strip. To rate drops the "Rate TV by" chips.
    - **Nav (JY-248).** The section row is Movies, TV shows, Diary, Discover: no Overview pill. The "Joey Media" title is the way Home and a TV focus
      stop (current on Home). Up from Home reaches it; Home to the sign-out pill is 6 presses.
    - **Device checks** for all of the above run together in one grouped TV session, not yet run (2026-10-25). Shell 1.0.2 (JY-191, PR #151) is
      held; see `docs/tv-release.md`.

## Environment (all read by the hub; secrets live in the NAS `deploy/.env`, see `deploy/.env.example`)

| Variable | Default | Does |
|---|---|---|
| `SNAPSHOT_DIR` | `/data/snapshots` | Where connector envelopes are read |
| `MEDIA_DB_PATH` / `MEDIA_BACKUP_DIR` | `/data/sqlite/media.db` / `/data/backups/media` | media.db and its gzip backups |
| `IMG_CACHE_DIR` / `META_CACHE_DIR` | `/data/cache/img` / `<IMG_CACHE_DIR>/meta` | Poster cache; 6 h Jellyseerr / title meta cache |
| `AREAS_PATH` | `config/areas.yaml` | Registry file |
| `OWNER_EMAIL_YOU`, `OWNER_NAME_YOU`, `OWNER_NAME_HER` | unset, Benji, Georgina | Access email that is "you" (any other is "her"); chip and greeting names |
| `ACCESS_JWT_VERIFY`, `ACCESS_AUD`, `ACCESS_TEAM` | off, unset, `joeyhomeed` | Access JWT gate: `audit` logs verdicts only, `1` refuses a missing/forged token (401; 503 if the team's keys cannot be read); `ACCESS_AUD` = comma-separated AUD tags, required once the flag is set (the hub will not start without it); find it under Zero Trust, Access controls, Applications, the app, **Additional settings** tab. JWT verification live since WP-A6a (2026-10-21); residual = replay of a captured token within its lifetime, and hub-container compromise |
| `WEATHER_LAT`, `WEATHER_LON`, `WEATHER_PLACE` | Windy radar falls back to Newport, `Newport VIC` | Windy radar centre (the weather connector reads the same pair) and the place name in weather labels |
| `JOEY_FRONT`, `MEDIA_PUBLIC_HOST` | unset (= `private`), `media.joeyhome.net` | `media` makes this process the guest front ("Guest front" above; set only on `joey-media`); any other value stops startup. `MEDIA_PUBLIC_HOST` = the Host the private front answers with 404 |
| `JOEY_COOKIE_SECURE`, `GUEST_DEV_OWNER` | `1`, unset | Guest sign-in ("Guest sign-in" above). `JOEY_COOKIE_SECURE=0` = plain cookie names without `Secure`, for http previews only; `GUEST_DEV_OWNER` = a `jf:<32 hex>` dev identity, honoured only with `HUB_DEV=1` on the media front. Neither belongs in compose or `media.env` |
| `HUB_DEV` | off | `1` re-reads templates on every render (local template editing) |
| `JELLYFIN_URL`, `_API_KEY`, `_USER`, `JELLYFIN_USER_HER`, `JELLYFIN_USER_ALIASES` | unset | Live item reads, play recorder, her profile; aliases = B.'s extra Jellyfin user names (comma-separated), recorded as "you" |
| `JELLYSEERR_*`, `RADARR_*`, `SONARR_*` (`_URL`, `_API_KEY`), `OMDB_API_KEY` | unset | Requests, Search now, Request remove; Metacritic pill (7-day cache, 800 calls a day) |
| `WUD_URL`, `WUD_USER`, `WUD_PASS`, `SERVER_DISCORD_WEBHOOK` | unset | Update now / Ignore; Attention push |
| `STACKCTL_URL`, `STACKCTL_TOKEN` | unset | Update and restart media stack and its status line (`stackctl/NAS_INSTALL.md`); unset = button hidden, "Not connected" |
| `MEDIA_BACKUP`, `PLAY_RECORDER`, `MEDIA_WARMUP`, `MEDIA_FOLLOW`, `MEDIA_AWARDS` | on | `off` stops that background job (`MEDIA_WARMUP=shelves` keeps only the shelf pass) |
| `PLAY_POLL_SECONDS`, `AWARDS_CONTACT` | 60, unset | Recorder poll; awards sync makes no call without a contact |

## Background loops (started in `tasks.lifespan` through `_every(label, first_s, every_s, fn)`; errors log by type only)

| Loop | First run | Every |
|---|---|---|
| media.db backup (`media_backup`) | 30 s | 1 h (skips while a backup under 20 h old exists) |
| Play recorder (`media_plays`) | 15 s | `PLAY_POLL_SECONDS` |
| Server alerts + history sample + disk forecast (`_server_tick`) | 60 s | 5 min |
| Film warm-up (`media_warmup.tick`) | 60 s | ticks every 60 s: the full pass every 3 h (full-library pass at most once per 24 h); the item pass on each new jellyfin snapshot |
| Follow (`media_follow`) | 2 min | 6 h |
| Awards (`media_awards`) | 3 min | hourly check, a pass only when one is due |

`scripts/awards_sync.py` is the manual CLI for the same awards code path (it calls `media_awards._insert_new` directly).
The connectors run in their own container: Media / Server feeds every 2 min, everything else hourly (`deploy/docker-compose.yml`).

## Caches

Snapshots: parsed once per `(mtime_ns, size)`, read once per request (`request.state.snaps`), and once at startup
(`tasks.prewarm`, with every template compiled). Hub Server card: 60 s. Runner history tail: kept in memory per file
identity + size + mtime, extended by appended bytes only (`store.get_runner_history`; shared by the card and `/server`).
stackctl status: 30 s (good or unreachable). Discover lists: 10 min fresh, the last good rows kept on disk and served
with their age when a refresh fails, a failed read remembered 60 s; Jellyseerr meta (bodies, ratings, season lists): 6 h
in memory and on disk; providers 24 h (last list kept on failure). Jellyfin item data: 10 min fresh, served up to 6 h
old while a background re-read runs (`media_item`; Joey's watch marks drop it). Search now lookups: 5 min (dropped by
Joey's *arr / Seerr writes). Diary: history sync once per jellyfin snapshot, stats per diary change; Month in Review / Wrapped per media.db row signature (at most 32). media.db: one kept
reader connection per thread (`media_store.reader`). Posters: 30 days on disk. HTML pages are `no-store` so Back and
Forward never show a stale page.

**Film pages render first, upstream sections after (F2, 2026-10-12).** `media_film.build_film(..., defer=True)` (the
routes) never waits on Jellyseerr or OMDb: it renders from Jellyfin + the caches (`peek_extras`), and each section whose
answer is not cached is in `film.pending` — drawn by `_film_wait.html` as a `<div class="fpart" id="fp-<name>">`
(display: contents) holding the Jellyfin fallback or "Loading". ONE element (`.fpart-load`, `hx-trigger="load"`,
`hx-swap="none"`) asks `GET /media/{item/{jf_id}|title/{kind}/{tmdb}}/part/all?p=<names>`; `build_parts` answers with
each part wrapped in its placeholder's id and `hx-swap-oob="true"`. Parts are `media_film.PARTS` (makers, actions,
scores, collection, crew, dates, cast, providers, shelves), each one template `_film_<name>.html` that the page includes
inline when cached; `/part/<name>` serves one. The actions part has two slots (E4, 2026-10-13): `fp-actions` in the
hero's action row and `fp-actions-more` under its More fold (Request beside Play), each part answer filling both. The upstream read runs in a bounded background pool (`warm_extras`, one
job per title, started as soon as the TMDB id is known); part requests wait for it (`EXTRAS_WAIT`) and never read
Jellyfin (`media_item.peek`). Scripts and tests calling `build_film` without `defer` get the whole page, waiting as
before. **Prefetch:** `static/joey.js` sends `X-Joey-Prefetch: 1` to a film / show link on touch or a 60 ms hover (once
per link, one at a time); the route runs the reads and answers 204 with no body, no cookie and a log line without the
path. A prefetch's background read runs in its own 1-worker lane (at most one more waits there, later ones are skipped),
and a tap on a title whose prefetch has not started takes it over in the page lane (E1, 2026-10-13).

**Resilience + per-request costs (E1, 2026-10-13).** Discover never blocks: shelf and provider-list reads wait 3 s, a
failed refresh serves the last good rows with their age in the shelf heading ("Trending · 12m ago"), a failure is
remembered 60 s, nothing stored = "Discover unavailable" at once. `/img` is async: hits never wait, misses take one of 6
upstream slots without holding a thread and fall back to the card (1 h cache) after 8 s without a slot; a `jfb:`
backdrop's width follows `h` (h=600 -> 800 wide). Series pages read one `/Shows/{id}/Episodes` for every season. The
Server page reads stackctl at most every 30 s and reuses the card's parsed sweep history. Details and measured numbers:
`docs/hub-changelog.md` (2026-10-13).

## Decisions pinned by tests

**Play owners (Joey TV WP-A2, 2026-10-18):** plays keyed jf:<id> for non-household Jellyfin users — the recorder names
a play's owner by Jellyfin user ID (`identity.owner_for_jellyfin`, names resolved once via `/Users`; `JELLYFIN_USER`
unset = nobody is "you"), the frozen format is `identity.OWNER_KEY_RE` (`jf:<32 lowercase hex>`), and every private
read (`you` / `her` / `both`) skips `jf:` rows (`media_db.household_sql`).

**Awards ballot (Plan C, 2026-10-14; review/2026-10-13-awards-ux/BALLOT_DECISIONS.md):** Movies / TV shows › Awards
(`media_awards_pages.py`, `media_awards.html`, `_award_body.html`, `_award_ballot.html`, `_award_sheet.html`) is a ballot:
one row per nominated film or show, the default **Films** view; the category cards are the second view (`?v=categories`,
E7's lazy tail kept). A sticky control row holds the picker (`<details class="awpick">`: ceremony tiles + year chips with
"‹ 2024" / "2026 ›" and Latest; a bottom sheet on a phone, a dropdown from 640 px; a choice, Done or the scrim re-renders
the block closed), the edition line and Films · Categories; "Next up" folds the dates grid. The films view: a progress
ring ("Seen 5 of 35 nominated films", the headline category, on your server and unseen, on your watchlist), then filter
chips (All · the headline category · Acting · Direction & writing · Craft · Not seen · On your server) and sort chips
(Most wins · Most nominations · A to Z), all URL state (`f`, `s`; the old `unseen=1` = `f=unseen`) swapped into `#awmain`
by htmx with the URL pushed and the scroll kept; Not seen says "Hiding N seen". A row: poster (gold frame + winner badge),
title + year (the server's, else the edition's "films of" year), "5 wins · 6 nominations", up to five pills (won first;
acting / directing pills name the person), the action (emerald "Seen ✓", or the worded Watchlist button — the same
`/media/watchlist/add|remove`, `style=ballot`, swapped in place) and a Details fold with every category and its people.
The first 7 rows render (JY-150: was 12, so the phone page stays under 2,500 px); the rest come through `/awards/part/rows`. Short-film categories fold under "Shorts · N" (out of
the rows, filters and progress); acting / directing winners close the page as a people strip. Nothing calls the award
hosts from a page; posters fill after the response (F2), the first rows first.

**No zoom (media-ux5, B.'s explicit choice 2026-10-09):** Joey cannot be pinch- or focus-zoomed on a phone (viewport
`maximum-scale=1`, 16 px inputs, Safari gesture events cancelled in `static/joey.js`). The accessibility trade-off (WCAG 1.4.4)
is accepted for this private two-person app; undo by restoring the old viewport meta and removing the gesture guard.

**Follow shows + show creators (F5, 2026-10-12):** `media_follow.py`. A show page (not an episode) carries one line under
the hero's makers (`_follow_show.html` via the `follow_show(request, film)` global — a media.db read, no upstream call):
"Follow show" keeps it monitored in Sonarr with every new season (`monitored: true, monitorNewItems: "all"`; requested
"All seasons + future" through Jellyseerr first when Sonarr lacks it), Unfollow sets `monitorNewItems: "none"` and never
deletes. A show's "Created by" cards get a small "Follow <name>" button each (`_film_makers.html`, via the `followed(kind)`
global); that, or Follow on the person page of someone with TV Creator / Director credits, follows them as a TV maker
(dept `creator`), so the 6-hourly check requests their new shows too. Following lists shows in their own group with
Unfollow. media.db `user_version` 3 (`migrate_shows`). Calls: the twelfth exception in `docs/connector-contract.md`.

**Search now (media-ux5, 2026-10-09):** `media_arr_search.py` sends a Radarr `MoviesSearch` / Sonarr `SeriesSearch` for
monitored items only, plus the "All seasons + future" request option; full behaviour in `docs/hub-changelog.md` and the
seventeenth exception in `docs/connector-contract.md`.

**Search all monitored (F3, 2026-10-12):** Activity › Requests and › Downloads open with one row (`_arr_sweep.html`, via
the `arr_sweep(request)` global): "Search missing" and "Search upgrades", each an inline confirm (htmx
`GET /media/arr/sweep?step=confirm`; without JS the page draws it from `?sweep_ask=`) then a `same_origin` POST that
sends Radarr `MissingMoviesSearch` + Sonarr `MissingEpisodeSearch`, or `CutoffUnmetMoviesSearch` +
`CutoffUnmetEpisodeSearch` — one worker thread and a 10 s timeout per app, so one app down never stops the other
(`?sweep=started|partial|failed`). A second sweep of the same kind inside 10 min is allowed; the card says "Started 4m
ago · run again?" (in-process timestamp). Neither app configured: "Not connected", no buttons.

**Upgrade available (F4b, 2026-10-12):** `media_upgrades.py` reads the `arr` snapshot's `data.upgrades` (Radarr / Sonarr
cutoff unmet) — no call. A small light-blue line (`.upnote`, token `--upgrade`; macro `_upgrade_note.html`) says
"Upgrade available · WEBDL-720p → Bluray-1080p" ("· 3 episodes ·" for a show; no arrow when the cutoff is unknown) under
Movies / TV rows and cards, Requests rows and the film / show hero's status line (inline in the core, never an episode
page); Activity › Downloads gains an "Upgrades" block ("3 films · 2 shows", each title linked; "Not connected" when both
lists are null, absent for an older envelope). Films match on `tmdb:`; Sonarr rows are `tvdb:`, so a show matches its
own `tvdb:` key, else a known TheTVDB id (the Jellyfin item's ProviderIds.Tvdb — cached by its page, `media_item.peek` —
or a request's `tvdb_id`), else its normalised title when unique on both sides. "Search for upgrade" joins the lazy
Search-now fragment when the app's own id is on the list: an inline confirm, then `POST …/upgrade` (`same_origin`,
threadpooled) sends `MoviesSearch` / `SeriesSearch`; `?upgrade=started|failed` flashes "Upgrade search started" /
"Couldn't start the search". The app grabs the best release its profile allows; picking a release is not offered (v2).
**Below cutoff + Why? (WP-U1, 2026-10-21):** the label is now "Below cutoff · HDTV-1080p → wants WEB/Bluray 1080p" — the
file is below the profile's cutoff, which does not mean a better release exists (the connector names a cutoff GROUP by
its members, never its own name such as "Default"). Activity › Downloads adds, under the Search buttons, one line per app
from `upgrades.last_search` ("Last upgrade search · Sonarr · 21 Oct 00:59 · 1 searched · 0 downloaded", the amber words
when nothing was downloaded or the search failed). Each Upgrades row is now `.row.has-form` with a "Why?" beside it
(`media_upgrade_why.py`, `_upgrade_why.html`): an inline ask, then the app's interactive search (Radarr `?movieId=`, Sonarr
`?episodeId=` of the row's `sample` episode; 90 s, kept 1 h) drawn as "S01E01 · 30 releases · all rejected", the
reasons grouped ("30 × custom-format score below the profile minimum (1000)", "7 × quality not wanted in profile", …), a
hint when nothing is accepted and the custom-format minimum is a reason on the best rejected release or on at least half
of them ("rejects N of M releases for this title", "every release" only when N = M; JY-108), and the top 5 releases (quality · size · seeders · indexer ·
group, then the first rejection), each with "Grab anyway" — its own inline confirm, then `POST /api/v3/release` with the
guid / indexer id from the kept answer. Page renders make no arr call; logs carry the app and a status / type only.

## Run locally

```
python -m hub.seed_demo
set SNAPSHOT_DIR=data/demo-snapshots && python -m uvicorn hub.main:app --port 8800
```

Local-only: with no Access header, `?owner_view=you|her|both` picks the owner view. Tests: `python -m pytest -q tests/`
from the repo root (see `tests/README.md`). Deploy: `deploy/README.md`.
