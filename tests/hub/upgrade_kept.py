"""JY-275 (2026-11-04): mark a cutoff-unmet row as checked, the way a Why? search or the sweep's check keeps it."""
from hub import media_upgrade_why


def keep(app: str, arr_id: int, viable: bool = True, reasons=None, quality: str = "Bluray-1080p") -> None:
    cand = {"title": "Some.Release", "indexer": "Idx", "facts": [quality, "Idx"], "first": None if viable else "Not wanted",
            "rejected": not viable, "unknown": False, "guid": "g", "indexer_id": 1}
    if reasons is None:
        reasons = [] if viable else [{"n": 1, "text": "too small"}]
    res = {"summary": "1 release", "reasons": reasons, "hint": None, "candidates": [cand], "app": app, "viable": viable}
    with media_upgrade_why._lock:
        media_upgrade_why._memo[(app, arr_id)] = {"at": media_upgrade_why._clock(), "res": res}
