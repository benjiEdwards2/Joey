"""JY-260: the private poster review page (spec docs/specs/JY-260-posters.md).

* GET /media/posters - every rendered title, original (the Jellyfin Primary through /img) beside the proposed Joey
  poster, Q9A order, with the pick in words and the template kit's state (a refused kit: its problems in words, and the starter kit is used).
* GET /media/posters/img/{jf_id} - the stored master JPEG (hub/media_posters_store.py).
* POST /media/posters/{jf_id}/revert | /restore (phase 2) - the per-item spot-check lever: stop serving the Joey poster
  (and put Jellyfin's original back when Joey had written one), or serve it again. Same-origin guarded.

Household only: the private front (owner "you" or "her"). The media front - friends - and everything while
POSTERS=off get the ordinary 404 page; hub.guest classifies both routes PRIVATE. Rendering reads local files only
(hub/media_posters.py writes them in the background loop), so the page makes no network call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from hub import guest, media_item, media_posters as mp, media_text
from hub.media_write import same_origin
from hub.ids import JELLYFIN_SNAPSHOT_ID

router = APIRouter()

PAGE = "/media/posters"
KIND_WORDS = {"movie": "Film", "tv": "Series", "season": ""}   # a season: its sub-line says "Season 2"
MODE_WORDS = {"dry": "Joey posters are served from the local store; nothing is written to Jellyfin",
              "on": "Joey posters are served from the local store and written to Jellyfin"}
NO_KEY_WORDS = "On, but the Jellyfin poster key is not set: nothing is written to Jellyfin"


def allowed() -> bool:
    return not guest.is_media() and not mp.disabled()


def pick_words(side: dict) -> str:
    if side.get("status") == "no_source":
        return "No TMDB poster"
    p = side.get("pick") or {}
    lang = {None: "Text-less", "en": "English poster", "series": "Series poster"}.get(p.get("fallback"),
                                                                                       "Other-language poster")
    rating = p.get("rating")
    parts = [lang, f"Rated {rating:.1f}" if isinstance(rating, (int, float)) else "Unrated"]
    if p.get("width") and p.get("height"):
        parts.append(f"{p['width']} × {p['height']}")
    if side.get("backoff"):
        parts.append("Failed 3 times: retried after " + str(side["backoff"])[:16].replace("T", " ") + " UTC")
    if side.get("manual"):
        parts.append("Manual: changed by hand in Jellyfin, left alone")
    elif side.get("reverted") and side.get("wrote"):
        parts.append("Revert pending: Jellyfin still has the Joey poster until the restore is confirmed")
    elif side.get("reverted"):
        parts.append("Reverted: the original is shown")
    elif not side.get("auto"):
        parts.append("Held back: under the rating floor")
    elif side.get("live"):
        parts.append("In Jellyfin")
    return " · ".join(parts)


# what the last action did, shown once after the redirect (`?done=`; only these words, never the query text)
DONE_WORDS = {
    "reverted": "Reverted: Jellyfin has the original again (confirmed).",
    "queued": "Revert queued: Joey was writing this title; the next pass restores the original.",
    "pending": "Revert recorded: write-back is off or has no key, so Jellyfin still has the Joey poster.",
    "error": "Revert failed: Jellyfin did not take the original. It is retried on the next pass.",
    "manual": "Your hand-set poster stays in Jellyfin; Joey no longer serves its own.",
    "cleared": "Backoff cleared: the next pass tries again.",
    "reapplied": "The Joey poster is served again and written on the next pass.",
}


def mode_words() -> str:
    from hub import media_posters_write as write
    if mp.mode() == "on" and write.creds() is None:
        return NO_KEY_WORDS
    return MODE_WORDS[mp.mode()]


@router.get(PAGE, response_class=HTMLResponse)
def posters_page(request: Request, done: str = ""):
    from hub import media_pages, shell
    if not allowed():
        return shell.not_found_page(request)
    request.state.media_section = "server"

    def build(_data, _view):
        tpl, problems, starter = mp.template_state()
        rows = []
        for side in mp.rows():
            rows.append({**side, "words": pick_words(side), "stale": bool(tpl) and side.get("template") != tpl.version,
                         "kind_word": KIND_WORDS.get(side.get("kind"), "Film")})
        rendered = sum(1 for r in rows if r.get("status") == "rendered")
        head = [mode_words(), media_text.plural(rendered, "poster") + " rendered"]
        if len(rows) > rendered:
            head.append(f"{len(rows) - rendered} without a TMDB poster")
        shown = {r["jf_id"] for r in rows}
        stuck = [{"jf_id": b["jf_id"], "title": b.get("title") or "Untitled",
                  "kind_word": KIND_WORDS.get(b.get("kind"), "Film"),
                  "until": str(b.get("retry_at"))[:16].replace("T", " "), "error": b.get("last_error") or ""}
                 for b in mp.backing_off() if b["jf_id"] not in shown]
        return {"rows": rows, "stuck": stuck, "done_words": DONE_WORDS.get(done, ""), "head_line": " · ".join(head), "problems": problems,
                "kit_words": (("Starter template" if starter else "Your template") + (f" · {tpl.version}" if tpl else "")),
                "version": tpl.version if tpl else ""}

    return media_pages._detail_page(request, "media_posters.html", JELLYFIN_SNAPSHOT_ID, build, always_build=True)


@router.get(PAGE + "/img/{jf_id}")
def poster_image(request: Request, jf_id: str):
    from hub import shell
    path = mp.image_path(jf_id) if allowed() else None
    if path is None:
        return shell.not_found_page(request)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


def _act(request: Request, jf_id: str, action: str):
    from hub import media_posters_write as write, shell
    if not allowed() or not media_item.ITEM_RE.match(jf_id or "") or mp.state(jf_id) is None:
        return shell.not_found_page(request)
    if action == "revert":
        got = write.revert(jf_id)
    elif action == "original":
        got = write.revert(jf_id, restore_manual=True)
    elif action == "retry":
        got = write.retry(jf_id)
    else:   # reapply / restore: B.'s explicit "use the Joey poster"
        write.reapply(jf_id)
        got = "reapplied"
    return RedirectResponse(f"{PAGE}?done={got}" if got in DONE_WORDS else PAGE, status_code=303)


@router.post(PAGE + "/{jf_id}/revert", dependencies=[Depends(same_origin)])
async def revert(request: Request, jf_id: str):
    return await run_in_threadpool(_act, request, jf_id, "revert")


@router.post(PAGE + "/{jf_id}/restore", dependencies=[Depends(same_origin)])
async def restore(request: Request, jf_id: str):
    return await run_in_threadpool(_act, request, jf_id, "restore")


@router.post(PAGE + "/{jf_id}/original", dependencies=[Depends(same_origin)])
async def restore_original(request: Request, jf_id: str):
    """B.'s explicit ask: put the pre-Joey original back over a hand-set (manual) poster."""
    return await run_in_threadpool(_act, request, jf_id, "original")


@router.post(PAGE + "/{jf_id}/reapply", dependencies=[Depends(same_origin)])
async def reapply(request: Request, jf_id: str):
    """Re-apply the Joey poster (over a hand-set one, after a revert or a backoff)."""
    return await run_in_threadpool(_act, request, jf_id, "reapply")


@router.post(PAGE + "/{jf_id}/retry", dependencies=[Depends(same_origin)])
async def retry(request: Request, jf_id: str):
    """"Try again now" on a backed-off item: repeats what failed (a revert retries the revert), never a re-apply."""
    return await run_in_threadpool(_act, request, jf_id, "retry")
