"""JY-260 phase 1: the private poster review page (spec docs/specs/JY-260-posters.md).

* GET /media/posters - every rendered title, original (the Jellyfin Primary through /img) beside the proposed Joey
  poster, Q9A order, with the pick in words and the template kit's state (its problems, in words, when refused).
* GET /media/posters/img/{jf_id} - the proposed JPEG from the dry cache.

Household only: the private front (owner "you" or "her"). The media front - friends - and everything while
POSTERS=off get the ordinary 404 page; hub.guest classifies both routes PRIVATE. Rendering reads local files only
(hub/media_posters.py writes them in the background loop), so the page makes no network call.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from hub import guest, media_posters as mp, media_text
from hub.ids import JELLYFIN_SNAPSHOT_ID

router = APIRouter()

PAGE = "/media/posters"
MODE_WORDS = {"dry": "Dry run: nothing is written to Jellyfin",
              "on": "On is phase 2 (not built): dry run, nothing is written to Jellyfin"}


def allowed() -> bool:
    return not guest.is_media() and not mp.disabled()


def pick_words(side: dict) -> str:
    if side.get("status") == "no_source":
        return "No TMDB poster"
    p = side.get("pick") or {}
    lang = {None: "Text-less", "en": "English poster"}.get(p.get("fallback"), "Other-language poster")
    parts = [lang, media_text.plural(int(p.get("votes") or 0), "vote")]
    if p.get("width") and p.get("height"):
        parts.append(f"{p['width']} × {p['height']}")
    return " · ".join(parts)


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
                         "kind_word": "Series" if side.get("kind") == "tv" else "Film"})
        rendered = sum(1 for r in rows if r.get("status") == "rendered")
        head = [MODE_WORDS[mp.mode()], media_text.plural(rendered, "poster") + " rendered"]
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
