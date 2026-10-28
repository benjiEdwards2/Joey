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
    if side.get("reverted"):
        parts.append("Reverted: the original is shown")
    elif not side.get("auto"):
        parts.append("Held back: under the rating floor")
    elif side.get("live"):
        parts.append("In Jellyfin")
    return " · ".join(parts)


def mode_words() -> str:
    from hub import media_posters_write as write
    if mp.mode() == "on" and write.creds() is None:
        return NO_KEY_WORDS
    return MODE_WORDS[mp.mode()]


@router.get(PAGE, response_class=HTMLResponse)
def posters_page(request: Request):
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
        return {"rows": rows, "head_line": " · ".join(head), "problems": problems,
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
        write.revert(jf_id)
    else:
        write.restore(jf_id)
    return RedirectResponse(PAGE, status_code=303)


@router.post(PAGE + "/{jf_id}/revert", dependencies=[Depends(same_origin)])
async def revert(request: Request, jf_id: str):
    return await run_in_threadpool(_act, request, jf_id, "revert")


@router.post(PAGE + "/{jf_id}/restore", dependencies=[Depends(same_origin)])
async def restore(request: Request, jf_id: str):
    return await run_in_threadpool(_act, request, jf_id, "restore")
