"""media-warm-library (2026-10-07): the 24 h full-library warm-up. Covers both profiles de-duplicated, warms
exactly the /img refs + sizes the item page renders above the fold, costs a stat for cached files, 24 h gating,
and the MEDIA_WARMUP=shelves / off switches. Upstreams are the test_media_film fakes; no network."""
import re
import time

from hub import images, media_discover as md, media_warmup
from tests.hub.helpers import env  # noqa: F401  (re-export: defined in tests/hub/helpers.py)
from tests.hub.test_media_speed import warm_env  # noqa: F401


def test_library_targets_cover_both_profiles_deduplicated():
    jelly = {"movies": [{"item_key": "tmdb:1", "jf_id": "a"}, {"item_key": "tmdb:1", "jf_id": "a"}],
             "shows": [{"item_key": "tmdb:2", "jf_id": "s"}],
             "her": {"movies": [{"item_key": "tmdb:1", "jf_id": "a"}, {"item_key": "tmdb:3", "jf_id": "b"},
                                {"jf_id": "c"}, {"item_key": "tmdb:9"}], "shows": []}}
    got = media_warmup.library_targets(jelly)
    assert got == [{"kind": "movie", "tmdb": 1, "art": "a"}, {"kind": "tv", "tmdb": 2, "art": "s"},
                   {"kind": "movie", "tmdb": 3, "art": "b"}, {"kind": "movie", "tmdb": None, "art": "c"}]


def test_library_pass_warms_exactly_what_the_item_page_renders(env, monkeypatch, tmp_path):
    client, both, fetched = warm_env(env, monkeypatch, tmp_path)
    first = media_warmup.warm_library(pause=0)
    assert first["titles"] == 3 and first["failed"] == 0
    # 3 titles x (poster + backdrop) + the film's one cast photo, fetched for each of the 2 films with the credit
    assert first["fetched"] == len(fetched) and first["fetched"] >= 7
    with client:
        html = client.get("/media/item/mov1").text
    rendered = {(m.group(1), int(m.group(2))) for m in
                re.finditer(r"/img/([A-Za-z0-9:_./-]+?)\?h=(600|1280|400)\b", html)}
    assert ("jf:mov1", 600) in rendered and ("jfb:mov1", 1280) in rendered and ("tmdb:/ada.jpg", 400) in rendered
    for ref, h in rendered:   # every above-the-fold image the page asks for is already on disk
        assert images.warm(ref, h) == "cached", (ref, h)


def test_library_pass_skips_cached_files_without_upstream_calls(env, monkeypatch, tmp_path):
    _, both, fetched = warm_env(env, monkeypatch, tmp_path)
    media_warmup.warm_library(pause=0)
    n_img, n_calls = len(fetched), len(both.calls)
    md.clear_cache()
    second = media_warmup.warm_library(pause=0)
    assert second["fetched"] == 0 and second["cached"] >= 7 and len(fetched) == n_img
    assert not [c for c in both.calls[n_calls:] if "/api/v1/" in c]   # body + ratings came off the disk meta cache


def test_library_gating_24h_and_stamp(env, monkeypatch, tmp_path):
    _, both, fetched = warm_env(env, monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    assert media_warmup.library_due()
    out = media_warmup.run_pass(pause=0)
    assert out["library"]["titles"] == 3 and not media_warmup.library_due()
    assert "library" not in media_warmup.run_pass(pause=0)             # within 24 h: shelf pass only
    assert media_warmup.library_due(now=time.time() + 24 * 3600 + 5)
    media_warmup._stamp_path().write_text(str(time.time() - 25 * 3600))
    assert "library" in media_warmup.run_pass(pause=0)


def test_missing_backdrops_count_as_done_and_the_pass_is_stamped(env, monkeypatch, tmp_path):
    """M-44: a library whose items have no backdrop (images.warm -> "skipped" for every jfb: ref) completes, counts
    those as skipped rather than failed, and stamps — the whole-library pass no longer repeats every 3 h."""
    _, both, fetched = warm_env(env, monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    real = images.warm
    monkeypatch.setattr(images, "warm", lambda ref, h=0: "skipped" if ref.startswith("jfb:") else real(ref, h))
    out = media_warmup.run_pass(pause=0)
    lib = out["library"]
    assert lib["titles"] == 3 and lib["skipped"] == 3 and lib["failed"] == 0 and lib["fetched"] > 0
    assert not media_warmup.library_due()


def test_a_pass_without_keys_is_not_stamped(env, monkeypatch, tmp_path):
    warm_env(env, monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    for name in ("JELLYSEERR_URL", "JELLYSEERR_API_KEY", "JELLYFIN_URL", "JELLYFIN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    out = media_warmup.run_pass(pause=0)
    assert out["library"].get("skipped_no_keys") and media_warmup.library_due()


def test_mode_switches(env, monkeypatch, tmp_path):
    warm_env(env, monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIA_WARMUP", "shelves")
    assert not media_warmup.disabled() and not media_warmup.library_enabled()
    assert "library" not in media_warmup.run_pass(pause=0) and media_warmup.library_due()
    monkeypatch.setenv("MEDIA_WARMUP", "off")
    assert media_warmup.disabled() and not media_warmup.library_enabled()
    monkeypatch.setenv("MEDIA_WARMUP", "on")
    assert not media_warmup.disabled() and media_warmup.library_enabled()


def test_the_warm_up_loop_prunes_meta_files_older_than_seven_days(env, monkeypatch, tmp_path):
    """M-47 (W2): META_CACHE_DIR no longer grows forever — run_pass deletes files last written over 7 days ago."""
    import os
    warm_env(env, monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIA_WARMUP", "shelves")
    folder = md.meta_dir()
    folder.mkdir(parents=True, exist_ok=True)
    old, fresh = folder / "old.json", folder / "fresh.json"
    for f in (old, fresh):
        f.write_text("{}", encoding="utf-8")
    week = 7 * 24 * 3600
    os.utime(old, (time.time() - week - 60,) * 2)
    os.utime(fresh, (time.time() - week + 3600,) * 2)
    out = media_warmup.run_pass(pause=0)
    assert out["pruned"] == 1 and not old.exists() and fresh.exists()
