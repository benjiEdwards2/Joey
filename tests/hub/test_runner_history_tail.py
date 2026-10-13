"""E1 (2026-10-13): `store.get_runner_history` keeps the parsed tail in memory keyed on the file's identity, size and
mtime: an unchanged file is a lookup (< 2 ms on a 2 MB file), an appended one parses only the new bytes, a rotated
(replaced / shrunk) one is read afresh — and every answer equals what the old full re-read gave."""
import json
import os
import random
import time

from hub import store
from tests.hub.helpers import write_envelope


def reference(path, max_lines=store.HISTORY_MAX_LINES, max_bytes=store.HISTORY_MAX_BYTES):
    """The pre-E1 implementation, verbatim in behaviour: the last max_bytes, first line dropped when cut."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            start = max(0, size - max_bytes)
            fh.seek(start)
            raw = fh.read()
    except Exception:
        return None
    lines = raw.split(b"\n")
    if start > 0:
        lines = lines[1:]
    out = []
    for line in lines:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out[-max_lines:]


def sweep(i, pad=0):
    return json.dumps({"ran_at": f"2026-10-13T00:{i % 60:02d}:00Z", "n": i, "results": {"jellyfin": "ok"},
                       "pad": "x" * pad}) + "\n"


def append(path, text):
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(text)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # coarse clocks: the mtime always moves


def test_every_answer_equals_a_full_reread_through_appends_partial_lines_and_rotation(tmp_path):
    path = tmp_path / store.HISTORY_NAME
    rng = random.Random(13)
    path.write_text("", encoding="utf-8")
    n = 0
    for step in range(160):
        roll = rng.random()
        if roll < 0.6:
            text = "".join(sweep(n + k, rng.randint(0, 300)) for k in range(rng.randint(1, 4)))
            n += 4
        elif roll < 0.7:
            text = "not json\n" if rng.random() < 0.5 else "[1, 2]\n"
        elif roll < 0.8:
            text = sweep(n, 50)[:20]          # a writer caught mid-line ...
        elif roll < 0.85:
            text = "\n"                       # ... and its newline later
        elif roll < 0.9:                       # rotation: tmp + os.replace, smaller file
            keep = path.read_bytes()[-3000:]
            tmp = path.with_name("rot.tmp")
            tmp.write_bytes(keep[keep.find(b"\n") + 1:])
            os.replace(tmp, path)
            text = ""
        else:
            text = ""
        if text:
            append(path, text)
        for max_bytes, max_lines in ((store.HISTORY_MAX_BYTES, store.HISTORY_MAX_LINES), (2048, 1000), (900, 5)):
            got = store.get_runner_history(tmp_path, max_lines=max_lines, max_bytes=max_bytes)
            assert got == reference(path, max_lines, max_bytes), (step, max_bytes, max_lines)


def test_an_unchanged_file_is_the_same_list_and_a_grown_one_reads_only_new_bytes(tmp_path, monkeypatch):
    path = tmp_path / store.HISTORY_NAME
    path.write_text("".join(sweep(i) for i in range(50)), encoding="utf-8")
    first = store.get_runner_history(tmp_path)
    assert store.get_runner_history(tmp_path) is first
    parsed = []
    real = store._parse_line
    monkeypatch.setattr(store, "_parse_line", lambda raw: parsed.append(raw) or real(raw))
    append(path, sweep(50) + sweep(51))
    grown = store.get_runner_history(tmp_path)
    assert len(parsed) == 2 and [s["n"] for s in grown[-3:]] == [49, 50, 51]
    assert grown == reference(path)


def test_missing_or_unreadable_is_still_none(tmp_path):
    assert store.get_runner_history(tmp_path) is None
    assert store.get_runner_history(tmp_path / "nope") is None


def test_a_two_megabyte_tail_hit_takes_under_two_ms(tmp_path):
    path = tmp_path / store.HISTORY_NAME
    line = sweep(0, 2000)
    path.write_text(line * (store.HISTORY_MAX_BYTES // len(line) + 50), encoding="utf-8")
    assert path.stat().st_size > store.HISTORY_MAX_BYTES
    cold_t = time.perf_counter()
    cold = store.get_runner_history(tmp_path)
    cold_s = time.perf_counter() - cold_t
    hits = []
    for _ in range(20):
        t = time.perf_counter()
        assert store.get_runner_history(tmp_path) is cold
        hits.append(time.perf_counter() - t)
    hits.sort()
    assert len(cold) > 900 and hits[len(hits) // 2] < 0.002, (cold_s, hits)


def test_the_server_page_reuses_the_hub_cards_parsed_history(tmp_path, monkeypatch):
    """P4: /server and the hub's Server card share one parse of the tail (the kept list) while the file is unchanged."""
    import importlib
    from fastapi.testclient import TestClient
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "system", age_minutes=1, data={"summary": "x"})
    (snaps / store.HISTORY_NAME).write_text("".join(sweep(i) for i in range(30)), encoding="utf-8")
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    monkeypatch.delenv("AREAS_PATH", raising=False)
    import hub.main
    importlib.reload(hub.main)
    reads = []
    real = store._history_lines
    monkeypatch.setattr(store, "_history_lines", lambda *a: reads.append(1) or real(*a))
    with TestClient(hub.main.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/server").status_code == 200
        assert client.get("/server").status_code == 200
    assert len(reads) == 1
