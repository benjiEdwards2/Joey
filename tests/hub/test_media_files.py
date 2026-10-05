"""File-quality strip (2026-10-06): Jellyfin file facts -> badge words. `requests.get` is faked; no network."""
import pytest
import requests

from hub import media_files

URL = "http://jf.secret-host.invalid:8096"
KEY = "jf-SECRET-key-123"
USERS = [{"Id": "u-plain", "Name": "Georgina", "Policy": {}},
         {"Id": "u-admin", "Name": "Ben", "Policy": {"IsAdministrator": True}},
         {"Id": "u-named", "Name": "Named", "Policy": {"IsAdministrator": True}}]


def vstream(h=1080, w=1920, codec="h264", rng="SDR"):
    return {"Type": "Video", "Codec": codec, "Height": h, "Width": w, "VideoRangeType": rng}


def astream(codec="aac", ch=2, profile="LC", default=True):
    return {"Type": "Audio", "Codec": codec, "Channels": ch, "Profile": profile, "IsDefault": default}


def item(streams, container="mkv", size=12.4 * 1024 ** 3, tmdb="1", **extra):
    return {"ProviderIds": {"Tmdb": tmdb}, **extra, "MediaSources": [{"Container": container, "Size": int(size), "MediaStreams": streams}]}


class R:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


class Fake:
    def __init__(self):
        self.calls, self.fail = [], False
        self.movies, self.series, self.episodes = [], [{"Id": "ser1"}], []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.startswith(URL) and headers == {"Authorization": f"MediaBrowser Token={KEY}"}
        path = url[len(URL):]
        self.calls.append((path, params))
        if self.fail:
            raise requests.ConnectionError(url)
        if path == "/Users":
            return R(USERS)
        if params.get("IncludeItemTypes") == "Movie":
            return R({"Items": self.movies})
        if params.get("IncludeItemTypes") == "Series":
            return R({"Items": self.series})
        return R({"Items": self.episodes})


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.delenv("JELLYFIN_USER", raising=False)
    media_files.clear_cache()
    f = Fake()
    monkeypatch.setattr(media_files.requests, "get", f.get)
    yield f
    media_files.clear_cache()


def words(badges):
    return [b["word"] for b in badges]


def test_uid_first_admin_and_named(fake, monkeypatch):
    fake.movies = [item([vstream(), astream()])]
    media_files.file_summary("movie", 1)
    assert fake.calls[1][0] == "/Users/u-admin/Items"
    media_files.clear_cache()
    monkeypatch.setenv("JELLYFIN_USER", "Named")
    media_files.file_summary("movie", 1)
    assert fake.calls[-1][0] == "/Users/u-named/Items"


def test_uid_cached_across_titles(fake):
    fake.movies = [item([vstream(), astream()])]
    media_files.file_summary("movie", 1)
    media_files.file_summary("movie", 2)
    assert [c[0] for c in fake.calls].count("/Users") == 1


def test_movie_4k_dv_truehd_atmos(fake):
    fake.movies = [item([vstream(2160, 3840, "hevc", "DOVIWithHDR10"),
                         astream("truehd", 8, "Dolby TrueHD + Dolby Atmos")], tmdb="603")]
    s = media_files.file_summary("movie", 603)
    params = fake.calls[1][1]
    assert params["AnyProviderIdEquals"] == "Tmdb.603" and params["IncludeItemTypes"] == "Movie"
    assert words(s["video"]) == ["4K", "Dolby Vision", "HEVC", "MKV"]
    assert words(s["audio"]) == ["TrueHD", "7.1", "Atmos"] and s["size_text"] == "12.4 GB"
    assert {b["icon"] for b in s["video"] + s["audio"]} == {"res", "hdr", "codec", "box", "audio", "channels", "atmos"}


def test_movie_1080p_h264_aac_stereo_mp4(fake):
    fake.movies = [item([vstream(), astream()], "mp4", 700 * 1024 ** 2)]
    s = media_files.file_summary("movie", 1)
    assert words(s["video"]) == ["1080p", "H.264", "MP4"] and words(s["audio"]) == ["AAC", "Stereo"]
    assert s["size_text"] == "700 MB"


@pytest.mark.parametrize("rng,word", [("HDR10", "HDR10"), ("HDR10Plus", "HDR10+"), ("HLG", "HLG"),
                                      ("DOVIInvalid", "HDR10"), ("DOVIWithHDR10Plus", "Dolby Vision")])
def test_hdr_words(fake, rng, word):
    fake.movies = [item([vstream(2160, 3840, "hevc", rng), astream()])]
    assert word in words(media_files.file_summary("movie", 1)["video"])


def test_audio_words(fake):
    for codec, profile, ch, word, chw in [("eac3", "", 6, "Dolby Digital Plus", "5.1"), ("ac3", "", 6, "Dolby Digital", "5.1"),
                                          ("dts", "DTS-HD MA", 8, "DTS-HD", "7.1"), ("dts", "DTS", 6, "DTS", "5.1"),
                                          ("flac", "", 1, "FLAC", "Mono")]:
        media_files.clear_cache()
        fake.movies = [item([vstream(720, 1280), astream(codec, ch, profile)])]
        s = media_files.file_summary("movie", 1)
        assert words(s["audio"]) == [word, chw] and "720p" in words(s["video"])


def test_show_mixed_resolutions(fake):
    fake.series = [{"Id": "other", "ProviderIds": {"Tmdb": "5"}}, {"Id": "ser1", "ProviderIds": {"tmdb": "100"}}]
    fake.episodes = [item([vstream(), astream()], size=1024 ** 3),
                     item([vstream(2160, 3840, "hevc", "HDR10"), astream()], size=2 * 1024 ** 3)]
    s = media_files.file_summary("tv", 100)
    assert s["episodes_on_disk"] == 2 and s["files"] == 2 and s["note"] == "1080p · 4K"
    assert words(s["video"])[:2] == ["1080p", "4K"] and s["size_text"] == "3.0 GB"
    series_call, eps_call = fake.calls[1], fake.calls[2]
    assert series_call[1]["AnyProviderIdEquals"] == "Tmdb.100" and eps_call[1]["ParentId"] == "ser1"
    assert eps_call[1]["IncludeItemTypes"] == "Episode"


def test_show_not_in_jellyfin_or_empty(fake):
    fake.series = []
    assert media_files.file_summary("tv", 100) is None
    fake.series = [{"Id": "x", "ProviderIds": {"Tmdb": "5"}}]
    assert media_files.file_summary("tv", 100) is None
    fake.movies = []
    assert media_files.file_summary("movie", 1) is None


def test_failure_returns_none_and_is_not_cached(fake, caplog):
    fake.fail = True
    assert media_files.file_summary("movie", 1) is None
    assert URL not in caplog.text and KEY not in caplog.text and "ConnectionError" in caplog.text
    fake.fail = False
    fake.movies = [item([vstream(), astream()])]
    assert media_files.file_summary("movie", 1) is not None


def test_not_configured(monkeypatch):
    monkeypatch.delenv("JELLYFIN_URL", raising=False)
    media_files.clear_cache()
    assert media_files.file_summary("movie", 1) is None


def test_cache_hit_and_expiry(fake, monkeypatch):
    fake.movies = [item([vstream(), astream()])]
    media_files.file_summary("movie", 1)
    n = len(fake.calls)
    media_files.file_summary("movie", 1)
    assert len(fake.calls) == n
    now = media_files.time.time()
    monkeypatch.setattr(media_files.time, "time", lambda: now + media_files.CACHE_TTL + 1)
    media_files.file_summary("movie", 1)
    assert len(fake.calls) > n


def test_movie_filtered_client_side(fake):
    fake.movies = [item([vstream(), astream()], tmdb="1"), item([vstream(2160, 3840, "hevc", "HDR10"), astream()], tmdb="2")]
    assert "4K" in words(media_files.file_summary("movie", 2)["video"])
    media_files.clear_cache()
    assert media_files.file_summary("movie", 3) is None
