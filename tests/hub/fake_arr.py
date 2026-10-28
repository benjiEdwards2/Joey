"""A fake Radarr + Sonarr for the Remove tests (JY-265, 2026-10-28).

Every body is built from the redacted response shapes in tests/hub/fixtures/arr_*.json (phase 0): the movie list,
the series list with `seasons[].statistics`, the episode-file list and `config/mediamanagement` (recycleBin,
recycleBinCleanupDays: the only values read live, by scripts/check_recycle_bin.py). The fake swaps in its own
invented ids, so a drift in the shapes shows up here. It counts every call, so a test can prove a page made none, and
it records every write (PUT / DELETE / POST) so a test can prove phase 1 never deletes anything in the arr apps.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"arr_{name}.json").read_text(encoding="utf-8"))


class Resp:
    def __init__(self, body=None, status=200):
        self.status_code = status
        self._body = body
        self.ok = 200 <= status < 300

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeArr:
    def __init__(self):
        self.movies = copy.deepcopy(fixture("radarr_movie")["body"])
        self.series = copy.deepcopy(fixture("sonarr_series")["body"])
        self.episode_files = copy.deepcopy(fixture("sonarr_episodefile")["body"])
        self.config = {RADARR: copy.deepcopy(fixture("radarr_mediamanagement")["body"]),
                       SONARR: copy.deepcopy(fixture("sonarr_mediamanagement")["body"])}
        self.calls: list[tuple] = []           # (method, base, path, params, json)
        self.raise_on: type[Exception] | None = None
        self.put_status = 202

    @staticmethod
    def handles(url: str) -> bool:
        return str(url).startswith((RADARR, SONARR))

    def env(self) -> dict:
        return {"RADARR_URL": RADARR, "RADARR_API_KEY": RKEY, "SONARR_URL": SONARR, "SONARR_API_KEY": TKEY}

    def _base(self, url, headers):
        base = RADARR if url.startswith(RADARR) else SONARR
        assert headers == {"X-Api-Key": RKEY if base == RADARR else TKEY}
        return base

    def _rec(self, method, url, headers, params=None, json_body=None):
        base = self._base(url, headers)
        path = urlsplit(url).path
        self.calls.append((method, base, path, params, json_body))
        if self.raise_on:
            raise self.raise_on(f"Max retries exceeded with url: {url}?apikey={RKEY}")
        return base, path

    def writes(self) -> list[tuple]:
        return [c for c in self.calls if c[0] != "GET"]

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert timeout, "every arr call carries a timeout"
        base, path = self._rec("GET", url, headers, params)
        params = params or {}
        if path == "/api/v3/config/mediamanagement":
            return Resp(copy.deepcopy(self.config[base]))
        if base == RADARR and path == "/api/v3/movie":
            return Resp([copy.deepcopy(m) for m in self.movies
                         if "tmdbId" not in params or m["tmdbId"] == params["tmdbId"]])
        if base == SONARR and path == "/api/v3/series":
            return Resp([copy.deepcopy(s) for s in self.series
                         if "tvdbId" not in params or s["tvdbId"] == params["tvdbId"]])
        if base == SONARR and path == "/api/v3/episodefile":
            return Resp([copy.deepcopy(f) for f in self.episode_files if f["seriesId"] == params.get("seriesId")])
        return Resp({}, 404)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert timeout
        base, path = self._rec("PUT", url, headers, json_body=json)
        rows = self.movies if base == RADARR else self.series
        for i, e in enumerate(rows):
            if path.endswith(f"/{e['id']}"):
                rows[i] = copy.deepcopy(json)
        return Resp(json, self.put_status)

    def delete(self, url, headers=None, timeout=None, params=None, **kw):
        assert timeout
        self._rec("DELETE", url, headers, params)
        return Resp(None, 200)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        assert timeout
        self._rec("POST", url, headers, json_body=json)
        return Resp({"id": 1}, 201)
