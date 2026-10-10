"""Movies + TV Shows hub pages (F3b, 2026-10-06): pure helpers over the Jellyfin library
lists. No I/O: the caller passes ratings, an `ago` formatter and an `href_of` resolver, so
tests can drive every rule directly. `deal_tonight` takes a random.Random (deterministic tests)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from hub import media_text

SORTS = ("score", "title", "year", "added", "rating")
SORT_LABELS = {"score": "Your score", "title": "A-Z", "year": "Newest release",
               "added": "Recently added", "rating": "Community rating"}
SHORT_MIN = 105
ARRIVED_DAYS = 7
OLD_FAVOURITE_MIN = 8
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


parse_ts = media_text.parse          # ISO -> aware datetime, None when it is not one
runtime_text = media_text.duration   # 112 -> "1h 52m", 47 -> "47m", 120 -> "2h", missing -> "—"


def _watched_text(played, last, ago) -> str:
    if not played:
        return "Not watched"
    return f"Watched {ago(last)}".strip() if last else "Watched"


def _library_rows(items, ratings, kind, ago, href_of, marks) -> list[dict]:
    rows = []
    for it in items or []:
        key = it.get("item_key")
        eps, unplayed = it.get("episodes") or 0, it.get("unplayed") or 0
        if kind == "movie":
            played, state = bool(it.get("played")), None
        else:
            played = eps > 0 and unplayed == 0               # 0 episodes is not "all watched" (2026-10-10)
            state = "finished" if played else ("not_started" if unplayed >= eps else "watching")
        href, external = href_of(it, kind)
        cr = it.get("community_rating")
        last = it.get("last_played_at") if marks else None
        rows.append({
            "kind": kind, "title": it.get("title") or "Untitled", "year": it.get("year"), "jf_id": it.get("jf_id"),
            "item_key": key, "poster": it.get("poster"), "href": href, "external": external,
            "runtime_min": it.get("runtime_min"), "runtime": runtime_text(it.get("runtime_min")) if it.get("runtime_min") else "",
            "played": played if marks else None, "last_played_at": last,
            "watched_text": _watched_text(played, last, ago) if marks and kind == "movie" else "",
            "added_at": it.get("added_at"),
            "community": float(cr) if isinstance(cr, (int, float)) and cr else None,
            "score": ratings.get(key) if marks and key else None,
            "genres": ", ".join(it.get("genres") or []),
            "status_word": it.get("status_word"), "episodes": eps, "unplayed": unplayed, "state": state,
            "eps_text": "" if kind == "movie" else (
                f"{eps} episode{'' if eps == 1 else 's'}"
                + ((" · All watched" if played else f" · {unplayed} to watch") if marks else "")),
            "last_text": f"Last watched {ago(last)}" if marks and kind == "tv" and last else "",
        })
    return rows


def card_state(row: dict, resume_ids=frozenset()) -> dict | None:
    """The grid card's state word (media-ux4, 2026-10-08): Watched · In progress · Not watched, with its colour class.
    Films: played, else in progress while the viewer's resume list holds it; shows: finished / watching / not started.
    None without watch marks (her view before her own list exists) — no word rather than a wrong one."""
    if row.get("played") is None:
        return None
    if row.get("kind") == "movie":
        key = "watched" if row["played"] else "progress" if str(row.get("jf_id")) in resume_ids else "todo"
    else:
        key = {"finished": "watched", "watching": "progress"}.get(row.get("state"), "todo")
    return {"watched": {"word": "Watched", "cls": "st-good"}, "progress": {"word": "In progress", "cls": "st-progress"},
            "todo": {"word": "Not watched", "cls": "st-todo"}}[key]


def film_rows(items, ratings, ago, href_of, marks=True) -> list[dict]:
    return _library_rows(items, ratings, "movie", ago, href_of, marks)


def show_rows(items, ratings, ago, href_of, marks=True) -> list[dict]:
    return _library_rows(items, ratings, "tv", ago, href_of, marks)


def sort_rows(rows, sort: str) -> list[dict]:
    title = lambda r: r["title"].lower()
    year = lambda r: r["year"] or 0
    if sort == "title":
        return sorted(rows, key=title)
    if sort == "year":
        return sorted(rows, key=lambda r: (-year(r), title(r)))
    if sort == "added":
        return sorted(rows, key=lambda r: (-(parse_ts(r["added_at"]) or _EPOCH).timestamp(), title(r)))
    if sort == "rating":
        return sorted(rows, key=lambda r: (r["community"] is None, -(r["community"] or 0), title(r)))
    return sorted(rows, key=lambda r: (r["score"] is None, -(r["score"] or 0), -year(r), title(r)))


GROUPS = {"movie": [("Watched", lambda r: r["played"]), ("Not yet watched", lambda r: not r["played"])],
          "tv": [("Watching", lambda r: r["state"] == "watching"),
                 ("Not started", lambda r: r["state"] == "not_started"),
                 ("Finished", lambda r: r["state"] == "finished")]}


def arrange(rows, q: str, sort: str, group: bool, kind: str, marks: bool = True) -> list[dict]:
    """Filter by title substring, sort, optionally group -> [{label, rows}] (label None = ungrouped)."""
    q = (q or "").strip().lower()
    rows = [r for r in rows if q in r["title"].lower()]
    rows = sort_rows(rows, sort if sort in SORTS else "score")
    if not group or not marks:
        return [{"label": None, "rows": rows}] if rows else []
    out = [{"label": label, "rows": [r for r in rows if test(r)]} for label, test in GROUPS[kind]]
    return [g for g in out if g["rows"]]


def head_line(rows, kind: str, marks: bool = True) -> str:
    n = len(rows)
    if kind == "movie":
        base = f"{n} film{'' if n == 1 else 's'}"
        if not marks:
            return base
        w = sum(1 for r in rows if r["played"])
        return f"{base} · {w} watched · {n - w} to watch"
    base = f"{n} show{'' if n == 1 else 's'}"
    if not marks:
        return base
    c = lambda s: sum(1 for r in rows if r["state"] == s)
    return f"{base} · {c('watching')} watching · {c('not_started')} not started · {c('finished')} finished"


def arrived_this_week(arrived, kind: str) -> list[dict]:
    """Arr `arrived` rows of this kind from the last week: by the `at` timestamp when the row
    has one, else by its `when` text (older snapshots)."""
    out = []
    now = datetime.now(timezone.utc)
    for r in arrived or []:
        if (r.get("kind") == "movie") != (kind == "movie"):
            continue
        at = parse_ts(r["at"]) if r.get("at") else None
        if at:
            if now - at > timedelta(days=ARRIVED_DAYS):
                continue
        else:
            m = re.match(r"(\d+) days? ago", str(r.get("when") or ""))
            if m and int(m.group(1)) > ARRIVED_DAYS:
                continue
        out.append(r)
    return out


def _norm_title(text) -> str:
    """Lower-case, no punctuation, no leading article, single spaces."""
    words = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split()
    return " ".join(words[1:] if len(words) > 1 and words[0] in ("the", "a", "an") else words)


def link_arrivals(rows, items, kind: str, item_href) -> list[dict]:
    """Add `href` to each arrival: the Joey item page when the Jellyfin list has the same
    item_key, else (Sonarr keys are tvdb, Jellyfin prefers tmdb) when exactly one library
    title matches the normalised series name (several: same year if known, else the first),
    else the title page for a tmdb key, else None (still shown, just not a link).
    The arr schema has no series field, so the name is the part of the title before ' · '.
    `items` = the raw Jellyfin list for this kind (or None); `item_href(jf_id)` -> path | None."""
    items = [i for i in items or [] if i.get("jf_id")]
    by_key = {i["item_key"]: i["jf_id"] for i in items if i.get("item_key")}
    by_title: dict[str, list] = {}
    for i in items:
        by_title.setdefault(_norm_title(i.get("title")), []).append(i)
    seg = "movie" if kind == "movie" else "tv"
    out = []
    for r in rows:
        key = str(r.get("item_key") or "")
        href = item_href(by_key[key]) if by_key.get(key) else None
        if not href:
            name = _norm_title(str(r.get("title") or "").split(" · ")[0])
            cands = by_title.get(name, []) if name else []
            yr = r.get("year")
            pick = next((c for c in cands if yr and c.get("year") == yr), cands[0] if cands else None)
            href = item_href(pick["jf_id"]) if pick else None
        if not href and key.startswith("tmdb:") and key[5:].isdigit():
            href = f"/media/title/{seg}/{key[5:]}"
        out.append({**r, "href": href})
    return out


def _recent(r, now) -> bool:
    ts = parse_ts(r["added_at"])
    return bool(ts) and now - ts <= timedelta(days=ARRIVED_DAYS)


def deal_tonight(rows, ratings, kind, rng, now=None) -> list[dict]:
    """Up to three cards [{row, pile}], each from a different pile where possible; nothing stored.
    Films: short, acclaimed, just arrived, old favourite (played, rated >= 8: the one exception),
    wildcard. TV: pick up where you left off, a fresh start, just arrived, wildcard. If the piles
    can't make three, remaining unplayed titles fill as extra wildcards."""
    now = now or datetime.now(timezone.utc)
    unplayed = [r for r in rows if r["played"] is False]
    piles: dict[str, list] = {}
    if kind == "movie":
        piles["A short one"] = [r for r in unplayed if isinstance(r["runtime_min"], (int, float))
                                and 0 < r["runtime_min"] < SHORT_MIN]
        scored = sorted((r for r in unplayed if r["community"]), key=lambda r: -r["community"])
        piles["Acclaimed"] = scored[:-(-len(scored) // 3)]
        piles["Just arrived"] = [r for r in unplayed if _recent(r, now)]
        piles["Watch again"] = [r for r in rows if r["played"]
                                and (ratings.get(r["item_key"]) or 0) >= OLD_FAVOURITE_MIN]
    else:
        piles["Pick up where you left off"] = [r for r in unplayed if r["state"] == "watching"]
        piles["A fresh start"] = [r for r in unplayed if r["state"] == "not_started"]
        piles["Just arrived"] = [r for r in unplayed if _recent(r, now)]
    piles["Wildcard"] = list(unplayed)
    names = list(piles)
    rng.shuffle(names)
    dealt: list[dict] = []
    used: set[int] = set()
    for name in names:
        if len(dealt) == 3:
            break
        pool = [r for r in piles[name] if id(r) not in used]
        if not pool:
            continue
        if name == "Acclaimed":   # lean to the top of the pile: weight by rank
            pick = rng.choices(pool, weights=range(len(pool), 0, -1))[0]
        else:
            pick = rng.choice(pool)
        used.add(id(pick))
        dealt.append({"row": pick, "pile": name})
    spare = [r for r in unplayed if id(r) not in used]
    rng.shuffle(spare)
    while len(dealt) < 3 and spare:
        dealt.append({"row": spare.pop(), "pile": "Wildcard"})
    rng.shuffle(dealt)
    return dealt
