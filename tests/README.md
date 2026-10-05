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
