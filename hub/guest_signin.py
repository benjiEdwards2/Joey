"""Sign-in and sign-out on the media front (Joey TV WP-B2, 2026-10-21). The Jellyfin calls, cookies and counters live
in hub.guest_auth; this module is the five routes (hub.guest.SIGNIN, all PUBLIC) and their two templates.

* GET  /signin            the page: a Quick Connect code (started on load by htmx) and the password form (fallback).
* POST /signin/qc/start   a new code: Jellyfin /QuickConnect/Initiate; the secret goes into `__Host-jm_qc` (10 min),
                          never into the page.
* GET  /signin/qc/poll    htmx every 3 s: waiting / expired / refused, or - once the phone approved the code - the
                          session cookie and `HX-Redirect` to where the guest was going.
* POST /signin/password   username + password (Jellyfin /Users/AuthenticateByName); a refusal of any kind reads
                          "Wrong username or password" after WRONG_DELAY_S; 5 failures per username in 15 min are
                          refused without calling Jellyfin (Q28).
* POST /signout           Jellyfin /Sessions/Logout with the token (best effort), the verdict evicted, then (JY-190,
                          L4) the cookie cleared, 303 /signin, and AFTER the response a friend's own Jellyfin
                          device deleted with the admin key (best effort, guest_auth.remove_device, a BackgroundTask).

The TV signs in on this same page (Q33: the shell has no native sign-in screen); WP-B3 adds the 10-foot TV styling.
Every POST passes hub.media_write.same_origin. On the private front every route is the ordinary 404.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from hub import guest, guest_auth, shell
from hub.guest_auth import DEV, QC, SESSION, Unreachable
from hub.media_write import form_of, safe_back, same_origin

log = logging.getLogger("hub.guest_signin")
router = APIRouter()

WRONG = "Wrong username or password"
UNREACHABLE = "Couldn't reach Jellyfin. Try again in a minute."
MISSING = "Enter your username and password"
QC_DOWN = "Quick Connect isn't available right now. Use your username and password instead."


def _next(value) -> str:
    """Where to go after signing in: a local guest page (hub.guest.allows), else the guest home."""
    home = guest.home_path() or "/"
    target = safe_back(value, home, keep_query=True)
    return target if guest.allows("GET", target.partition("?")[0]) else home


def _code_words(code: str) -> str:
    return f"{code[:3]} {code[3:]}" if len(code) == 6 and code.isdigit() else code


def _device(request: Request) -> tuple[str, str | None]:
    """(this browser's Jellyfin DeviceId, a new one to set as `__Host-jm_dev` or None when it already has one)."""
    have = guest_auth.cookies_of(request.headers).get(guest_auth.cookie_name(DEV)) or ""
    if guest_auth.DEV_RE.match(have):
        return have, None
    new = guest_auth.new_device_id()
    return new, new


def _page(request: Request, *, next_path: str, error: str | None = None, code: str | None = None,
          qc_error: str | None = None, status: int = 200, new_device: str | None = None) -> HTMLResponse:
    resp = shell.templates.TemplateResponse(request, "guest_signin.html", {
        "next_path": next_path, "error": error, "code": code, "qc_error": qc_error,
        "poll_url": _poll_url(next_path),
    }, status_code=status)
    if new_device:
        resp.headers.append("set-cookie", guest_auth.set_cookie_header(DEV, new_device, guest_auth.DEV_MAX_AGE))
    return resp


def _poll_url(next_path: str) -> str:
    return "/signin/qc/poll?next=" + quote(next_path, safe="")


def _status(request: Request, state: str, next_path: str, status: int = 200) -> HTMLResponse:
    """The Quick Connect status line (htmx swaps it every 3 s while `state` is waiting / trying)."""
    return shell.templates.TemplateResponse(request, "_guest_qc_status.html", {
        "state": state, "poll_url": _poll_url(next_path), "next_path": next_path}, status_code=status)


def _not_found(request: Request):
    return shell.not_found_page(request)


@router.get("/signin", response_class=HTMLResponse)
def signin_page(request: Request, next: str = ""):
    if not guest.is_media():
        return _not_found(request)
    _, new_device = _device(request)
    return _page(request, next_path=_next(next), new_device=new_device)


@router.post("/signin/qc/start", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def qc_start(request: Request):
    if not guest.is_media():
        return _not_found(request)
    form = await form_of(request)
    next_path = _next(form.get("next"))
    device, new_device = _device(request)
    try:
        secret, code = await run_in_threadpool(guest_auth.qc_initiate, device, guest_auth.is_tv(request.headers))
    except Unreachable as exc:
        log.warning("guest: quick connect unavailable (%s)", exc)
        return _qc_panel(request, next_path, None, QC_DOWN, new_device)
    resp = _qc_panel(request, next_path, _code_words(code), None, new_device)
    resp.headers.append("set-cookie", guest_auth.set_cookie_header(QC, secret, guest_auth.QC_MAX_AGE))
    return resp


def _qc_panel(request: Request, next_path: str, code: str | None, qc_error: str | None, new_device: str | None):
    if request.headers.get("hx-request") == "true":
        resp = shell.templates.TemplateResponse(request, "_guest_qc.html", {
            "code": code, "qc_error": qc_error, "poll_url": _poll_url(next_path), "next_path": next_path})
        if new_device:
            resp.headers.append("set-cookie", guest_auth.set_cookie_header(DEV, new_device, guest_auth.DEV_MAX_AGE))
        return resp
    return _page(request, next_path=next_path, code=code, qc_error=qc_error, new_device=new_device)


@router.get("/signin/qc/poll", response_class=HTMLResponse)
def qc_poll(request: Request, next: str = ""):
    if not guest.is_media():
        return _not_found(request)
    next_path = _next(next)
    cookies = guest_auth.cookies_of(request.headers)
    secret = cookies.get(guest_auth.cookie_name(QC)) or ""
    if not guest_auth.SECRET_RE.match(secret):
        return _status(request, "none", next_path)
    device, tv = guest_auth.device_of(cookies), guest_auth.is_tv(request.headers)
    try:
        approved = guest_auth.qc_state(secret, device, tv)
        out = guest_auth.qc_signin(secret, device, tv) if approved else None
    except Unreachable as exc:
        log.warning("guest: quick connect poll unreachable (%s)", exc)
        return _status(request, "trying", next_path)
    if approved is False:
        return _status(request, "waiting", next_path)
    if out is None:   # expired, or approved by a user who may not hold a guest session (logged in guest_auth)
        resp = _status(request, "expired" if approved is None else "refused", next_path)
    else:
        token, _ = out
        if request.headers.get("hx-request") == "true":
            resp = HTMLResponse("", headers={"HX-Redirect": next_path})
        else:
            resp = RedirectResponse(next_path, status_code=303)
        resp.headers.append("set-cookie", guest_auth.set_cookie_header(SESSION, token, guest_auth.SESSION_MAX_AGE))
    resp.headers.append("set-cookie", guest_auth.clear_cookie_header(QC))
    return resp


@router.post("/signin/password", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def password_signin(request: Request):
    if not guest.is_media():
        return _not_found(request)
    form = await form_of(request)
    next_path = _next(form.get("next"))
    username, password = (form.get("username") or "").strip()[:128], (form.get("password") or "")[:256]
    device, new_device = _device(request)
    if not username or not password:
        return _page(request, next_path=next_path, error=MISSING, new_device=new_device)
    try:
        out = await run_in_threadpool(guest_auth.password_signin, username, password, device,
                                      guest_auth.is_tv(request.headers))
    except Unreachable as exc:
        log.warning("guest: password sign-in unreachable (%s)", exc)
        return _page(request, next_path=next_path, error=UNREACHABLE, status=503, new_device=new_device)
    if out == "wrong":
        await run_in_threadpool(guest_auth.sleep, guest_auth.WRONG_DELAY_S)
        return _page(request, next_path=next_path, error=WRONG, new_device=new_device)
    token, _ = out
    resp = RedirectResponse(next_path, status_code=303)
    if new_device:
        resp.headers.append("set-cookie", guest_auth.set_cookie_header(DEV, new_device, guest_auth.DEV_MAX_AGE))
    resp.headers.append("set-cookie", guest_auth.set_cookie_header(SESSION, token, guest_auth.SESSION_MAX_AGE))
    return resp


def _whose(token: str, device: str, tv: bool):
    """The signing-out session's identity (the cached verdict, else /Users/Me), or None when Jellyfin cannot say."""
    try:
        return guest_auth.validate(token, device, tv, guest_auth.SIGNOUT_WHO_TIMEOUT)
    except Unreachable as exc:
        log.warning("guest: sign-out identity unknown (%s)", exc)
        return None


@router.post("/signout", dependencies=[Depends(same_origin)])
async def signout(request: Request):
    if not guest.is_media():
        return _not_found(request)
    cookies = guest_auth.cookies_of(request.headers)
    token = cookies.get(guest_auth.cookie_name(SESSION)) or ""
    after = None
    if guest_auth.TOKEN_RE.match(token):
        device, tv = guest_auth.device_of(cookies), guest_auth.is_tv(request.headers)
        ident = await run_in_threadpool(_whose, token, device, tv)   # before the logout: the token still answers
        await run_in_threadpool(guest_auth.logout, token, device, tv)
        guest_auth.forget(token)   # after the logout: a request racing it cannot re-cache a valid verdict
        log.info("guest: signed out")
        if ident is not None:   # after the 303 is sent: a slow Jellyfin never holds the sign-out up (JY-190 review)
            after = BackgroundTask(guest_auth.remove_device, device, ident)
    resp = RedirectResponse("/signin", status_code=303, background=after)
    resp.headers.append("set-cookie", guest_auth.clear_cookie_header(SESSION))
    return resp
