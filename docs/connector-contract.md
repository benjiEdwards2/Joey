# Connector contract

The one agreement between Track D (connectors, which write) and Track C (the
hub, which reads). Authored at WP23; the envelope it describes was FROZEN at
WP0 (D13). Changing the envelope is a dated DECISIONS.md entry plus a full
suite re-run — never a silent edit.

## THE HUB'S TILES READ SNAPSHOTS ONLY

A tile never calls a live API. Connectors fetch on their own hourly clock and
leave a file behind; the hub renders whatever file is there, or "Not connected"
if there is none. This is why the dashboard still loads when an upstream is down.

The single sanctioned exception is the **/money room page**, which reads SQLite
directly (D14). It is a room page, not a tile.

**Notion is LINK tier.** A URL in `areas.yaml` and nothing else — no connector,
no snapshot, no expectation of one anywhere in the hub.

## Snapshot path convention

| What | Where |
|---|---|
| Live snapshots (the box) | `/opt/life-dashboard-data/snapshots/{id}.json`, mounted at `/data/snapshots` |
| Runner heartbeat | `{SNAPSHOT_DIR}/_runner.json` — last sweep only |
| Runner history | `{SNAPSHOT_DIR}/_runner_history.jsonl` — one line per sweep, append-only (WP38 soak evidence) |
| Committed samples | `config/sample_snapshots/` — the fixture sweep, what hub work is developed against |

Snapshots are **never committed** (D13); `data/` is gitignored. Their offsite
safety is the WP8 encrypted backup.

Writes are atomic: dump to a per-writer `.tmp`, then `os.replace`. A reader can
never see half a snapshot.

## The envelope

`connectors/schema/envelope.schema.json` — every field required, no extras.

| Field | Meaning |
|---|---|
| `connector` | id from the frozen namespace: open_meteo, gcal, clickup, macromates, home_assistant, jellyfin, nas_stats, money, media_status, arr. `clickup` is reserved-but-unused (removed from v1, 2026-08-25). |
| `schema_version` | always `1` |
| `fetched_at` | last fetch **attempt** |
| `updated_at` | last **success** — this is what the hub's stale badge reads |
| `status` | `ok` or `error`. There is no `stale` status: staleness is computed by the hub from `updated_at` against the tile's `stale_after_minutes`. |
| `consecutive_failures` | 0 on success; **≥ 3 triggers the notifier** (WP28) |
| `error` | human-readable reason when status=error, else null |
| `data` | the per-feed payload — see below |

**Failure behaviour.** A failing run does not delete or blank anything: it
re-writes the envelope keeping the previous `data` and `updated_at` byte-for-byte,
sets status=error, bumps `consecutive_failures`, and refreshes `fetched_at` only.
The tile therefore keeps showing the last known value with a stale badge, which
is exactly the agreed failure handling (2026-08-25).

## The `data` block

Each feed has its own schema in `connectors/schema/data/{id}.schema.json`, and
every one of them requires the **hub display convention** (D17, WP18):

- `summary` — **required string**, the one composed line the tile shows
- `secondary` — optional string, the single supporting line

Feed-specific fields sit alongside them. Any person-scoped record carries
`owner: you | her | shared` (R12). `both` is a **view** (the hub's switcher),
never a stored value — the schemas reject it.

`home_assistant` is keyed by area (`house`, `car`, `garden`) because one
connector feeds three tiles; that keying is what lets each tile slice its own
entities instead of all three repeating the same summary.

The **money** data schema is Track E's — WP32 authors it under
`connectors/money/`. The money envelope is written by the importer, a
runner-registered task rather than a `Connector` subclass (D14), and an empty
CSV inbox is `status=ok`, never an error.

## Fixture vs live mode

`CONNECTOR_MODE` is `live` on the box (the default — forgetting the variable can
never silently serve fake data) and `fixture` in the suite and for local work.

- **fixture** — `fetch()` is never called; canned bytes are read from
  `connectors/fixtures/{id}/raw*`, no socket is opened, and BOTH timestamps are
  pinned to `2026-01-01T00:00:00+00:00` so output is byte-reproducible. That
  pinning is what lets `config/sample_snapshots/` be diffed in a test.
- **live** — missing credentials fail fast, and the error names the exact
  environment variable. Credentials live only in `deploy/.env` on the box.

## Cadence

The connectors container runs `while true; do python -m connectors.run_all; sleep 3600; done`
(D16 — a sleep loop, not crond; phase drift after a restart is accepted). One
connector crashing never stops the sweep.

D16 amended 2026-10-05: a second background loop runs
`python -m connectors.run_all --only jellyfin,media_status; sleep 120` for the live Media
feeds. `--only id1,id2` runs a subset and tags the `_runner.json` / history line with
`"only": [...]` so full hourly sweeps can be told apart from fast partial ones.

## Add-a-connector checklist

Every file a new feed touches. Nothing here needs knowledge outside the repo.

1. `connectors/fixtures/{id}/raw*.json` — a canned upstream payload. Fake names
   and `@example.invalid` emails only; no URLs, no token-shaped strings
   (`tests/connectors/test_fixtures.py` enforces this).
2. `connectors/schema/data/{id}.schema.json` — the data block, requiring
   `summary`, allowing `secondary`, `additionalProperties: false`.
3. `connectors/stubs.py` — a `Connector` subclass with `id`, `requires_env`,
   `transform(raw)`, and its live `fetch()`; append it to `STUBS` so it registers.
4. `config/areas.yaml` — a tile with `tier: embed|ingest`, `snapshot: {id}`,
   `stale_after_minutes`, `owner`. The id must already be in the frozen
   namespace in `connectors/schema/envelope.schema.json` (and in `FROZEN_SNAPSHOT_IDS`
   in `hub/registry.py`; `media_status` and `arr` were added to both on 2026-10-05).
5. `config/sample_snapshots/{id}.json` — regenerate the sweep per that folder's
   README and commit the result.
6. `deploy/.env.example` — name any new credential (never its value).
7. `tests/connectors/` — grow the cumulative suite in the SAME session (rule 13).
   The existing `tests/connectors/test_data_schemas.py`,
   `tests/connectors/test_sample_snapshots.py` and
   `tests/connectors/test_id_crosscheck.py` pick a new registered connector up automatically once
   its schema, fixture and sample are in place.
8. `docs/connector-contract.md` — this file, if the contract itself moved.

## Where the container proof stands

`connectors/Dockerfile` and `deploy/docker-compose.yml` were authored blind at
WP22 (the dev machine has no container engine). The first engine-verify: WP24 step 1.
