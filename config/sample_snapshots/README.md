# sample_snapshots

The fixture-mode sweep, committed. This is what hub tiles are developed and
demoed against before any live credential exists (WP23).

Regenerate after changing a fixture or a `transform()`:

```sh
CONNECTOR_MODE=fixture SNAPSHOT_DIR=/tmp/snapgen python -m connectors.run_all
cp /tmp/snapgen/*.json config/sample_snapshots/   # then delete _runner_history.jsonl
```

Timestamps are pinned to `2026-01-01T00:00:00+00:00` in fixture mode, so the
output is byte-reproducible — `tests/connectors/test_sample_snapshots.py`
fails if what is committed here drifts from a fresh sweep.

`_runner_history.jsonl` is deliberately NOT committed: it is append-only
runtime evidence and lives on the box only (D13).
