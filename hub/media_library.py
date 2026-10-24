"""Movies + TV Shows hub pages (F3b, 2026-10-06): pure helpers over the Jellyfin library
lists. No I/O: the caller passes ratings, an `ago` formatter and an `href_of` resolver, so
tests can drive every rule directly. `deal_tonight` takes a random.Random (deterministic tests)."""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

from hub import media_text

# Library round (2026-10-13, B.): six more sorts; "Most to watch" is offered on the TV page only (sort_labels).
SORTS = ("score", "title", "year", "added", "rating", "last", "runtime_short", "runtime_long", "oldest", "genre",
         "shuffle", "to_watch")
SORT_LABELS = {"score": "Your score", "title": "A-Z", "year": "Newest release",
               "added": "Recently added", "rating": "Community rating", "last": "Last watched",
               "runtime_short": "Shortest first", "runtime_long": "Longest first", "oldest": "Oldest release",
               "genre": "Genre A-Z", "shuffle": "Shuffle", "to_watch": "Most to watch"}
TV_ONLY_SORTS = ("to_watch",)
SHORT_MIN = 105
ARRIVED_DAYS = 7
OLD_FAVOURITE_MIN = 8
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


parse_ts = media_text.parse          # ISO -> aware datetime, None when it is not one
runtime_text = media_text.duration   # 112 -> "1h 52m", 47 -> "47m", 120 -> "2h", missing -> "—"


def empty_series(row) -> bool:
    """WP-T1 (2026-10-19): a library show row with a counted 0 episodes - Sonarr's folder before any file arrived. It
    is not a library entry and not "On server". A row without an `episodes` count (older snapshots) or with an unknown
    one (None, JY-115: Jellyfin gave no count) is not empty."""
    return isinstance(row, dict) and row.get("episodes") == 0


def _watched_text(played, last, ago) -> str:
    if not played:
        return "Not watched"
    return f"Watched {ago(last)}".strip() if last else "Watched"


def _library_rows(items, ratings, kind, ago, href_of, marks, runtimes=None) -> list[dict]:
    """`runtimes` (E5, M2): {show_key: average episode minutes} for the progress words' hours (media_plays_db)."""
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
        progress = (media_text.progress_words(unplayed, eps, (runtimes or {}).get(f"jf:{it.get('jf_id')}"))
                    if marks and kind == "tv" else None)
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
            # E5 (M2): "26 episodes · 6 left · ~4h 30m" (was "· 6 to watch"); "· All watched" as before
            "eps_text": "" if kind == "movie" else (
                (f"{eps} episode{'' if eps == 1 else 's'}" if it.get("episodes") is not None else "")
                + (f" · {progress}" if progress else "")),
            "progress": progress,
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
        key = {"finished": "watched", "watching": "progress", "caught_up": "caught_up"}.get(row.get("state"), "todo")
    return {"watched": {"word": "Watched", "cls": "st-good"}, "progress": {"word": "In progress", "cls": "st-progress"},
            "caught_up": {"word": "Caught up", "cls": "st-good"},   # WP-T1: every episode watched, more still due
            "todo": {"word": "Not watched", "cls": "st-todo"}}[key]


def apply_season_state(rows, state_of) -> None:
    """WP-T1 (2026-10-19): Sonarr's words on show rows, in place. `state_of(row)` -> media_season_state's cached state or
    None. A show with episodes still to come or aired-but-missing gains them after its episode words ("6 episodes · All
    watched · 2 to come · next airs 2 Nov"), and a fully watched one is "Caught up", not "Finished", while more is due.
    Rows without a state keep their words."""
    for r in rows or []:
        st = state_of(r) if r.get("kind") == "tv" else None
        if not st or not st.get("word") or not (st.get("to_come") or st.get("missing")):
            continue
        r["sonarr_word"] = st["word"]
        r["eps_text"] = (r["eps_text"] + " · " if r.get("eps_text") else "") + st["word"]
        if r.get("state") == "finished":
            r["state"] = "caught_up"


def film_rows(items, ratings, ago, href_of, marks=True) -> list[dict]:
    return _library_rows(items, ratings, "movie", ago, href_of, marks)


def show_rows(items, ratings, ago, href_of, marks=True, runtimes=None) -> list[dict]:
    return _library_rows(items, ratings, "tv", ago, href_of, marks, runtimes)


def sort_labels(kind: str) -> dict:
    """The sort select's {key: label} for this page: every sort, less the TV-only ones on the films page."""
    return {k: v for k, v in SORT_LABELS.items() if kind == "tv" or k not in TV_ONLY_SORTS}


def sort_rows(rows, sort: str, rng=None) -> list[dict]:
    """`rng` (a random.Random) only for "shuffle": a fresh order each request unless a test passes a seeded one."""
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
    if sort == "last":   # never watched last
        last = lambda r: parse_ts(r.get("last_played_at"))
        return sorted(rows, key=lambda r: (last(r) is None, -(last(r) or _EPOCH).timestamp(), title(r)))
    if sort in ("runtime_short", "runtime_long"):   # unknown runtime last either way
        sign = 1 if sort == "runtime_short" else -1
        mins = lambda r: r["runtime_min"] if isinstance(r.get("runtime_min"), (int, float)) and r["runtime_min"] > 0 else None
        return sorted(rows, key=lambda r: (mins(r) is None, sign * (mins(r) or 0), title(r)))
    if sort == "oldest":   # unknown year last
        return sorted(rows, key=lambda r: (not r["year"], year(r), title(r)))
    if sort == "genre":    # by the first genre, then title; no genre last
        first = lambda r: (r.get("genres") or "").split(", ")[0].lower()
        return sorted(rows, key=lambda r: (not first(r), first(r), title(r)))
    if sort == "shuffle":
        out = list(rows)
        (rng or random.Random()).shuffle(out)
        return out
    if sort == "to_watch":
        return sorted(rows, key=lambda r: (-(r.get("unplayed") or 0), title(r)))
    return sorted(rows, key=lambda r: (r["score"] is None, -(r["score"] or 0), -year(r), title(r)))


# Library round (2026-10-13, B.): the Grouped chip and its sections are gone - one flat grid, narrowed by a filter chip.
# Films: "continue" = in the viewer's resume list; "unwatched" = not played and not in it; "watched" = played.
# Shows: "Caught up" (WP-T1's state - every episode watched, more still due) takes the place of its old group.
FILTERS = {"movie": {"all": "All", "continue": "Continue watching", "unwatched": "Not yet watched", "watched": "Watched"},
           "tv": {"all": "All", "watching": "Watching", "not_started": "Not started", "caught_up": "Caught up",
                  "finished": "Finished"}}


def _in_filter(r, f: str, resume_ids) -> bool:
    if r.get("kind") == "movie":
        resumed = str(r.get("jf_id")) in resume_ids
        return {"continue": resumed, "unwatched": not r["played"] and not resumed,
                "watched": bool(r["played"])}.get(f, True)
    return r.get("state") == f if f in FILTERS["tv"] and f != "all" else True


def arrange(rows, q: str, sort: str, f: str, kind: str, resume_ids=frozenset(), rng=None) -> list[dict]:
    """Filter by title substring and the filter chip (`f`, a FILTERS key; anything else = all), then sort."""
    q = (q or "").strip().lower()
    f = f if f in FILTERS[kind] else "all"
    rows = [r for r in rows if q in r["title"].lower() and (f == "all" or _in_filter(r, f, resume_ids))]
    return sort_rows(rows, sort if sort in sort_labels(kind) else "score", rng)


# Suggestions carousel (2026-10-13, B.): New (the arr's arrivals this week) · Continue watching · Not yet watched.
SUGGESTIONS = {"new": "New", "continue": "Continue watching", "unwatched": "Not yet watched"}
SUGGESTION_EMPTY = {"new": "Nothing new this week", "continue": "Nothing in progress",
                    "unwatched": "Nothing left to watch"}
NO_MARKS_EMPTY = "No marks for her yet"   # 2026-10-22: her shows' Continue watching before her own list exists
SUGGEST_MAX = 12


def suggestions(rows, kind: str, which: str, resume=(), marks: bool = True) -> list[dict]:
    """Carousel items {title, poster, href, when} for "continue" / "unwatched" (the caller passes "new" itself).
    Films continue = the viewer's resume rows (`resume`, in_progress only, Jellyfin's most-recently-played-first
    order) that are in the library; shows = state watching, latest last_played_at first. Unwatched = films not played
    and not resumed / shows not started, most recently added first. Up to SUGGEST_MAX; nothing without watch marks
    (her view before her own list exists), except her own resume list."""
    def item(r, when):
        return {"title": r["title"], "poster": r["poster"], "href": r["href"], "when": when}
    if which == "continue" and kind == "movie":
        by_id = {str(r.get("jf_id")): r for r in rows if r.get("jf_id")}
        out = [item(by_id[str(x.get("jf_id"))], x.get("remaining_text") or "") for x in resume
               if str(x.get("jf_id")) in by_id]
    elif not marks:
        return []
    elif which == "continue":
        last = lambda r: parse_ts(r.get("last_played_at"))
        picked = sorted((r for r in rows if r["state"] == "watching"),
                        key=lambda r: (last(r) is None, -(last(r) or _EPOCH).timestamp(), r["title"].lower()))
        out = [item(r, r.get("progress") or "") for r in picked]
    elif which == "unwatched":
        resumed = {str(x.get("jf_id")) for x in resume}
        keep = ((lambda r: not r["played"] and str(r.get("jf_id")) not in resumed) if kind == "movie"
                else (lambda r: r["state"] == "not_started"))
        out = [item(r, str(r["year"] or "")) for r in sort_rows([r for r in rows if keep(r)], "added")]
    else:
        return []
    return out[:SUGGEST_MAX]


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
    caught = f" · {c('caught_up')} caught up" if c("caught_up") else ""   # WP-T1: only when Sonarr says more is due
    return f"{base} · {c('watching')} watching · {c('not_started')} not started{caught} · {c('finished')} finished"


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


def library_index(items) -> dict:
    """The lookups link_arrivals matches against, built once (E1: a page linking many rows builds it once, not per
    row): {by_key: item_key -> jf_id, by_title: normalised title -> [items]}."""
    items = [i for i in items or [] if i.get("jf_id")]
    by_title: dict[str, list] = {}
    for i in items:
        by_title.setdefault(_norm_title(i.get("title")), []).append(i)
    return {"by_key": {i["item_key"]: i["jf_id"] for i in items if i.get("item_key")}, "by_title": by_title}


def link_arrivals(rows, items, kind: str, item_href, index: dict | None = None) -> list[dict]:
    """Add `href` to each arrival: the Joey item page when the Jellyfin list has the same
    item_key, else (Sonarr keys are tvdb, Jellyfin prefers tmdb) when exactly one library
    title matches the normalised series name (several: same year if known, else the first),
    else the title page for a tmdb key, else None (still shown, just not a link).
    The arr schema has no series field, so the name is the part of the title before ' · '.
    `items` = the raw Jellyfin list for this kind (or None); `item_href(jf_id)` -> path | None. `index` = a
    library_index(items) already built (then `items` is not read)."""
    index = library_index(items) if index is None else index
    by_key, by_title = index["by_key"], index["by_title"]
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
