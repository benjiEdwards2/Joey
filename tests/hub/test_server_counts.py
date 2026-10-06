"""WP-S3 (2026-10-06): Radarr / Sonarr / Prowlarr rows in the Server Counts band.
Rendered only when the arr snapshot carries them; assertions inside <main>."""
import json

from tests.hub.test_server import SAMPLES, env, main_of  # noqa: F401  (env is a fixture)


def counts_of(body):
    return body.split('id="counts"', 1)[1].split("</section>", 1)[0]


def row(label, value):
    return f'>{label}</span><span class="uptime nextleft">{value}<'


def test_counts_band_shows_radarr_sonarr_and_prowlarr_from_the_samples(env):
    with env() as client:
        band = counts_of(main_of(client.get("/server").text))
    radarr = band.split('<div class="upday">Radarr</div>', 1)[1].split('<div class="upday">Sonarr</div>', 1)[0]
    assert all(row(k, v) in radarr for k, v in (("Wanted", 2), ("Missing", 3), ("Queued", 1), ("Movies", 6)))
    sonarr = band.split('<div class="upday">Sonarr</div>', 1)[1].split('<div class="upday">Prowlarr</div>', 1)[0]
    assert all(row(k, v) in sonarr for k, v in (("Wanted", 7), ("Queued", 1), ("Series", 3)))
    prowlarr = band.split('<div class="upday">Prowlarr</div>', 1)[1]
    assert all(row(k, v) in prowlarr for k, v in (("Grabs", 40), ("Queries", 1325),
                                                  ("Failed grabs", 3), ("Failed queries", 52)))


def test_older_or_nulled_arr_counts_render_no_rows_and_no_error(env):
    arr = json.loads((SAMPLES / "arr.json").read_text(encoding="utf-8"))["data"]
    arr.pop("radarr")
    arr.pop("sonarr")        # an envelope from before WP-S3
    arr["prowlarr"] = None   # Prowlarr env unset on the box
    with env(arr=arr) as client:
        r = client.get("/server")
    assert r.status_code == 200
    band = counts_of(main_of(r.text))
    assert ">This week<" in band  # the existing arr rows still render
    for head in ("Radarr", "Sonarr", "Prowlarr"):
        assert f'<div class="upday">{head}</div>' not in band
