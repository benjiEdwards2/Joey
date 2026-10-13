"""E1 (2026-10-13): the phone backdrop. A Jellyfin backdrop is sized by the asked h (h=600 -> 800 wide), and both
warm-up passes warm that phone size beside the desktop h=1280 for every title they already warm. Fakes only."""
from hub import images, media_warmup
from tests.hub.helpers import env  # noqa: F401  (env fixture)
from tests.hub.test_media_speed import warm_env


def warmed(monkeypatch):
    seen = []
    real = images.warm
    monkeypatch.setattr(images, "warm", lambda ref, h=images.DEFAULT_SIZE: seen.append((ref, h)) or real(ref, h))
    return seen


def test_the_phone_size_is_six_hundred_and_eight_hundred_wide():
    assert media_warmup.BACKDROP_PHONE_H == 600 and images.JF_BACKDROP_WIDTH[600] == 800
    assert media_warmup.BACKDROP_H == 1280 and images.JF_BACKDROP_WIDTH[1280] == 1280
    assert images.SIZES == (120, 240, 400, 600, 1280)   # the allowed heights are unchanged


def test_the_shelf_pass_warms_both_backdrop_sizes(env, monkeypatch, tmp_path):
    warm_env(env, monkeypatch, tmp_path)
    seen = warmed(monkeypatch)
    media_warmup.warm_once(pause=0)
    backdrops = {r: {h for ref, h in seen if ref == r} for r, _ in seen if r.startswith("jfb:")}
    assert backdrops and all(hs == {600, 1280} for hs in backdrops.values())


def test_the_library_pass_warms_both_backdrop_sizes(env, monkeypatch, tmp_path):
    warm_env(env, monkeypatch, tmp_path)
    seen = warmed(monkeypatch)
    media_warmup.warm_library(pause=0)
    backdrops = {r: {h for ref, h in seen if ref == r} for r, _ in seen if r.startswith("jfb:")}
    assert len(backdrops) == 3 and all(hs == {600, 1280} for hs in backdrops.values())
