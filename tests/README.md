# tests/ — the cumulative suite

The growth law, verbatim from MASTER_PLAN "Testing & release gates" (binding, §2 rule 13):

> **Growth law (append-only):** a WP that changes code lands its tests in the same session.
> A bugfix session writes the failing regression test FIRST, then fixes until green — the test
> stays forever. A test is never deleted, weakened, or skipped without a dated DECISIONS.md
> line saying why.

Runner, dev machine (fixture-mode, no credentials, no network — must pass anywhere; test-only deps in `requirements-dev.txt`):

    python -m pytest -q tests/

On the box `deploy/deploy.sh` builds the union `life-test` image (`deploy/test.Dockerfile`: hub + connectors + test deps)
and runs the same suite offline (`--network none`) against the code that ships, then smoke-tests the live stack
(`tests/deploy/smoke.py`). It is the only path to production and aborts on any failure.

| Dir | Owns |
|---|---|
| `tests/hub/` | The hub: shell, registry, identity, store, every Media / Server / Weather / Awards page and its routes |
| `tests/connectors/` | Envelope and per-feed schemas, fixture tests per connector, the sample snapshots, the contract doc |
| `tests/deploy/` | `smoke.py` plus compose, `.dockerignore`, deploy-script, cloudflared, public-edge (`test_edge.py`) and off-box media.db push (`test_media_offsite.py`) checks |
| `tests/money/` | The money pre-commit guard only (the money importer was never built) |
| `tests/stackctl/` | The `stackctl/` media-stack helper: Bearer auth, service filter, one-job rule, HTTP layer (docker faked) |

`tests/deploy/test_edge.py` (Joey TV WP-A3, 2026-10-18; host network mode since WP-A4, 2026-10-19) pins the public edge offline: swag in
`network_mode: host` with no `ports`/`networks` and no service publishing a port, no port 80, one `server_name` and one upstream
(`127.0.0.1:8096`, the only IPv4 literal allowed), AU + NZ geo with our own `$joey_country` plus 192.168/16, 10/8 and 127.0.0.1 (no
172.16/12), the 444 catch-all, the `jellyfin-auth` fail2ban jail (5/600/3600, regex fixtures, stock `nginx-unauthorized` off, `ignoreip`
= the geo gate's local set), php-fpm's `[www]` pool on a unix socket via the `:ro` `www2.conf` bind (WP-A5: off Portainer's
127.0.0.1:9000 in host mode), `edge.env` ignored by git and docker, and no Cloudflare token value anywhere in `deploy/`.
`test_deploy_script` gained the edge smoke checks (and pins that the gate no longer checks `joey-edge`); `test_compose_limits` gained
swag 192m and ddns 32m. `tests/connectors/test_container.py`'s exact services set gains `swag` and `ddns`. The top-level networks pins in
`tests/deploy/test_cloudflared.py` (`{"media"}`) and `test_container.py` (`media` only) are back to their original exact form: WP-A3
extended them for `joey-edge`, which host mode no longer declares. `nginx -t`, certbot and `fail2ban-regex` run only live (WP-A4).

The guest front (Joey TV WP-B1, 2026-10-21) is pinned offline by:

- `tests/hub/test_guest_routes.py`: `allows()` unit cases, the `JOEY_FRONT` values, and the **route-classification gate** (every
  route of `hub.main.app` in exactly one of GUEST / PRIVATE / RESERVED, a throwaway extra route reported by name), plus the frozen
  `Identity` fields and `TV_UA_TOKEN`, and that `guest.py` imports `OWNER_KEY_RE` rather than redefining it.
- `tests/hub/test_guest_surface.py`: with `JOEY_FRONT=media`, private paths answer the same 404 body as an unknown path, `/` and
  the guest home 303, a forged Access header does not sign anyone in, `/healthz` front and home, the private-front Host guard
  (`MEDIA_PUBLIC_HOST`), and middleware order in the request log.
- `tests/hub/test_guest_snapshots.py`: the media-mode scrub allow-lists, and the AST check that only the named modules import
  `get_snapshots` from `hub.store`.
- `tests/hub/test_guest_lifespan.py`: on the media front the six loop starters are never called.
- `tests/deploy/test_joey_media_service.py`: the `joey-media` compose service (profile, image, `depends_on`, the five loop offs,
  `:ro` snapshots, no ports, networks, `media.env`) and that `media.env.example` and compose carry no forbidden key.
- `tests/deploy/test_route_sweep.py`: `route_sweep.py` plans every PRIVATE pair with its own verb (the sweep itself runs live, WP-B5).

`tests/hub/` by theme (file prefixes):`tests/hub/` by theme (file prefixes):

- **Shell and look:** `test_hub_shell`, `test_hub_core`, `test_shell`, `test_hub_page`, `test_area_pages` (top bar, tab bar, hub tiles, area pages; formerly `test_apex_*` — the Apex rail and theme-toggle tests are historical, rewritten for the MediaHub shell), `test_style_*`, `test_styling`, `test_pwa`, `test_hidden_areas`, `test_history_*`, `test_routes`.
- **Registry, identity, owners:** `test_registry`, `test_identity`, `test_owner_filter`, `test_store`, `test_tiles`, `test_images`.
- **Hub, Next 7 days, weather:** `test_upcoming` (hub/upcoming.py), `test_weather*`, `test_hub_hero`.
- **Server area:** `test_server*` (bands, cards, counts, history, alerts, Update now / Update all / Ignore, Restart + update media stack, not-configured states).
- **Media app:** `test_media*` — feature-named files, not build-round names: shelves (`test_media_shelves`), library and list pages (`test_media_library_pages`, `test_media_list_posters`, `test_media_to_rate_pages`), nav and phone fit (`test_media_nav`, `test_media_phone_nav`, `test_media_frame`), film / item / person pages (`test_media_film`, `test_media_film_scores`, `test_film_page_e4` (hero order + action row), `test_media_item`, `test_media_person`), episodes (`test_media_episodes`, `test_media_episode_watch_state`), Discover (`test_media_discover`, `test_media_discover_search_now`), Follow, requests, watchlist, rate and diary, Month in Review and Wrapped (`test_month_in_review`, `test_wrapped`; E6), show progress words (`test_show_progress_words`, `test_show_hero_progress`), play recorder, backup, warm-up; plus `test_film_quality`.
- **Awards:** `test_awards_*` (recorded Wikidata / Wikipedia answers in `tests/hub/fixtures/awards/`, stored gzipped; parsers, store, sync, pages, UI; the ballot (2026-10-14): `test_awards_ballot.py` context + routes, `test_awards_ballot_templates.py` templates).

Shared fixtures live in `tests/hub/conftest.py`; shared builders, fakes and sample data (`write_envelope`, `make_area` / `make_tile` / `write_registry`, `shelf_area`, the Jellyfin / Jellyseerr fakes and `ITEMS` / `FILM` samples, `FakeResponse`, the film `env` fixture, E6's media.db builders `diary` / `play` / `eps` / `seed_year` and the Diary `wrap` fixture) live in `tests/hub/helpers.py` — import from there, not from another `test_*` module (`tests/connectors/helpers.py` holds the Radarr/Sonarr ones). `tests/conftest.py` makes the repo importable and has an autouse fixture
that points `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR`, `SNAPSHOT_DIR` and `META_CACHE_DIR` at per-test temp paths, sets
`PLAY_RECORDER`, `MEDIA_BACKUP`, `MEDIA_WARMUP` and `MEDIA_AWARDS` to `off`, and unsets `OMDB_API_KEY` and
`AWARDS_CONTACT`; without it the default `/data/...` resolves to `C:\data\...` on Windows and tests touch a real directory.
It also calls `hub.media_store.reset()` before and after each test (E1, 2026-10-13: media.db readers are one kept
connection per thread). `tests/hub/conftest.py` routes `hub.upstream.session(...)` back through the `requests` module
(E1: the Media modules call one keep-alive Session per upstream), so a fake at `requests.get` / `post` / `put` /
`delete` still sees every outbound call; tests of the Sessions themselves restore the real one.
