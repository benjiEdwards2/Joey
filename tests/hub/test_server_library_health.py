"""WP-T3 (2026-10-19, S1 + S2): the Library health line under Services › Downloads — the Counts band's unique
figures (Radarr / Sonarr wanted + missing, Prowlarr failed grabs). Was test_server_counts.py (WP-S3, 2026-10-06: the
Radarr / Sonarr / Prowlarr rows of the Counts band, removed). Assertions inside <main>."""
import json
from types import SimpleNamespace

from hub import server
from tests.hub.test_server import SAMPLES, env, main_of, services_of, txt  # noqa: F401  (env is a fixture)


def arr_sample():
    return json.loads((SAMPLES / "arr.json").read_text(encoding="utf-8"))["data"]


def downloads_of(body):
    return services_of(body).split('<h2 class="seclabel">Downloads</h2>', 1)[1].split("</section>", 1)[0]


def test_library_health_line_sits_under_downloads_with_the_sample_counts(env):
    """Was test_counts_band_shows_radarr_sonarr_and_prowlarr_from_the_samples (Counts band rows)."""
    with env() as client:
        body = main_of(client.get("/server").text)
    line = downloads_of(body).split('class="metaline libhealth"', 1)[1].split("</p>", 1)[0]
    assert txt(line).startswith(">Library health · Radarr 2 wanted · 3 missing · Sonarr 7 wanted · ")
    assert '<span class="st-warn">Prowlarr 3 failed grabs</span>' in line                  # amber: a failure count
    assert '<a class="btn btn-ghost btn-sm" href="/media/requests?sweep_ask=missing">Search missing</a>' in line
    assert "Movies" not in line and "queued" not in txt(line) and "Queries" not in line    # the unique figures only


def test_older_or_nulled_arr_counts_render_no_line_and_no_error(env):
    """Was the same-named Counts test: an envelope from before WP-S3 and Prowlarr unset now mean no line at all."""
    arr = arr_sample()
    arr.pop("radarr")
    arr.pop("sonarr")        # an envelope from before WP-S3
    arr["prowlarr"] = None   # Prowlarr env unset on the box
    with env(arr=arr) as client:
        r = client.get("/server")
    assert r.status_code == 200 and "Library health" not in main_of(r.text)


def test_library_health_words_zero_nonzero_and_amber():
    snaps = lambda **arr: {"arr": SimpleNamespace(status="ok", data=arr)}  # noqa: E731
    zero = {"radarr": {"wanted": 0, "missing": 0}, "sonarr": {"wanted": 0}, "prowlarr": {"failed_grabs": 0}}
    assert server.library_health({}) is None
    clear = server.library_health(snaps(**zero))
    assert clear == {"parts": [], "failed": None, "search": None}                             # "all clear"
    some = server.library_health(snaps(**{**zero, "sonarr": {"wanted": 1}, "prowlarr": {"failed_grabs": 1}}))
    assert some == {"parts": ["Sonarr 1 wanted"], "failed": "Prowlarr 1 failed grab",
                    "search": server.SEARCH_MISSING_HREF}
    only_missing = server.library_health(snaps(radarr={"wanted": 0, "missing": 2}))
    assert only_missing["parts"] == ["Radarr 2 missing"] and only_missing["failed"] is None


def test_all_clear_line_has_no_amber_and_no_search(env):
    arr = {**arr_sample(), "radarr": {"wanted": 0, "missing": 0, "movies": 6, "queued": 0},
           "sonarr": {"wanted": 0, "queued": 0, "series": 3}, "prowlarr": {"failed_grabs": 0, "grabs": 4}}
    with env(arr=arr) as client:
        line = downloads_of(main_of(client.get("/server").text)).split('class="metaline libhealth"', 1)[1]
    line = line.split("</p>", 1)[0]
    assert txt(line) == ">Library health · all clear" and "st-warn" not in line and "Search missing" not in line
