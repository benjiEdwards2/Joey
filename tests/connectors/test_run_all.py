"""WP22 step 5 — the sweep: isolation, heartbeat, append-only history."""

import json

from connectors.base import Connector
from connectors.run_all import HEARTBEAT_NAME, HISTORY_NAME, run_sweep


class Good(Connector):
    id = "open_meteo"

    def fetch_fixture(self):
        return {"summary": "18 °C · light rain"}

    def transform(self, raw):
        return raw


class Raiser(Connector):
    """Worst case: even run() blows up (a broken subclass), not just fetch()."""

    id = "nas_stats"

    def run(self):
        raise RuntimeError("connector exploded")


def test_one_crash_never_blocks_the_rest(snapshots, validate_envelope):
    sweep = run_sweep([Raiser(), Good()])

    good_path = snapshots / "open_meteo.json"
    assert good_path.exists(), "a crashing connector stopped a healthy one"
    validate_envelope(json.loads(good_path.read_text(encoding="utf-8")))
    assert sweep["results"]["open_meteo"]["status"] == "ok"
    assert sweep["results"]["nas_stats"]["status"] == "error"
    assert "connector exploded" in sweep["results"]["nas_stats"]["error"]


def test_heartbeat_lists_every_connector(snapshots):
    run_sweep([Raiser(), Good()])
    beat = json.loads((snapshots / HEARTBEAT_NAME).read_text(encoding="utf-8"))
    assert set(beat["results"]) == {"open_meteo", "nas_stats"}
    assert beat["ran_at"]


def test_history_gains_exactly_one_line_per_sweep(snapshots):
    history = snapshots / HISTORY_NAME
    for expected in (1, 2, 3):
        run_sweep([Good()])
        lines = history.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == expected
        assert json.loads(lines[-1])["results"]["open_meteo"]["status"] == "ok"


def test_main_exits_zero_even_with_a_failing_feed(snapshots, monkeypatch):
    from connectors import registry, run_all

    monkeypatch.setattr(registry, "build_all", lambda: [Raiser(), Good()])
    assert run_all.main() == 0


def test_only_filters_and_tags_the_history_line(snapshots):
    sweep = run_sweep([Raiser(), Good()], only=["open_meteo"])
    assert set(sweep["results"]) == {"open_meteo"}
    assert sweep["only"] == ["open_meteo"]
    line = json.loads((snapshots / HISTORY_NAME).read_text(encoding="utf-8").splitlines()[-1])
    assert line["only"] == ["open_meteo"]


def test_full_sweep_history_line_has_no_only_tag(snapshots):
    run_sweep([Good()])
    line = json.loads((snapshots / HISTORY_NAME).read_text(encoding="utf-8").splitlines()[-1])
    assert "only" not in line


def test_main_parses_only_argument(snapshots, monkeypatch):
    from connectors import registry, run_all

    monkeypatch.setattr(registry, "build_all", lambda: [Raiser(), Good()])
    assert run_all.main(["--only", "open_meteo, nas_stats"]) == 0
    beat = json.loads((snapshots / HEARTBEAT_NAME).read_text(encoding="utf-8"))
    assert beat["only"] == ["open_meteo", "nas_stats"]


def test_heartbeat_is_written_atomically_via_os_replace(snapshots, monkeypatch):
    """C-15: two loops write _runner.json while the hub reads it — tmp + os.replace."""
    from connectors import base

    replaced = []
    real = base.os.replace

    def spy(src, dst):
        replaced.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(base.os, "replace", spy)
    run_sweep([Good()])
    assert any(dst.endswith(HEARTBEAT_NAME) and src.endswith(".tmp") for src, dst in replaced)
    assert not list(snapshots.glob("*.tmp"))
    beat = json.loads((snapshots / HEARTBEAT_NAME).read_text(encoding="utf-8"))
    assert beat["results"]["open_meteo"]["status"] == "ok"


# ---- 2026-10-09 review (C-16, N-10, N-11): timings + bounded history ----


def test_history_line_carries_timings_but_the_heartbeat_does_not(snapshots):
    run_sweep([Raiser(), Good()])
    line = json.loads((snapshots / HISTORY_NAME).read_text(encoding="utf-8").splitlines()[-1])
    assert isinstance(line["sweep_ms"], int) and line["sweep_ms"] >= 0
    for cid in ("open_meteo", "nas_stats"):
        assert isinstance(line["results"][cid]["duration_ms"], int) and line["results"][cid]["duration_ms"] >= 0
    # otherwise the same shape the hub tails: {ran_at, results: {id: {status, error, ...}}, only?}
    assert line["results"]["open_meteo"]["status"] == "ok" and line["ran_at"]
    beat = json.loads((snapshots / HEARTBEAT_NAME).read_text(encoding="utf-8"))
    assert "sweep_ms" not in beat and "duration_ms" not in beat["results"]["open_meteo"]


def _seed_history(path, days_ago_list):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)  # the fixture clock
    with path.open("w", encoding="utf-8") as fh:
        for days in days_ago_list:
            at = (base - timedelta(days=days)).isoformat(timespec="seconds")
            fh.write(json.dumps({"ran_at": at, "results": {"open_meteo": {"status": "ok", "error": None,
                                                                           "pad": "x" * 200}}}) + "\n")


def test_history_over_the_cap_is_rewritten_to_the_last_14_days(snapshots, monkeypatch):
    from connectors import run_all

    history = snapshots / HISTORY_NAME
    _seed_history(history, [30] * 8 + [20, 15, 13, 5, 1])
    monkeypatch.setattr(run_all, "HISTORY_MAX_BYTES", 3000)  # seed is ~3.4 kB: over
    run_sweep([Good()])
    lines = [json.loads(x) for x in history.read_text(encoding="utf-8").splitlines()]
    assert [x["ran_at"][:10] for x in lines] == ["2025-12-19", "2025-12-27", "2025-12-31", "2026-01-01"]
    assert "sweep_ms" in lines[-1]                       # the new line survived, last
    assert history.stat().st_size <= 3000 // 2
    assert not list(snapshots.glob("*.tmp"))


def test_rotation_keeps_only_the_newest_half_cap_when_14_days_is_too_big(snapshots, monkeypatch):
    from connectors import run_all

    history = snapshots / HISTORY_NAME
    _seed_history(history, [3, 2, 1, 0])
    monkeypatch.setattr(run_all, "HISTORY_MAX_BYTES", 800)
    run_sweep([Good()])
    lines = history.read_text(encoding="utf-8").splitlines()
    assert history.stat().st_size <= 400 and json.loads(lines[-1])["sweep_ms"] >= 0
    assert len(lines) < 5


def test_history_under_the_cap_is_never_rewritten(snapshots, monkeypatch):
    from connectors import run_all

    history = snapshots / HISTORY_NAME
    _seed_history(history, [30, 1])
    monkeypatch.setattr(run_all, "_rotate_history", lambda *a: (_ for _ in ()).throw(AssertionError))
    run_sweep([Good()])
    assert len(history.read_text(encoding="utf-8").splitlines()) == 3
