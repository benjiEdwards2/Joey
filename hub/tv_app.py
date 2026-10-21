"""Joey TV WP-B8 step 6 (Q37 = public): the TV app's download and update endpoints on the guest front.

deploy.sh's tv_publish (deploy/tv_publish.py) fills TV_APP_DIR (joey-media: /data/tv-app, read-only) with
`version.json` and up to three `joey-media-<semver>-<versionCode>.apk` files. This module only serves that dir:

* GET /app               plain HTML (no JS): name, version, notes, one big Download link, Downloader steps;
                         "No build published yet" while the dir is empty.
* GET /app/version.json  the file as published, `Cache-Control: no-cache` (the app's daily update check).
* GET /app/latest.apk    302 to the versioned APK named in version.json, `no-store` (short Downloader URL).
* GET /app/<apk>         only an existing file matching APK_NAME_RE: `application/vnd.android.package-archive`,
                         `public, max-age=31536000, immutable` (the name carries the versionCode).
* anything else          the ordinary Joey 404, rendered for the neutral path (byte-identical, DECISIONS C).

Media front only: on the private front every /app path is the same 404 (the private hub has no tv-app mount).
On the media front hub/guest.py lists /app and /app/{rest:path} as GUEST + PUBLIC (no sign-in, Q37).
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.requests import Request as StarletteRequest

from hub import guest

router = APIRouter()

DEFAULT_DIR = "/data/tv-app"
APK_NAME_RE = re.compile(r"^joey-media-\d+\.\d+\.\d+-\d{10}\.apk$")
APK_TYPE = "application/vnd.android.package-archive"
IMMUTABLE = "public, max-age=31536000, immutable"


def app_dir() -> Path:
    return Path((os.environ.get("TV_APP_DIR") or "").strip() or DEFAULT_DIR)


def _not_found(request: Request):
    """The one Joey 404 page, rendered for guest.NOT_FOUND_PATH whatever was asked for (as GuestGate does)."""
    from hub import shell
    neutral = {**request.scope, "path": guest.NOT_FOUND_PATH, "raw_path": guest.NOT_FOUND_PATH.encode(),
               "query_string": b""}
    return shell.not_found_page(StarletteRequest(neutral, request.receive))


def _apk_path(name: str) -> Path | None:
    if not APK_NAME_RE.match(name):
        return None
    path = app_dir() / name
    return path if path.is_file() else None


def published() -> dict | None:
    """version.json as a dict when it is valid JSON naming an APK that exists, else None."""
    try:
        doc = json.loads((app_dir() / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("url"), str) or _apk_path(doc["url"]) is None:
        return None
    return doc


def _size(doc: dict) -> str:
    size = doc.get("size")
    return f"{size / 1_000_000:.1f} MB" if isinstance(size, int) and size > 0 else ""


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Joey Media for TV</title>
<style>
body {{ background: #0b0b0f; color: #ededf0; font: 20px/1.5 system-ui, sans-serif; margin: 0; padding: 48px; }}
main {{ max-width: 760px; margin: 0 auto; }}
h1 {{ font-size: 40px; margin: 0 0 8px; }}
.meta {{ color: #a1a1aa; margin: 0 0 24px; }}
.notes {{ white-space: pre-line; margin: 0 0 32px; }}
a.download {{ display: inline-block; background: #f5f5f7; color: #0b0b0f; font-size: 28px; font-weight: 600;
  padding: 20px 40px; border-radius: 14px; text-decoration: none; outline: 4px solid transparent; }}
a.download:focus, a.download:hover {{ outline-color: #7dd3fc; outline-offset: 4px; }}
code {{ background: #1c1c22; padding: 2px 8px; border-radius: 6px; }}
ol {{ padding-left: 28px; }}
</style>
</head>
<body>
<main>
<h1>Joey Media for TV</h1>
{body}
</main>
</body>
</html>
"""


def _page(request: Request) -> HTMLResponse:
    doc = published()
    if doc is None:
        body = '<p class="meta">No build published yet.</p>'
    else:
        name = doc["url"]
        latest = f"https://{guest.media_public_host()}/app/latest.apk"   # the public name, never the tunnel's http
        meta = " · ".join(x for x in (f"Version {doc.get('version', '?')} ({doc.get('versionCode', '?')})",
                                      _size(doc)) if x)
        body = (f'<p class="meta">{html.escape(meta)}</p>\n'
                f'<p class="notes">{html.escape(str(doc.get("notes", "")))}</p>\n'
                f'<p><a class="download" href="/app/{html.escape(name)}" autofocus>Download for Android TV</a></p>\n'
                "<h2>Install with the Downloader app</h2>\n<ol>\n"
                "<li>On the TV, install <strong>Downloader</strong> (by AFTVnews) from the app store.</li>\n"
                "<li>Allow it to install apps: Settings &rarr; Apps &rarr; Security &amp; restrictions &rarr; "
                "Unknown sources &rarr; Downloader (the wording differs by TV).</li>\n"
                f"<li>Open Downloader and type <code>{html.escape(latest)}</code>, then Go.</li>\n"
                "<li>Choose Install. Open <strong>Joey Media</strong> from the TV's apps row.</li>\n</ol>")
    return HTMLResponse(PAGE.format(body=body))


@router.api_route("/app", methods=["GET", "HEAD"])
def tv_app_page(request: Request):
    if not guest.is_media():
        return _not_found(request)
    return _page(request)


@router.api_route("/app/{rest:path}", methods=["GET", "HEAD"])   # HEAD: download managers probe first
def tv_app_file(request: Request, rest: str):
    if not guest.is_media():
        return _not_found(request)
    if rest == "version.json":
        try:
            data = (app_dir() / "version.json").read_bytes()
        except OSError:
            return _not_found(request)
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-cache"})
    if rest == "latest.apk":
        doc = published()
        if doc is None:
            return _not_found(request)
        return RedirectResponse(f"/app/{doc['url']}", status_code=302, headers={"Cache-Control": "no-store"})
    path = _apk_path(rest)
    if path is None:
        return _not_found(request)
    return FileResponse(path, media_type=APK_TYPE, filename=rest, headers={"Cache-Control": IMMUTABLE})
