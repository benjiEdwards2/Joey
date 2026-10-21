"""Why? + Grab anyway (WP-U1, 2026-10-21). B. saw "Upgrade available" on Brothers (2026) S01E01 (HDTV-1080p, profile
"1080p" wanting WEB/Bluray 1080p) and "Search upgrades" ran - "1 episodes searched, 0 reports downloaded". The question
was WHY: Sonarr's interactive search answered 30 releases, every one rejected, almost all by the profile's minimum
custom-format score (1000) that nothing reaches.

Each row of Activity › Downloads › Upgrades carries "Why?" (`_upgrade_why.html`):

1. GET /media/upgrades/why/{app}/{arr_id}?step=confirm - the inline confirm (no call). Without JS the link is the
   page itself with `?why=<app>:<id>&why_step=confirm`, which draws the same card.
2. POST (same_origin) - the app's interactive search: Radarr `GET /api/v3/release?movieId=<arr_id>`, Sonarr
   `GET /api/v3/release?episodeId=<the row's episode_id>` (the row's `sample` episode - one search, the profile is the
   series'). It hits every indexer and grabs NOTHING; 10-60 s live, so a worker thread with a 90 s timeout. The answer
   is kept 1 h per row (`_memo`) and drawn as counts, grouped reasons, a hint when the profile's custom-format minimum
   rejects everything, and the top 5 releases.
3. "Grab anyway" on a listed release: GET ?step=grab&pick=<n> draws its confirm (no call), the same_origin POST .../grab
   sends `POST /api/v3/release {"guid", "indexerId"}` taken from the kept answer (never from the form) - the app
   downloads it even though it rejected it ("Unknown Series" may still fail at import, and the card says so).

The page render never calls an arr app: it draws "Why?" and, for the row named in `?why=`, the kept answer only.
Logs carry the app and an HTTP status / exception type - never a release title, guid, URL or key.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from hub import media_discover as md, media_item, media_requests as mr, media_text, media_upgrades, shell, upstream
from hub.media_write import flash_keys, form_of, is_htmx, same_origin

log = logging.getLogger("hub.media_upgrade_why")
router = APIRouter()

WHY_TIMEOUT = 90     # s: the interactive search (every indexer)
GRAB_TIMEOUT = 30    # s: the grab (the app hands it to the download client)
TTL = 3600           # s: a row's answer is kept this long
TOP = 5              # releases listed
BACK = "/media/downloads"
NAMES = {"radarr": "Radarr", "sonarr": "Sonarr"}
UNKNOWN = {"radarr": "Unknown Movie", "sonarr": "Unknown Series"}

ASK_FAIL = {"unset": "{app} is not connected", "unreachable": "Couldn't reach {app} · try again",
            "refused": "{app} refused the search", "noepisode": "No episode id yet · try after the next refresh"}
GRAB = {"sent": ("Grab sent · check Downloads in a minute", True),
        "gone": ("{app} no longer holds that release · ask Why? again", False),
        "expired": ("That search has expired · ask Why? again", False),
        "refused": ("{app} refused the grab", False),
        "unreachable": ("Couldn't reach {app}", False),
        "unset": ("{app} is not connected", False)}

flash_keys("why", "why_step", "pick", "wf", "grab", "gcode")

_lock = threading.Lock()
_memo: dict[tuple[str, int], dict] = {}   # (app, arr_id) -> {"at": clock, "res": the drawn answer + guids}
_clock = time.monotonic


def clear_cache() -> None:
    with _lock:
        _memo.clear()


def peek(app: str, arr_id: int) -> dict | None:
    """The kept answer for this row while under TTL, else None - never a call."""
    with _lock:
        m = _memo.get((app, arr_id))
    return m if m and _clock() - m["at"] < TTL else None


# ---- the answer, in words ----

def _text(rej) -> str:
    """A rejection as text: v3 sends strings; a newer build may send {reason, message}."""
    if isinstance(rej, dict):
        return str(rej.get("message") or rej.get("reason") or "")
    return str(rej or "")


CF_MIN = re.compile(r"custom formats?.*score (-?\d+) below .*minimum (-?\d+)", re.I)
REASONS = ((re.compile(r"is not wanted in profile", re.I), "quality not wanted in profile"),
           (re.compile(r"smaller than minimum allowed", re.I), "too small"),
           (re.compile(r"larger than maximum allowed", re.I), "too large"),
           (re.compile(r"^unknown series", re.I), "unknown series"),
           (re.compile(r"^unknown movie", re.I), "unknown movie"),
           (re.compile(r"not an upgrade|existing file.*(meets|equal|higher)|cutoff already met", re.I),
            "not better than the file on disk"),
           (re.compile(r"blocklist|blacklist", re.I), "blocklisted"),
           (re.compile(r"seeders", re.I), "too few seeders"),
           (re.compile(r"delay", re.I), "held by a delay profile"),
           (re.compile(r"not monitored|isn't monitored", re.I), "not monitored"))


def reason(text: str) -> tuple[str, str]:
    """(group key, words) for one rejection. The custom-format minimum keeps its number; anything unknown is its own
    group, verbatim (≤ 100 characters)."""
    m = CF_MIN.search(text)
    if m:
        return f"cf:{m.group(2)}", f"custom-format score below the profile minimum ({m.group(2)})"
    for rx, words in REASONS:
        if rx.search(text):
            return words, words
    short = text.strip()[:100] or "no reason given"
    return short, short


def _size(n) -> str | None:
    try:
        b = float(n)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    return f"{b / 1024 ** 3:.1f} GB" if b >= 1024 ** 3 else f"{b / 1024 ** 2:.1f} MB"


def summarize(releases, app: str, profile: str | None = None, sample: str | None = None) -> dict:
    """The interactive search's list -> {summary, reasons: [{n, text}], hint, candidates}. Candidates (≤ TOP, accepted
    ones first, else the app's own order) keep `guid` / `indexer_id` for the grab; they are drawn, never logged."""
    rels = [r for r in releases or [] if isinstance(r, dict)]
    n = len(rels)
    bad = {i for i, r in enumerate(rels) if r.get("rejected") or (r.get("rejections") and not r.get("approved"))}
    ok = n - len(bad)
    if not n:
        summary = "No releases found"
    elif not ok:
        summary = f"{n} release{'' if n == 1 else 's'} · {'rejected' if n == 1 else 'all rejected'}"
    elif not bad:
        summary = f"{n} release{'' if n == 1 else 's'} · {'accepted' if n == 1 else 'all accepted'}"
    else:
        summary = f"{n} releases · {ok} accepted · {len(bad)} rejected"
    if sample:
        summary = f"{sample} · {summary}"

    counts: Counter = Counter()
    words: dict[str, str] = {}
    cf_every, cf_min = bool(bad) and not ok, Counter()
    for i in sorted(bad):
        r, seen = rels[i], set()
        for rej in r.get("rejections") or []:
            key, w = reason(_text(rej))
            words.setdefault(key, w)
            seen.add(key)
        counts.update(seen)
        cf = [k for k in seen if k.startswith("cf:")]
        cf_min.update(cf)
        if not cf:
            cf_every = False
    reasons = [{"n": c, "text": words[k]} for k, c in counts.most_common()]

    hint = None
    if cf_every and cf_min:
        minimum = cf_min.most_common(1)[0][0][3:]
        whose = f"The {profile} profile's" if profile else "The profile's"
        hint = (f"{whose} minimum custom-format score ({minimum}) rejects every release for this title — lower it in "
                f"{NAMES[app]} › Settings › Profiles, or grab one anyway.")

    order = sorted(range(n), key=lambda i: (i in bad, i))
    cands = []
    for i in order[:TOP]:
        r = rels[i]
        rejs = [_text(x) for x in r.get("rejections") or [] if _text(x)]
        seeders = r.get("seeders")
        facts = [((r.get("quality") or {}).get("quality") or {}).get("name"), _size(r.get("size")),
                 (f"{seeders} seeder{'' if seeders == 1 else 's'}" if isinstance(seeders, int) else None),
                 r.get("indexer"), r.get("releaseGroup")]
        cands.append({"title": str(r.get("title") or "Untitled")[:200], "indexer": str(r.get("indexer") or "the indexer"),
                      "facts": [str(f) for f in facts if f], "first": rejs[0][:160] if rejs and i in bad else None,
                      "rejected": i in bad, "unknown": any(t.lower().startswith(UNKNOWN[app].lower()) for t in rejs),
                      "guid": r.get("guid"), "indexer_id": r.get("indexerId")})
    return {"summary": summary, "reasons": reasons, "hint": hint, "candidates": cands, "app": app}


# ---- the calls (explicit actions only) ----

def row_of(snaps, app: str, arr_id: int) -> dict | None:
    """The snapshot's upgrade row for (app, arr_id), or None - Why? only runs for a listed row."""
    for r in (media_upgrades.upgrades(snaps) or {}).get(app) or []:
        if isinstance(r, dict) and r.get("arr_id") == arr_id:
            return r
    return None


def _status(why: str) -> int | None:
    return int(why[5:]) if why.startswith("HTTP ") and why[5:].isdigit() else None


def _search(app: str, arr_id: int, row: dict) -> dict:
    base, headers = mr._arr_creds(app)
    params = {"movieId": arr_id} if app == "radarr" else {"episodeId": int(row["episode_id"])}
    resp = upstream.session("arr").get(f"{base}/api/v3/release", params=params, headers=headers, timeout=WHY_TIMEOUT)
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"HTTP {resp.status_code}")
    body = resp.json()
    if not isinstance(body, list):
        raise ValueError("not a list")
    return summarize(body, app, row.get("profile"), row.get("sample") if app == "sonarr" else None)


def ask(app: str, arr_id: int, row: dict) -> str:
    """Run (or reuse, under TTL) the interactive search for a listed row -> "ok" or an ASK_FAIL code."""
    if peek(app, arr_id):
        return "ok"
    if mr._arr_creds(app) is None:
        return "unset"
    if app == "sonarr" and not isinstance(row.get("episode_id"), int):
        return "noepisode"
    try:
        res = media_item.once(("why", app, arr_id), lambda: _search(app, arr_id, row))
    except Exception as exc:
        why = media_text.why(exc)
        log.warning("%s interactive search failed: %s", app, why)
        return "refused" if _status(why) else "unreachable"
    with _lock:
        _memo[(app, arr_id)] = {"at": _clock(), "res": res}
    return "ok"


def grab(app: str, arr_id: int, pick: int | None) -> tuple[str, int | None]:
    """Send the kept answer's release `pick` to the app -> (GRAB code, HTTP status or None)."""
    m = peek(app, arr_id)
    cands = m["res"]["candidates"] if m else []
    if pick is None or not 0 <= pick < len(cands) or not cands[pick].get("guid"):
        return "expired", None
    creds = mr._arr_creds(app)
    if creds is None:
        return "unset", None
    base, headers = creds
    c = cands[pick]
    try:
        resp = upstream.session("arr").post(f"{base}/api/v3/release", json={"guid": c["guid"], "indexerId": c["indexer_id"]},
                                            headers=headers, timeout=GRAB_TIMEOUT)
    except Exception as exc:
        log.warning("%s grab failed: %s", app, media_text.why(exc))
        return "unreachable", None
    if 200 <= resp.status_code < 300:
        return "sent", None
    log.warning("%s grab failed: HTTP %s", app, resp.status_code)
    if resp.status_code == 404:   # the app's own release cache (~30 min) dropped it: the next Why? searches afresh
        with _lock:
            _memo.pop((app, arr_id), None)
    return ("gone" if resp.status_code == 404 else "refused"), resp.status_code


# ---- drawing ----

def _int(v) -> int | None:
    s = str(v if v is not None else "")
    return int(s) if s.isdigit() and len(s) <= 9 else None


def ctx(app: str, arr_id: int, step: str = "", pick=None, flash: tuple | None = None) -> dict:
    """What `_upgrade_why.html` draws for one row. step: idle (the Why? link) | confirm (the ask, or the kept answer) |
    result | grab (the kept answer with release `pick`'s confirm). Never a call."""
    m = peek(app, arr_id) if step in ("confirm", "result", "grab") else None
    res = m["res"] if m else None
    pick = _int(pick) if step == "grab" and res else None
    if pick is not None and pick >= len(res["candidates"]):
        pick = None
    ago = None
    if m:
        mins = int((_clock() - m["at"]) // 60)
        ago = "searched just now" if mins < 1 else f"searched {mins} min ago"
    return {"app": app, "app_name": NAMES[app], "arr_id": arr_id, "key": f"{app}:{arr_id}", "dom": f"why-{app}-{arr_id}",
            "url": f"/media/upgrades/why/{app}/{arr_id}", "back": BACK, "res": res, "ago": ago,
            "ask": step == "confirm" and res is None, "pick": pick, "unknown_word": UNKNOWN[app],
            "flash": flash or (None, None)}


def ask_flash(app: str, code: str) -> tuple:
    return None, ASK_FAIL.get(code, ASK_FAIL["unreachable"]).format(app=NAMES[app])


def grab_flash(app: str, code: str, status: int | None = None) -> tuple:
    word, good = GRAB.get(code, GRAB["unreachable"])
    word = word.format(app=NAMES[app]) + (f" (HTTP {status})" if code == "refused" and status else "")
    return (word, None) if good else (None, word)


def page_ctx(params, rows) -> dict:
    """Downloads: {"sonarr:15": ctx} for every Upgrades row - idle, except the row named by `?why=<app>:<id>` (the no-JS
    path), drawn at `?why_step=` with its flash (`wf` / `grab` + `gcode`)."""
    named = str(params.get("why") or "")
    out = {}
    for r in rows or []:
        app = "radarr" if r.get("kind") == "movie" else "sonarr"
        arr_id = r.get("arr_id")
        if not isinstance(arr_id, int) or isinstance(arr_id, bool):
            continue
        key = f"{app}:{arr_id}"
        if key != named:
            out[key] = ctx(app, arr_id)
            continue
        step = params.get("why_step") or "result"
        flash = None
        if params.get("wf") in ASK_FAIL:
            flash = ask_flash(app, params["wf"])
        elif params.get("grab") in GRAB:
            flash = grab_flash(app, params["grab"], _int(params.get("gcode")))
        out[key] = ctx(app, arr_id, step if step in ("confirm", "grab", "result") else "result", params.get("pick"), flash)
    return out


def _target(request: Request, app: str, arr_id: int) -> dict:
    """The listed row, or 404 (an unknown app, id or a row no longer on the list)."""
    row = row_of(shell.get_snapshots(request=request), app, arr_id) if app in NAMES and arr_id > 0 else None
    if row is None:
        raise HTTPException(404, "Not on the upgrade list")
    return row


def _page(app: str, arr_id: int, **q) -> str:
    return f"{BACK}?" + urlencode({"why": f"{app}:{arr_id}", **q}) + f"#why-{app}-{arr_id}"


@router.get("/media/upgrades/why/{app}/{arr_id}", response_class=HTMLResponse)
def why_step(request: Request, app: str, arr_id: int, step: str = "", pick: str = ""):
    """htmx: one row's Why? area at `step`. Without htmx: the Downloads page, which draws the same from `?why=`."""
    _target(request, app, arr_id)
    if not is_htmx(request):
        return RedirectResponse(_page(app, arr_id, why_step=step or "result", **({"pick": pick} if pick else {})),
                                status_code=303)
    return md._partial(request, "_upgrade_why.html", w=ctx(app, arr_id, step, pick))


@router.post("/media/upgrades/why/{app}/{arr_id}", dependencies=[Depends(same_origin)])
async def why_now(request: Request, app: str, arr_id: int):
    row = _target(request, app, arr_id)
    code = await run_in_threadpool(ask, app, arr_id, row)   # 10-60 s: off the event loop
    if is_htmx(request):
        w = ctx(app, arr_id, "result") if code == "ok" else ctx(app, arr_id, flash=ask_flash(app, code))
        return md._partial(request, "_upgrade_why.html", w=w)
    return RedirectResponse(_page(app, arr_id, **({} if code == "ok" else {"wf": code})), status_code=303)


@router.post("/media/upgrades/why/{app}/{arr_id}/grab", dependencies=[Depends(same_origin)])
async def grab_now(request: Request, app: str, arr_id: int):
    _target(request, app, arr_id)
    form = await form_of(request)
    code, status = await run_in_threadpool(grab, app, arr_id, _int(form.get("pick")))
    if is_htmx(request):
        return md._partial(request, "_upgrade_why.html", w=ctx(app, arr_id, "result", flash=grab_flash(app, code, status)))
    return RedirectResponse(_page(app, arr_id, grab=code, **({"gcode": status} if status else {})), status_code=303)
