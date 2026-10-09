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
| `tests/deploy/` | `smoke.py` plus compose, `.dockerignore`, deploy-script and cloudflared checks |
| `tests/money/` | The money pre-commit guard only (the money importer was never built) |

`tests/hub/` by theme (file prefixes):

- **Shell and look:** `test_hub_shell`, `test_hub_core`, `test_shell`, `test_hub_page`, `test_area_pages` (top bar, tab bar, hub tiles, area pages; formerly `test_apex_*` — the Apex rail and theme-toggle tests are historical, rewritten for the MediaHub shell), `test_style_*`, `test_styling`, `test_pwa`, `test_hidden_areas`, `test_history_*`, `test_routes`.
- **Registry, identity, owners:** `test_registry`, `test_identity`, `test_owner_filter`, `test_store`, `test_tiles`, `test_images`.
- **Hub, Next 7 days, weather:** `test_upcoming` (hub/upcoming.py), `test_weather*`, `test_hub_hero`.
- **Server area:** `test_server*` (bands, cards, counts, history, alerts, Update now / Ignore, not-configured states).
- **Media app:** `test_media*` — feature-named files, not build-round names: shelves (`test_media_shelves`), library and list pages (`test_media_library_pages`, `test_media_list_posters`, `test_media_to_rate_pages`), nav and phone fit (`test_media_nav`, `test_media_phone_nav`, `test_media_frame`), film / item / person pages (`test_media_film`, `test_media_film_scores`, `test_media_item`, `test_media_person`), episodes (`test_media_episodes`, `test_media_episode_watch_state`), Discover (`test_media_discover`, `test_media_discover_search_now`), Follow, requests, watchlist, rate and diary, play recorder, backup, warm-up; plus `test_film_quality`.
- **Awards:** `test_awards_*` (recorded Wikidata / Wikipedia answers in `tests/hub/fixtures/awards/`, stored gzipped; parsers, store, sync, pages, UI).

Shared fixtures live in `tests/hub/conftest.py`; shared builders, fakes and sample data (`write_envelope`, `make_area` / `make_tile` / `write_registry`, `shelf_area`, the Jellyfin / Jellyseerr fakes and `ITEMS` / `FILM` samples, `FakeResponse`, the film `env` fixture) live in `tests/hub/helpers.py` — import from there, not from another `test_*` module (`tests/connectors/helpers.py` holds the Radarr/Sonarr ones). `tests/conftest.py` makes the repo importable and has an autouse fixture
that points `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR`, `SNAPSHOT_DIR` and `META_CACHE_DIR` at per-test temp paths, sets
`PLAY_RECORDER`, `MEDIA_BACKUP`, `MEDIA_WARMUP` and `MEDIA_AWARDS` to `off`, and unsets `OMDB_API_KEY` and
`AWARDS_CONTACT`; without it the default `/data/...` resolves to `C:\data\...` on Windows and tests touch a real directory.
