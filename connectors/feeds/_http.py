"""The one HTTP helper every live feed fetch goes through (C-05).

`http_json` makes one call, checks the status and returns the parsed body. Any failure
raises `RuntimeError(f"{label} failed ({reason})")` — `reason(exc)` is the type or HTTP status
ONLY, because requests' exception text embeds the URL (host, query, sometimes a token) and
this string ends up in envelopes, `_runner.json` and the log (C-06).

A connector's `fetch()` opens one `session()` per run and passes it to every call, so its
N calls to one service reuse one connection instead of opening N (C-18).
"""

from __future__ import annotations

from typing import Any


def failure(label: str, why: str) -> RuntimeError:
    """`RuntimeError(f"{label} failed ({why})")` carrying `.reason` = `why`, for callers that
    collect per-source reasons (gcal's feed_errors, arr's app_errors). A plain RuntimeError
    so envelope errors keep reading "RuntimeError: Jellyfin users failed (HTTP 401)"."""
    err = RuntimeError(f"{label} failed ({why})")
    err.reason = why
    return err


def reason(exc: Exception) -> str:
    """Why a call failed, in words — never the URL or key a requests error embeds."""
    import requests

    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status:
        return f"HTTP {status}"
    if isinstance(exc, requests.Timeout):  # before ConnectionError: ConnectTimeout is both
        return "timeout"
    if isinstance(exc, requests.ConnectionError):
        return "connection refused"
    return type(exc).__name__


def session():
    """A fresh `requests.Session` for one connector run; the caller closes it."""
    import requests

    return requests.Session()


def http_json(label: str, url: str, *, headers: dict | None = None, auth: Any = None,
              params: dict | None = None, timeout: float = 10, session: Any = None,
              method: str = "GET", data: Any = None, text: bool = False) -> Any:
    """One call: the JSON body (or `.text` with `text=True`). Only the
    keyword arguments given are passed on; without `session` it is a one-off call.
    Raises `failure(label, reason(exc))` from None — never the requests exception itself."""
    import requests

    client = session if session is not None else requests
    extra = {k: v for k, v in (("headers", headers), ("auth", auth), ("params", params), ("data", data))
             if v is not None}
    try:
        response = getattr(client, method.lower())(url, timeout=timeout, **extra)
        response.raise_for_status()
        return response.text if text else response.json()
    except Exception as exc:
        raise failure(label, reason(exc)) from None
