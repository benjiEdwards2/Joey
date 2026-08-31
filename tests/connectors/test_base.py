"""WP22 step 3 — the run() wrapper: atomic writes, failure preserves history."""

import json
import time
import threading

from connectors.base import Connector


class Dummy(Connector):
    id = "open_meteo"

    def __init__(self, payload=None, boom=False):
        self.payload = payload or {"summary": "18 °C · light rain", "now_c": 18}
        self.boom = boom

    def fetch_fixture(self):
        if self.boom:
            raise RuntimeError("upstream down")
        return self.payload

    def transform(self, raw):
        return raw


def test_success_writes_schema_valid_envelope(snapshots, validate_envelope):
    envelope = Dummy().run()
    validate_envelope(envelope)
    on_disk = json.loads((snapshots / "open_meteo.json").read_text(encoding="utf-8"))
    assert on_disk == envelope
    assert on_disk["status"] == "ok"
    assert on_disk["consecutive_failures"] == 0
    assert on_disk["error"] is None


def test_failure_preserves_data_and_updated_at_and_bumps_counter(snapshots, validate_envelope):
    good = Dummy().run()

    first_failure = Dummy(boom=True).run()
    validate_envelope(first_failure)
    assert first_failure["status"] == "error"
    assert first_failure["data"] == good["data"]           # byte-identical payload
    assert first_failure["updated_at"] == good["updated_at"]  # last SUCCESS untouched
    assert first_failure["consecutive_failures"] == 1
    assert "upstream down" in first_failure["error"]

    second_failure = Dummy(boom=True).run()
    assert second_failure["consecutive_failures"] == 2
    assert second_failure["data"] == good["data"]

    recovered = Dummy().run()
    assert recovered["status"] == "ok" and recovered["consecutive_failures"] == 0


def test_first_ever_run_failure_is_still_schema_valid(snapshots, validate_envelope):
    envelope = Dummy(boom=True).run()
    validate_envelope(envelope)
    assert envelope["data"] == {} and envelope["consecutive_failures"] == 1


def test_concurrent_runs_never_leave_a_truncated_file(snapshots):
    path = snapshots / "open_meteo.json"
    Dummy().run()
    stop = threading.Event()
    corrupt: list[str] = []

    def writer(n):
        for i in range(60):
            Dummy(payload={"summary": f"w{n}-{i}", "pad": "x" * 400}).run()

    def reader():
        # Poll like the hub does — repeatedly, but not at 100% duty cycle
        # (Windows blocks os.replace while a reader holds the file open).
        while not stop.is_set():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, PermissionError):
                # Windows briefly denies opening the destination mid-replace.
                # Transient, and never a PARTIAL read — which is what atomicity
                # promises. hub/store.py already treats an unreadable snapshot
                # as absent, so this is the production behaviour too.
                pass
            except Exception as exc:  # a JSON decode error here == truncation
                corrupt.append(str(exc))
            time.sleep(0.001)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    watcher = threading.Thread(target=reader)
    watcher.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    watcher.join()

    assert not corrupt, f"reader saw a partial snapshot: {corrupt[:3]}"
    json.loads(path.read_text(encoding="utf-8"))
    assert not list(snapshots.glob("*.tmp")), "temp file left behind"
