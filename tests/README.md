# tests/ — the cumulative suite

The growth law, verbatim from MASTER_PLAN "Testing & release gates" (binding, §2 rule 13):

> **Growth law (append-only):** a WP that changes code lands its tests in the same session.
> A bugfix session writes the failing regression test FIRST, then fixes until green — the test
> stays forever. A test is never deleted, weakened, or skipped without a dated DECISIONS.md
> line saying why.

Runner, dev machine (fixture-mode, no credentials, no network — must pass anywhere):

    python -m pytest -q tests/

On the box the same suite runs inside the freshly built images
(`docker compose build && docker compose run --rm hub python -m pytest -q tests/`) —
what is tested is exactly what ships. `deploy/deploy.sh` is the only path to production
and aborts on any failure.

| Dir | Owns |
|---|---|
| `tests/hub/` | shell, loader, tile states, owner semantics |
| `tests/connectors/` | envelope + per-feed schemas, fixture tests, read-only greps |
| `tests/money/` | importer, rules, golden month, plaintext-never-in-git guard |
| `tests/deploy/` | smoke.py and deploy-gate checks |

Media suites live in `tests/hub/` (`test_media_*.py`: shelves, discover, her view, backup, frame) and
`tests/connectors/` (`test_jellyfin.py`, `test_arr.py`).

Rail section + brand link (2026-10-06): `test_registry.py` covers `rail_section`; `test_apex_shell.py` covers Home-group rendering and the brand home link.

`tests/conftest.py` has an autouse fixture that points `MEDIA_DB_PATH`, `MEDIA_BACKUP_DIR` and `SNAPSHOT_DIR` at per-test temp paths and sets `PLAY_RECORDER=off` and `MEDIA_BACKUP=off`; without it the default `/data/...` resolves to `C:\data\...` on Windows and tests touch a real directory.

Hidden (parked) areas (2026-10-06): `test_hidden_areas.py` covers the registry `hidden` flag, rail / phone bar / hub row exclusion, `/a/<id>` still serving, the hub KPI order Media · Weather · Calendar with `kpis few` + `span2`, and the Calendar page dropping its Weather KPI tile. Pins reworded for this: `test_apex_hub.py` (visible areas only; money card gone), `test_apex_areas.py` (weather tile excluded where the band renders), `test_hub_hero.py` / `test_styling.py` (last card may carry `span2`), `test_owner_filter.py` (shared tile reads `money`, not `open_meteo`), `test_hub_reads_samples.py` (kitchen has no hub card).

Signed-in user (2026-10-06): `test_identity.py` covers `hub/identity.py` (Access header == `OWNER_EMAIL_YOU` ⇒ you, any other address ⇒ her, no header ⇒ not signed in, env display names), the header-forced owner view (query and cookie ignored, no cookie set), the rail footer + top-bar user chip, the greeting with and without a name, no Both/You/Her switcher on shell or Media pages, the brand reading just "Joey", and media.db writes landing as the signed-in owner. Only placeholder `example.com` addresses appear in tests. Pins reworded for this: `test_apex_shell.py` (rail shows "Not signed in"/"Local preview" and no `joeyhome.net`; greeting has no name without the header; brand has no `joeyhome.net`), `test_media_frame.py::test_switcher_links_to_current_media_path` and `::test_switcher_keeps_the_query_string` (no switcher links; the query still sets the view locally / the sections nav still lights), `test_owner_filter.py::test_switcher_links_render_plain_hrefs` (no switcher links; the plain query still filters).
