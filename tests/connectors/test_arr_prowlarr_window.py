"""JY-143: Prowlarr `/api/v1/indexerstats` is cumulative without a window (verified live 2026-10-24: the default
answer equalled the 30-day one). The arr feed asks for the last ARR_WINDOW_DAYS only, so failed grabs age out."""

from datetime import datetime, timedelta, timezone

import requests

from connectors.feeds.arr import ARR_WINDOW_DAYS
from connectors.stubs import Arr
from tests.connectors.helpers import Resp, fake_requests
from tests.connectors.helpers import live, raw  # noqa: F401  (fixtures)
from tests.connectors.test_arr_counts import PKEY, PROWLARR

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)   # what the `live` fixture freezes arr._now to


def test_prowlarr_stats_ask_for_the_last_window_only(live, monkeypatch, raw):
    monkeypatch.setenv("PROWLARR_URL", PROWLARR)
    monkeypatch.setenv("PROWLARR_API_KEY", PKEY)
    calls = fake_requests(monkeypatch, raw)
    arr_get = requests.get
    seen = []

    def get(url, headers=None, params=None, timeout=None, **kw):
        if url.startswith(PROWLARR):
            seen.append(params)
            return Resp(raw["raw_prowlarr_indexerstats"])
        return arr_get(url, headers=headers, params=params, timeout=timeout, **kw)
    monkeypatch.setattr(requests, "get", get)

    Arr().run()
    assert len(seen) == 1 and seen[0] is not None, "indexerstats was asked for with no startDate / endDate"
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    assert seen[0]["startDate"] == (NOW - timedelta(days=ARR_WINDOW_DAYS)).strftime(fmt)
    assert seen[0]["endDate"] == NOW.strftime(fmt)
    assert calls  # radarr/sonarr still fetched
