"""Run the Awards sync by hand (AWARDS_PLAN A3, 2026-10-08) — the same code path as the hub's loop.

    python scripts/awards_sync.py --edition oscars:97 [--db PATH] [--gap 2]
    python scripts/awards_sync.py --edition bafta:78
    python scripts/awards_sync.py --pass [--cap 40]

Needs AWARDS_CONTACT in the environment (the User-Agent contact; nothing is called without it). `--edition body:N`
pulls one ceremony: an Oscars edition first finds its Wikidata item (one discovery query) when it is not known yet; a
Wikipedia-sourced one is listed from its ordinal. Cannes / DGA / PGA / WGA take no ordinal (`--edition cannes`): their
winners come from one query for every year. `--db` points MEDIA_DB_PATH at another file (e.g. a throwaway copy);
`--gap` is the pause between calls in seconds (default 2 s); `--wdqs-gap 65` keeps SPARQL calls a minute apart
(WDQS asked for one request a minute during its 2026-10-08 outage). On the NAS (scripts/ is not in the image):
    docker exec -i <hub container> python - --edition oscars:97 < scripts/awards_sync.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_edition(text: str) -> tuple[str, int | None]:
    body, _, n = str(text or "").partition(":")
    from hub import media_awards_seed as seed
    if body not in seed.BY_ID:
        raise SystemExit(f"unknown body {body!r} (one of {', '.join(seed.BY_ID)})")
    if seed.BY_ID[body]["source"] == "wdw":
        return body, None
    if not n.isdigit():
        raise SystemExit("give the edition as body:ordinal, e.g. oscars:97")
    return body, int(n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--edition", help="body:ordinal, e.g. oscars:97 / bafta:78 / cannes")
    ap.add_argument("--pass", dest="full", action="store_true", help="run one normal pass")
    ap.add_argument("--cap", type=int, default=40)
    ap.add_argument("--db", help="MEDIA_DB_PATH for this run")
    ap.add_argument("--gap", type=float, default=None, help="seconds between calls (default 2)")
    ap.add_argument("--wdqs-gap", type=float, default=0.0, help="at least this many seconds between SPARQL calls")
    args = ap.parse_args(argv)
    if args.db:
        os.environ["MEDIA_DB_PATH"] = args.db
    from hub import media_awards as ma, media_awards_db as adb, media_awards_seed as seed
    who = ma.contact()
    if who is None:
        print("AWARDS_CONTACT is not set — nothing called.")
        return 2
    client = ma.Client(who, pace=args.gap if args.gap is not None else ma.PACE_S, wdqs_gap=args.wdqs_gap)
    t0 = time.perf_counter()
    try:
        if args.full:
            counts = ma.run_pass(cap=args.cap, client=client)
        elif args.edition:
            body, n = parse_edition(args.edition)
            b = seed.BY_ID[body]
            with closing(adb.ensure()) as db:
                if b["source"] == "wdw":
                    rows = ma.pull_winners(db, client, b)
                    counts = {"editions": db.execute("SELECT COUNT(*) AS n FROM award_edition WHERE body_id = ?",
                                                     (body,)).fetchone()["n"], "rows": rows, "calls": client.calls}
                    print(_summary(counts, time.perf_counter() - t0))
                    return 0
                if b["source"] == "wp":
                    ma._insert_new(db, body, [{"ordinal": n, "year": b["year_offset"] + n}])
                known = db.execute("SELECT wd_qid FROM award_edition WHERE body_id = ? AND ordinal = ?",
                                   (body, n)).fetchone()
                if b["source"] == "wd" and not (known and known["wd_qid"]):
                    found = ma.editions_from_discovery(client.sparql(ma.discovery_query(*ma.discovery_series())))
                    for bid, rows in found.items():
                        adb.upsert_editions(db, bid, rows)
            counts = ma.run_pass(client=client, only=(body, n), discover_now=False)
        else:
            ap.print_help()
            return 1
    finally:
        client.close()
    print(_summary(counts, time.perf_counter() - t0))
    return 0


def _summary(counts: dict, seconds: float) -> str:
    return " · ".join(f"{k} {v}" for k, v in counts.items()) + f" · {seconds:.1f} s"


if __name__ == "__main__":
    raise SystemExit(main())
