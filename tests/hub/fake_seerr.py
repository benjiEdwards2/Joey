"""A fake Seerr 3.5.0 for the guest request tests (Joey TV WP-B4, 2026-10-21).

Every user and request body is built from the REAL, redacted response shapes captured by the W3 probe on 2026-10-21
(tests/hub/fixtures/seerr_{status,import,request,decline}.json): the fake swaps in its own invented users and ids, so a
drift in Seerr's shapes shows up here. What the probe proved, and the fake enforces:

* `POST /api/v1/user/import-from-jellyfin` body `{"jellyfinUserIds": [...]}` -> 201 with ONLY the newly created users
  (an already imported id -> 201 `[]`); new users get permissions 32 (REQUEST only).
* `GET /api/v1/user?take=500` -> `{"pageInfo": ..., "results": [user, ...]}`, each with `jellyfinUserId`.
* `POST /api/v1/request` with the admin `X-Api-Key` plus `X-Api-User: <seerr id>` is created AS that user: status 1
  (pending) for a REQUEST-only user, 2 (approved) for one that may auto-approve; without `X-Api-User` it is the admin's.
* `POST /api/v1/request/{id}/decline` needs MANAGE_REQUESTS (16) or ADMIN (2): status 3.

Not probed live (WP-B5 BG6 is the first live use): `GET /api/v1/request?requestedBy=<id>` - modelled on the
Overseerr API (`{"pageInfo", "results": [MediaRequest]}`, the same MediaRequest shape as the POST answer).

Installed on top of tests/hub/fake_jellyfin.FakeJellyfin: Seerr URLs are answered here, anything else goes to the
`requests` function that was installed before (the Jellyfin fake, which refuses every other host). Names are invented.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "http://seerr.test:5055"
KEY = "seerr-key-SECRET-0002"
ADMIN_SEERR = 1

ADMIN, MANAGE_REQUESTS, REQUEST, AUTO_APPROVE = 2, 16, 32, 128
AUTO_APPROVE_MOVIE, AUTO_APPROVE_TV = 256, 512


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"seerr_{name}.json").read_text(encoding="utf-8"))


class Resp:
    def __init__(self, body=None, status=200):
        self.status_code = status
        self._body = body
        self.ok = 200 <= status < 300

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def res(tmdb: int, title: str, kind: str = "movie", status: int | None = None, year: str = "2024", **extra) -> dict:
    """A discover / search result (TMDB shape through Seerr)."""
    r = {"id": tmdb, "mediaType": kind, "posterPath": f"/p{tmdb}.jpg", "backdropPath": f"/b{tmdb}.jpg",
         "overview": f"Overview of {title}.", **extra}
    r["title" if kind == "movie" else "name"] = title
    r["releaseDate" if kind == "movie" else "firstAirDate"] = f"{year}-01-01"
    if status is not None:
        r["mediaInfo"] = {"status": status}
    return r


class FakeSeerr:
    def __init__(self):
        user0 = fixture("import")["body"][0]
        self._user_shape = copy.deepcopy(user0)
        self.users: dict[int, dict] = {}            # seerr id -> user body
        self.next_user = 2
        self.add_user(ADMIN_SEERR, "a" * 32, ADMIN, "Sample Admin")
        self.requests: list[dict] = []              # created MediaRequest bodies
        self.next_request = 129
        self.calls: list[tuple] = []                # (method, path, query, json, headers)
        self.users_status: int | None = None        # force GET /api/v1/user to answer this status
        self.users_raises: type[Exception] | None = None
        self.import_creates = True                  # False: the import answers 201 [] and creates nobody
        self.import_status = 201
        self.request_status: int | None = None      # force POST /api/v1/request to answer this status
        self.titles: dict[tuple[str, int], dict] = {}
        self.shelves: dict[str, list] = {}
        self.search: list = []

    # ---- test helpers ----
    def add_user(self, sid: int, jf_id: str, permissions: int = REQUEST, name: str = "Sample Friend") -> dict:
        body = copy.deepcopy(self._user_shape)
        body.update(id=sid, jellyfinUserId=jf_id, permissions=permissions, jellyfinUsername=name, displayName=name,
                    email=f"{name.split()[0].lower()}@example.test", avatar="/avatar.png")
        self.users[sid] = body
        self.next_user = max(self.next_user, sid + 1)
        return body

    def user_for(self, jf_id: str) -> dict | None:
        return next((u for u in self.users.values()
                     if str(u["jellyfinUserId"]).replace("-", "").lower() == jf_id.replace("-", "").lower()), None)

    def count(self, method: str, path: str) -> int:
        return sum(1 for c in self.calls if c[0] == method and c[1] == path)

    def posts_to(self, path: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == "POST" and c[1] == path]

    def decline(self, rid: int) -> dict:
        """B. declining in Seerr's own UI (the admin): status 3 - the media status is left as Seerr's answer left it."""
        req = next(r for r in self.requests if r["id"] == rid)
        req["status"] = 3
        return req

    def install(self, monkeypatch) -> "FakeSeerr":
        prev_get, prev_post = requests.get, requests.post
        monkeypatch.setenv("JELLYSEERR_URL", URL)
        monkeypatch.setenv("JELLYSEERR_API_KEY", KEY)

        def get(url, *a, **kw):
            return self.get(url, **kw) if str(url).startswith(URL) else prev_get(url, *a, **kw)

        def post(url, *a, **kw):
            return self.post(url, **kw) if str(url).startswith(URL) else prev_post(url, *a, **kw)
        monkeypatch.setattr(requests, "get", get)
        monkeypatch.setattr(requests, "post", post)
        return self

    # ---- shapes from the fixtures ----
    def _request_body(self, rid: int, kind: str, tmdb: int, status: int, user: dict, seasons) -> dict:
        body = copy.deepcopy(fixture("request")["body"])
        body.update(id=rid, type=kind, status=status, requestedBy=copy.deepcopy(user))
        body["media"].update(tmdbId=tmdb, mediaType=kind, id=rid - 1)
        if kind == "tv":
            body["seasons"] = [{"seasonNumber": n} for n in (seasons if isinstance(seasons, list) else [1])]
        return body

    # ---- the API ----
    def _record(self, method, url, headers, json_body=None):
        parts = urlsplit(url)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        self.calls.append((method, parts.path, query, json_body, dict(headers or {})))
        return parts.path, query

    def get(self, url, headers=None, timeout=None, **kw):
        assert timeout, "every Seerr call carries a timeout"
        path, query = self._record("GET", url, headers)
        if (headers or {}).get("X-Api-Key") != KEY:
            return Resp({"message": "Unauthorized"}, 401)
        assert "X-Api-User" not in (headers or {}), "reads are made as the admin key alone"
        if path == "/api/v1/status":
            return Resp(fixture("status")["body"])
        if path == "/api/v1/user":
            if self.users_raises:
                raise self.users_raises(f"Read timed out: {url}")
            if self.users_status:
                return Resp({}, self.users_status)
            take = int(query.get("take", 10))
            rows = list(self.users.values())[:take]
            return Resp({"pageInfo": {"pages": 1, "pageSize": take, "results": len(self.users), "page": 1},
                         "results": copy.deepcopy(rows)})
        if path == "/api/v1/request":
            by = query.get("requestedBy")
            rows = [r for r in reversed(self.requests) if by is None or str(r["requestedBy"]["id"]) == by]
            return Resp({"pageInfo": {"pages": 1, "pageSize": 100, "results": len(rows), "page": 1},
                         "results": copy.deepcopy(rows)})
        if path.startswith("/api/v1/search"):
            return Resp({"page": 1, "totalPages": 1, "totalResults": len(self.search), "results": self.search})
        if path in self.shelves:
            return Resp({"page": 1, "totalPages": 1, "results": copy.deepcopy(self.shelves[path])})
        if path.startswith("/api/v1/watchproviders/"):
            return Resp([])
        bits = path.split("/")
        if len(bits) == 5 and bits[3] in ("movie", "tv") and bits[4].isdigit():
            body = self.titles.get((bits[3], int(bits[4])))
            return Resp(copy.deepcopy(body)) if body else Resp({}, 404)
        return Resp({}, 404)

    def post(self, url, json=None, data=None, headers=None, timeout=None, **kw):
        assert timeout, "every Seerr call carries a timeout"
        path, query = self._record("POST", url, headers, json)
        headers = headers or {}
        if headers.get("X-Api-Key") != KEY:
            return Resp({"message": "Unauthorized"}, 401)
        acting = self.users.get(int(headers["X-Api-User"])) if "X-Api-User" in headers else self.users[ADMIN_SEERR]
        if acting is None:
            return Resp({"message": "User not found"}, 403)
        if path == "/api/v1/user/import-from-jellyfin":
            assert "X-Api-User" not in headers
            ids = (json or {}).get("jellyfinUserIds")
            assert isinstance(ids, list) and ids, json
            if self.import_status != 201:
                return Resp({"message": "error"}, self.import_status)
            created = []
            for jf in ids:
                if self.import_creates and self.user_for(jf) is None:
                    created.append(self.add_user(self.next_user, jf, REQUEST, "Imported Friend"))
            return Resp(copy.deepcopy(created), 201)
        if path == "/api/v1/request":
            if self.request_status:
                return Resp({"message": "refused"}, self.request_status)
            kind, tmdb = (json or {}).get("mediaType"), (json or {}).get("mediaId")
            assert kind in ("movie", "tv") and isinstance(tmdb, int), json
            if any(r["media"]["tmdbId"] == tmdb and r["type"] == kind and r["status"] in (1, 2) for r in self.requests):
                return Resp({"message": "Request for this media already exists."}, 409)
            perms = acting["permissions"]
            auto = perms & (ADMIN | AUTO_APPROVE | (AUTO_APPROVE_MOVIE if kind == "movie" else AUTO_APPROVE_TV))
            body = self._request_body(self.next_request, kind, tmdb, 2 if auto else 1, acting, json.get("seasons"))
            self.next_request += 1
            self.requests.append(body)
            title = self.titles.get((kind, tmdb))
            if title is not None:
                title.setdefault("mediaInfo", {})["status"] = 2
            return Resp(copy.deepcopy(body), 201)
        if path.startswith("/api/v1/request/") and path.endswith("/decline"):
            if not acting["permissions"] & (ADMIN | MANAGE_REQUESTS):
                return Resp({"message": "You do not have permission to modify this request."}, 403)
            rid = int(path.split("/")[4])
            body = copy.deepcopy(fixture("decline")["body"])
            body.update(self.decline(rid))
            return Resp(body, 200)
        return Resp({}, 404)
