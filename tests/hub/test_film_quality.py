"""film-quality (2026-10-07): the film page's MediaHub-style body — File panel parsing (bitrate, picture shape,
subtitle kind, source, release group, file name only), Crew grouping, portrait cast at the warm-up's size, and the
library rank ("Smaller than N% of your films"). Upstreams are the test_media_film fakes; no network."""
import json
import time

import pytest

from hub import images, media_files as mf, media_film, media_rank, media_warmup
from tests.hub.test_media_film import FILM, ITEMS, SOURCES, STREAMS, env, main_of  # noqa: F401  (env = fixture)

NAME = "500 Days of Summer (2009) {imdb-tt1022603} [QxR8R][Bluray-1080p][x265][AAC 5.1]-Tigole.mkv"


# ---- parsing ----

def test_bitrate_from_source_else_size_over_runtime():
    assert mf.bitrate_bps({"Bitrate": 4_700_000}, {}) == 4_700_000
    # 3.4 GB over 95 min -> about 5.1 Mb/s
    bps = mf.bitrate_bps({"Size": 3.4e9}, {"RunTimeTicks": 95 * 600_000_000})
    assert mf.bitrate_text(bps) == "4.8 Mb/s"
    assert mf.bitrate_bps({"Size": 1e9}, {}) is None and mf.bitrate_bps({"Bitrate": True}, {}) is None
    assert mf.bitrate_text(None) is None


@pytest.mark.parametrize("w,h,ratio,shape", [
    (1920, 800, "2.40 : 1", "Scope"), (1920, 1040, "1.85 : 1", "Flat"), (1920, 1080, "1.78 : 1", "Widescreen"),
    (1440, 1080, "1.33 : 1", "Full frame"), (3840, 1920, "2.00 : 1", "Wide")])
def test_picture_ratio_and_shape(w, h, ratio, shape):
    p = mf.picture({"Width": w, "Height": h})
    assert p["ratio"] == ratio and p["sub"] == f"{shape} · {w} × {h}"


def test_picture_anamorphic_uses_declared_shape_and_none_without_size():
    assert mf.picture({"Width": 720, "Height": 480, "AspectRatio": "16:9", "IsAnamorphic": True})["ratio"] == "1.78 : 1"
    assert mf.picture({}) is None and mf.picture(None) is None


@pytest.mark.parametrize("name,group,source", [
    (NAME, "Tigole", "Blu-ray"),
    ("Movie.2020.1080p.WEB-DL.DDP5.1.H.264-FLUX.mkv", "FLUX", "WEB-DL"),
    ("Movie.2020.1080p.WEB-DL.mkv", None, "WEB-DL"),
    ("Movie 2019 2160p UHD BluRay REMUX HDR HEVC Atmos-FGT.mkv", "FGT", "Remux"),
    ("Movie.2019.2160p.UHD.BluRay.x265-TERMiNAL.mkv", "TERMiNAL", "UHD Blu-ray"),
    ("Movie.2018.720p.WEBRip.x264-x265.mp4", None, "WEBRip"),
    ("Show.S01E01.HDTV.x264-LOL.mkv", "LOL", "HDTV"),
    ("Old Film (1950).mkv", None, None), (None, None, None)])
def test_release_group_and_source(name, group, source):
    assert mf.release_group(name) == group and mf.source_word(name) == source


def test_subtitle_kind_text_vs_picture():
    for c in ("subrip", "srt", "ass", "mov_text"):
        assert mf.subtitle_kind(c)[0] == "Text", c
    for c in ("pgs", "PGSSUB", "vobsub", "dvdsub", "dvd_subtitle"):
        assert mf.subtitle_kind(c)[0] == "Picture", c
    assert mf.subtitle_kind("dvd_subtitle") == ("Picture", "VobSub") and mf.subtitle_kind("weird") is None


def test_subs_and_audio_words():
    subs = [{"lang": "English", "kind": "Picture", "format": "VobSub"}] + \
        [{"lang": lang, "kind": "Picture", "format": "VobSub"} for lang in ("French", "German", "Spanish", "Italian", "French")]
    assert mf.subs_text(subs) == "English + 4 more · Picture (VobSub)"
    assert mf.subs_text([{"lang": "English", "kind": "Text", "format": "SRT"},
                         {"lang": "English", "kind": "Picture", "format": "PGS"}]) == "English · Text + Picture"
    assert mf.subs_text([]) is None
    audios = [{"Language": "fra"}, {"Language": "eng", "IsDefault": True}]
    assert mf.audio_text(audios) == "English, French · 2 tracks" and mf.audio_text([{}]) == "1 track"


def test_file_name_never_carries_folders():
    assert mf.basename("/volume1/media/movies/500 Days (2009)/" + NAME) == NAME
    assert mf.basename(r"D:\films\a\b.mkv") == "b.mkv" and mf.basename(None) is None


def test_detail_for_one_film_file():
    streams = [{"Type": "Video", "Codec": "hevc", "Width": 1920, "Height": 800},
               {"Type": "Audio", "Codec": "aac", "Channels": 6, "Language": "eng", "IsDefault": True},
               {"Type": "Audio", "Codec": "aac", "Channels": 2, "Language": "eng"},
               {"Type": "Subtitle", "Codec": "dvd_subtitle", "Language": "eng"},
               {"Type": "Subtitle", "Codec": "dvd_subtitle", "Language": "spa"}]
    item = {"Id": "abc", "MediaSources": [{"Container": "mkv", "Size": 3_650_722_201, "Bitrate": 4_700_000,
                                            "Path": "/data/movies/x/" + NAME, "MediaStreams": streams}]}
    s = mf._summarise("movie", [item])
    d = s["file"]
    assert (d["filename"], d["release"], d["bitrate_text"], d["picture"]["ratio"]) == (NAME, "group Tigole · MKV", "4.7 Mb/s", "2.40 : 1")
    assert d["audio_text"] == "English · 2 tracks" and d["subs_text"] == "English + 1 more · Picture (VobSub)"
    assert s["source"] == "Blu-ray" and s["size"] == 3_650_722_201 and "/data/" not in json.dumps(s)


# ---- badges + crew ----

def test_badges_main_word_sub_label_and_source_last(tmp_path, monkeypatch):
    monkeypatch.setattr(media_film, "BADGES_DIR", tmp_path)
    files = {"video": [{"word": "1080p", "icon": "res"}, {"word": "HEVC", "icon": "codec"}, {"word": "MKV", "icon": "box"}],
             "audio": [{"word": "AAC", "icon": "audio"}, {"word": "5.1", "icon": "channels"}], "source": "Blu-ray"}
    got = [(b["main"], b["sub"]) for b in media_film.badges_for(files)]
    assert got == [("1080p", "FULL HD"), ("H.265", "HEVC"), ("AAC", ""), ("5.1", "SURROUND"), ("Blu-ray", "")]
    (tmp_path / "1080p.svg").write_text("<svg/>", encoding="utf-8")       # the override hook covers every badge
    assert media_film.badges_for(files)[0]["img"] == "/static/badges/1080p.svg"
    assert media_film.badge("Dolby Vision")["id"] == "dolby-vision"        # F10 override ids kept


def test_crew_groups_roles_dedupes_writers_and_drops_empty_roles():
    raw = {"credits": {"crew": [
        {"name": "Marc Webb", "job": "Director", "id": 1},
        {"name": "Scott Neustadter", "job": "Screenplay", "id": 2}, {"name": "Michael H. Weber", "job": "Writer", "id": 3},
        {"name": "Scott Neustadter", "job": "Story", "id": 2},
        {"name": "Eric Steelberg", "job": "Director of Photography", "id": 4},
        {"name": "Mychael Danna", "job": "Original Music Composer"}, {"name": "Rob Simonsen", "job": "Music"},
        {"name": "Grip Person", "job": "Key Grip"}]}}
    crew = media_film.crew_for(raw, "movie")
    assert [c["role"] for c in crew] == ["Director", "Writer", "Cinematography", "Composer"]   # no editor -> no row
    assert [p["name"] for p in crew[1]["people"]] == ["Scott Neustadter", "Michael H. Weber"]
    assert crew[0]["people"][0] == {"name": "Marc Webb", "id": 1} and crew[3]["people"][0]["id"] is None
    tv = media_film.crew_for({"createdBy": [{"name": "Cass Creator", "id": 9}]}, "tv")
    assert tv == [{"role": "Created by", "people": [{"name": "Cass Creator", "id": 9}]}]
    assert media_film.crew_for({}, "movie") == []


def test_warmup_warms_the_cast_size_the_page_renders():
    assert media_warmup.CAST_H == media_film.CAST_H == 400 and media_film.CAST_H in images.SIZES
    assert media_warmup.CAST_WARM == media_film.CAST_MAX
    assert images.TMDB_WIDTH[media_film.CAST_H] == "w500"   # 500 px wide covers a 180 px card at 2x


# ---- library rank ----

def test_rank_phrase_takes_the_larger_share():
    others = list(range(1, 100))                     # 99 other films, sizes 1..99
    assert media_rank.phrase(7, others, ("Smaller", "Larger")) == "Smaller than 93% of your films"
    assert media_rank.phrase(91, others, ("Smaller", "Larger")) == "Larger than 91% of your films"
    assert media_rank.phrase(10, others, ("Lower", "Higher")) == "Lower than 90% of your films"
    assert media_rank.phrase(5, list(range(1, 19)), ("Smaller", "Larger")) is None    # 19 films < MIN_FILMS
    assert media_rank.phrase(5, list(range(1, 20)), ("Smaller", "Larger")) is not None
    assert media_rank.phrase(None, others, ("Smaller", "Larger")) is None


@pytest.fixture()
def rankdir(tmp_path, monkeypatch):
    monkeypatch.setenv("META_CACHE_DIR", str(tmp_path / "meta"))
    media_rank.clear_cache()
    yield tmp_path / "meta"
    media_rank.clear_cache()


def write_rank(folder, films, at=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / media_rank.FILE).write_text(json.dumps({"at": at or time.time(), "films": films}), encoding="utf-8")


def test_rank_excludes_the_film_itself_and_reads_the_file(rankdir):
    write_rank(rankdir, {**{f"f{i}": [i * 1e9, i * 1e6] for i in range(1, 30)}, "me": [1e12, 1e12]})
    got = media_rank.rank("me", 2.5e9, 2.5e6)
    assert got == {"size": "Smaller than 93% of your films", "bitrate": "Lower than 93% of your films"}
    assert not media_rank.due()
    write_rank(rankdir, {}, at=time.time() - 25 * 3600)
    assert media_rank.due()


def test_rows_from_items_and_refresh_writes_the_file(rankdir, monkeypatch):
    items = [{"Id": "a", "RunTimeTicks": 100 * 600_000_000, "MediaSources": [{"Size": 6e9}]},
             {"Id": "b", "MediaSources": [{"Size": 2e9, "Bitrate": 3_000_000}]}, {"Id": "c"}, "junk"]
    assert media_rank.rows_from(items) == {"a": [6e9, 8_000_000], "b": [2e9, 3_000_000]}
    monkeypatch.setattr(mf, "_creds", lambda: ("http://jf.invalid", {}))
    monkeypatch.setattr(mf, "_user_id", lambda base, headers: "u1")
    seen = []
    monkeypatch.setattr(mf, "_get", lambda base, headers, path, params=None: seen.append(params) or {"Items": items})
    assert media_rank.refresh() == 2 and seen[0]["IncludeItemTypes"] == "Movie" and seen[0]["Fields"] == "MediaSources"
    assert json.loads((rankdir / media_rank.FILE).read_text(encoding="utf-8"))["films"]["b"] == [2e9, 3_000_000]
    monkeypatch.setattr(mf, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert media_rank.refresh() is None                                   # a failure never raises


def test_run_pass_refreshes_the_rank_only_when_due(rankdir, monkeypatch):
    calls = []
    monkeypatch.setenv("MEDIA_WARMUP", "shelves")
    monkeypatch.setattr(media_warmup, "warm_once", lambda snaps=None, pause=0: {})
    monkeypatch.setattr(media_rank, "refresh", lambda: calls.append(1) or 5)
    assert media_warmup.run_pass(pause=0)["rank"] == 5
    write_rank(rankdir, {})
    assert "rank" not in media_warmup.run_pass(pause=0) and calls == [1]


# ---- the page ----

def film_source(**extra):
    streams = STREAMS + [{"Type": "Audio", "Codec": "aac", "Channels": 2, "Language": "eng"},
                         {"Type": "Subtitle", "Codec": "subrip", "Language": "eng"}]
    return [{**SOURCES[0], "MediaStreams": streams, "Bitrate": 4_700_000,
             "Path": "/volume1/secret-share/movies/Harbour Lights (2019)/Harbour.Lights.2019.2160p.WEB-DL.DDP5.1.HEVC-FLUX.mkv",
             **extra}]


def test_file_panel_renders_grid_rows_and_file_name_only(env, monkeypatch, rankdir):
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", film_source())
    monkeypatch.setitem(ITEMS["mov1"], "DateCreated", "2024-05-01T10:00:00.0000000Z")
    write_rank(rankdir, {f"f{i}": [i * 1e9, i * 1e6] for i in range(1, 30)})
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    panel = b.split('<div class="seclabel">File</div>', 1)[1].split("</section>", 1)[0]
    assert '<b>WEB-DL</b>' in panel and 'class="fmt fmt-source"' in panel
    for label, value in (("Size", "20.0 GB"), ("Bitrate", "4.7 Mb/s"), ("Picture", "1.78 : 1"), ("Added", "1 May 2024")):
        assert f'<div class="microlabel">{label}</div><div class="filestat-value">{value}</div>' in panel, label
    assert "Widescreen · 3840 × 2160" in panel
    assert "Larger than 72% of your films" in panel and "Lower than 86% of your films" in panel   # 21.5 GB, 4.7 Mb/s vs 1..29
    assert "<dt>Audio</dt><dd>English · 2 tracks</dd>" in panel and "<dt>Release</dt><dd>group FLUX · MKV</dd>" in panel
    assert "<dt>Subtitles</dt><dd>English · Text (SRT)</dd>" in panel
    assert '<p class="filename">Harbour.Lights.2019.2160p.WEB-DL.DDP5.1.HEVC-FLUX.mkv</p>' in panel
    assert "secret-share" not in b and "/volume1" not in b                 # never the folders
    assert b.index(">Overview</div>") < b.index(">File</div>") < b.index(">Crew</div>") < b.index(">Cast</div>")


def test_rank_hidden_under_twenty_films(env, monkeypatch, rankdir):
    monkeypatch.setitem(ITEMS["mov1"], "MediaSources", film_source())
    write_rank(rankdir, {f"f{i}": [i * 1e9, i * 1e6] for i in range(1, 10)})
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert "of your films" not in b and "4.7 Mb/s" in b


def test_tv_file_panel_degrades_to_totals(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/tv/100").text)
    assert '<div class="seclabel">Crew</div>' in b and "<dt>Created by</dt>" in b and "Cass Creator" in b
    if '<div class="seclabel">File</div>' in b:                             # the fake show has no file facts
        panel = b.split('<div class="seclabel">File</div>', 1)[1].split("</section>", 1)[0]
        assert 'class="filename"' not in panel and ">Bitrate<" not in panel


def test_tv_summary_has_no_single_file():
    eps = [{"ParentIndexNumber": 1, "IndexNumber": i, "MediaSources": [{"Size": 1e9, "Path": f"/x/S01E0{i}-GRP.mkv",
            "MediaStreams": STREAMS}]} for i in (1, 2)]
    s = mf._summarise("tv", eps)
    panel = media_film.file_panel(s, "tv", "2 Mar 2026")
    labels = [g["label"] for g in panel["grid"]]
    assert labels == ["Size", "On disk", "Added"] and panel["filename"] is None
    assert panel["grid"][1]["value"] == "2 episodes" and not [r for r in panel["rows"] if r["label"] == "Release"]


def test_not_on_server_film_has_no_file_section_but_keeps_details(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/701").text)
    assert '<div class="seclabel">File</div>' not in b and '<div class="seclabel">Crew</div>' not in b
    assert '<div class="seclabel">Overview</div>' in b and "Nothing yet." in b


def test_stats_card_and_portrait_cast(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    stats = b.split('<div class="stats numbers">', 1)[1].split("\n</div>", 1)[0]
    assert '<a class="scorepill sp-you" href="#rate">' in stats and '<b class="sp-val">Rate</b></a>' in stats  # media-ux4 (2026-10-08, B.): one pill style
    assert '<span class="sp-name">IMDb</span>' in stats and ">Runtime</div>" in stats
    cast = b.split('<div class="castrow">', 1)[1].split("</section>", 1)[0]
    assert f'src="/img/tmdb:/ada.jpg?h={media_film.CAST_H}"' in cast and 'width="180" height="270"' in cast
    assert '<span class="castname">Ada Actor</span><span class="castrole">as Pilot</span>' in cast


def test_cast_row_scrolls_inside_itself_css():
    from pathlib import Path
    css = (Path(media_film.__file__).resolve().parent / "static" / "control-surface.css").read_text(encoding="utf-8")
    row = css.split(".castrow {", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in row and "flex-wrap" not in row
    assert "flex: 0 0 130px" in css.split(".castcard {", 1)[1].split("}", 1)[0] and ".castcard { flex-basis: 180px; }" in css
    assert "aspect-ratio: 2 / 3" in css.split(".castpic {", 1)[1].split("}", 1)[0]
