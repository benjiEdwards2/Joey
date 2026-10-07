"""Eyes-on preview of the film page body (film-quality, 2026-10-07) — no live services, no network.

Renders hub/templates/media_film.html through the real hub app (TestClient) for four fixture titles and writes
static HTML under .preview/film/ (gitignored), with the real CSS / fonts linked and every /img/ picture swapped
for a local placeholder:
  1. a 1080p x265 Blu-ray film with crew, cast and library percentiles (the MediaHub reference shape)
  2. a 4K HDR10 / Dolby Vision WEB-DL film with Atmos
  3. a TV show (File panel degrades to totals)
  4. a film not on the server (no File panel)
The File panel, badges and crew come from the REAL code paths (media_files._summarise, media_film.file_panel /
crew_for, media_rank against a fixture library); only the page-level dict around them is hand-built.

    python scripts/render_film_preview.py
    python -m http.server 8765        # from the repo root, then open http://localhost:8765/.preview/film/
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".preview" / "film"
sys.path.insert(0, str(ROOT))

NAME_1080 = "500 Days of Summer (2009) {imdb-tt1022603} [QxR8R][Bluray-1080p][x265][AAC 5.1]-Tigole.mkv"
NAME_4K = "Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.Atmos.DV.HDR10.H.265-FLUX.mkv"


def _setup(tmp: Path) -> None:
    from tests.hub.test_media_shelves import shelf_area
    from tests.hub.test_registry import make_area, make_tile, write_registry
    from tests.hub.test_store import write_envelope

    area = shelf_area()
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    os.environ.update({"AREAS_PATH": str(write_registry(tmp, area, make_area("beta"))),
                       "MEDIA_DB_PATH": str(tmp / "media.db"), "SNAPSHOT_DIR": str(tmp / "snaps"),
                       "META_CACHE_DIR": str(tmp / "meta"), "IMG_CACHE_DIR": str(tmp / "img"),
                       "PLAY_RECORDER": "off", "MEDIA_WARMUP": "off", "MEDIA_FOLLOW": "off"})
    for k in ("JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYSEERR_URL", "JELLYSEERR_API_KEY"):
        os.environ.pop(k, None)  # no live service is ever reachable from the preview
    for snap in ("jellyfin", "arr", "jellyseerr"):
        write_envelope(tmp / "snaps", snap, age_minutes=1, data={"summary": "x"})
    # A fixture library of 120 films for the rank lines (sizes 1-30 GB, bitrates 2-40 Mb/s).
    films = {f"lib{i}": [(1 + (i * 7) % 30) * 1e9, (2 + (i * 11) % 39) * 1e6] for i in range(120)}
    (tmp / "meta").mkdir(parents=True, exist_ok=True)
    (tmp / "meta" / "library_rank.json").write_text(json.dumps({"at": time.time(), "films": films}), encoding="utf-8")


def _jf_item(jf_id, name, video, audios, subs, size, bitrate=None, ticks=None, container="mkv"):
    streams = [{"Type": "Video", **video}] + [{"Type": "Audio", **a} for a in audios] + \
        [{"Type": "Subtitle", **s} for s in subs]
    src = {"Container": container, "Size": size, "Path": f"/volume1/media/movies/{name}", "MediaStreams": streams}
    if bitrate:
        src["Bitrate"] = bitrate
    return {"Id": jf_id, "RunTimeTicks": ticks, "MediaSources": [src]}


def _base(**kw) -> dict:
    film = {"title": "", "year": None, "backdrop": None, "poster": None, "score": None, "episode": None, "tagline": "",
            "kind": "movie", "facts": {"runtime": None, "seasons": None, "languages": None, "releases": [], "added": None},
            "official": None, "genres": [], "makers": [], "makers_label": "Director", "tmdb": None, "on_server": True,
            "jf_failed": False, "status_line": "", "note": None, "play": None, "rating": None, "t": None,
            "wl_on": False, "show_request": False, "req_state": "idle", "req_msg": None, "trailer": None,
            "jellyseerr_href": None, "numbers": {}, "overview": "", "file": None, "crew": [], "cast": [],
            "cast_h": 400, "watch_count": 0, "diary": [], "requested_when": None, "requested_by": None,
            "providers": [], "seasons": [], "next_air": None, "shelves": [], "follow_flash": None, "files": None}
    film.update(kw)
    return film


def _cast(pairs):
    return [{"name": n, "role": r, "ref": f"tmdb:/p{i}.jpg" if i % 5 != 4 else None, "id": 1000 + i}
            for i, (n, r) in enumerate(pairs)]


def _films() -> dict[str, dict]:
    from hub import media_files as mf, media_film

    # 1. 1080p x265 Blu-ray, MediaHub's own example shape
    one = _jf_item("j500", NAME_1080, {"Codec": "hevc", "Width": 1920, "Height": 800},
                   [{"Codec": "aac", "Channels": 6, "Language": "eng", "IsDefault": True},
                    {"Codec": "aac", "Channels": 2, "Language": "eng"}],
                   [{"Codec": "dvd_subtitle", "Language": lang} for lang in ("eng", "fra", "spa", "ger", "ita")],
                   size=int(3.4 * 1024 ** 3), bitrate=4_700_000)
    raw1 = {"credits": {"crew": [
        {"name": "Marc Webb", "job": "Director", "id": 1}, {"name": "Michael H. Weber", "job": "Screenplay", "id": 2},
        {"name": "Scott Neustadter", "job": "Writer", "id": 3}, {"name": "Scott Neustadter", "job": "Story", "id": 3},
        {"name": "Eric Steelberg", "job": "Director of Photography", "id": 4},
        {"name": "Mychael Danna", "job": "Original Music Composer", "id": 5}, {"name": "Rob Simonsen", "job": "Music", "id": 6},
        {"name": "Alan Edward Bell", "job": "Editor", "id": 7}]}}
    f1 = mf._summarise("movie", [one])
    summer = _base(
        title="(500) Days of Summer", year=2009, tagline="This is not a love story. This is a story about love.",
        poster="tmdb:/poster1.jpg", backdrop="tmdb:/bd1.jpg", genres=["Comedy", "Drama", "Romance"], tmdb=19913,
        official="M", makers=[{"name": "Marc Webb", "id": 1}],
        status_line="On your server · 1080p · not watched yet", play={"href": "#", "label": "Play ▶"},
        rating={"item_key": "tmdb:19913", "kind": "movie", "level": "show", "title": "(500) Days of Summer", "year": 2009,
                "poster": None},
        numbers={"community": "7.3 / 10", "imdb": "7.7", "rt": "85 %", "runtime": "1h 35m", "ends": "22:10"},
        overview="Tom, greeting-card writer and hopeless romantic, is caught completely off-guard when his girlfriend, "
                 "Summer, suddenly dumps him. He reflects on their 500 days together to try to figure out where their "
                 "love affair went sour, and in doing so, Tom rediscovers his true passions in life.",
        facts={"runtime": "1h 35m", "seasons": None, "languages": None, "added": "1 May 2024",
               "releases": [{"label": "Cinema", "date": "17 Sep 2009"}, {"label": "Disc", "date": "22 Dec 2009"}]},
        file=media_film.file_panel(f1, "movie", "1 May 2024"), files=f1, crew=media_film.crew_for(raw1, "movie"),
        cast=_cast([("Joseph Gordon-Levitt", "Tom Hansen"), ("Zooey Deschanel", "Summer Finn"),
                    ("Geoffrey Arend", "McKenzie"), ("Chloë Grace Moretz", "Rachel Hansen"), ("Matthew Gray Gubler", "Paul"),
                    ("Clark Gregg", "Vance"), ("Patricia Belcher", "Millie"), ("Rachel Boston", "Alison")]),
        watch_count=2, diary=["14 Feb 2025", "3 Mar 2024"])

    # 2. 4K HDR WEB-DL with Atmos (bitrate from size / runtime: no Bitrate field)
    two = _jf_item("jdune", NAME_4K, {"Codec": "hevc", "Width": 3840, "Height": 1608, "VideoRangeType": "DOVIWithHDR10"},
                   [{"Codec": "eac3", "Channels": 6, "Profile": "Dolby Digital Plus + Dolby Atmos", "Language": "eng",
                     "IsDefault": True}],
                   [{"Codec": "subrip", "Language": "eng"}, {"Codec": "subrip", "Language": "fra"}],
                   size=int(24.6 * 1024 ** 3), ticks=166 * 600_000_000)
    raw2 = {"credits": {"crew": [{"name": "Denis Villeneuve", "job": "Director", "id": 11},
                                 {"name": "Denis Villeneuve", "job": "Screenplay", "id": 11},
                                 {"name": "Jon Spaihts", "job": "Screenplay", "id": 12},
                                 {"name": "Frank Herbert", "job": "Novel", "id": 13},
                                 {"name": "Greig Fraser", "job": "Director of Photography", "id": 14},
                                 {"name": "Hans Zimmer", "job": "Original Music Composer", "id": 15},
                                 {"name": "Joe Walker", "job": "Editor", "id": 16}]}}
    f2 = mf._summarise("movie", [two])
    dune = _base(
        title="Dune: Part Two", year=2024, tagline="Long live the fighters.", poster="tmdb:/poster2.jpg",
        backdrop="tmdb:/bd2.jpg", genres=["Science Fiction", "Adventure"], tmdb=693134, official="M",
        makers=[{"name": "Denis Villeneuve", "id": 11}], score=10,
        rating={"item_key": "tmdb:693134", "kind": "movie", "level": "show", "title": "Dune: Part Two", "year": 2024,
                "poster": None},
        status_line="On your server · 4K · Dolby Vision · watched 2 Mar · you rated 10",
        play={"href": "#", "label": "Play again ▶"},
        numbers={"community": "8.2 / 10", "imdb": "8.5", "rt": "92 %", "runtime": "2h 46m", "ends": "23:41"},
        overview="Follow the mythic journey of Paul Atreides as he unites with Chani and the Fremen while on a path "
                 "of revenge against the conspirators who destroyed his family.",
        facts={"runtime": "2h 46m", "seasons": None, "languages": None, "added": "28 May 2024",
               "releases": [{"label": "Cinema", "date": "29 Feb 2024"}, {"label": "Digital", "date": "16 Apr 2024"}]},
        file=media_film.file_panel(f2, "movie", "28 May 2024"), files=f2, crew=media_film.crew_for(raw2, "movie"),
        cast=_cast([("Timothée Chalamet", "Paul Atreides"), ("Zendaya", "Chani"), ("Rebecca Ferguson", "Jessica"),
                    ("Josh Brolin", "Gurney Halleck"), ("Austin Butler", "Feyd-Rautha Harkonnen"),
                    ("Florence Pugh", "Princess Irulan"), ("Dave Bautista", "Rabban"), ("Javier Bardem", "Stilgar")]),
        watch_count=1, diary=["2 Mar 2025"])

    # 3. A TV show: File panel degrades to the total size and episode count
    eps = [{"ParentIndexNumber": s, "IndexNumber": e, "MediaSources": [{
        "Container": "mkv", "Size": int(1.6 * 1024 ** 3), "Path": f"/volume1/tv/Show/S0{s}E0{e}.mkv", "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080},
            {"Type": "Audio", "Codec": "eac3", "Channels": 6, "Language": "eng", "IsDefault": True},
            {"Type": "Subtitle", "Codec": "subrip", "Language": "eng"}]}]} for s in (1, 2) for e in range(1, 9)]
    f3 = mf._summarise("tv", eps)
    raw3 = {"createdBy": [{"name": "Dan Erickson", "id": 21}],
            "credits": {"crew": [{"name": "Theodore Shapiro", "job": "Original Music Composer", "id": 22}]}}
    show = _base(
        title="Severance", year=2022, kind="tv", tagline="Work is a mystery.", poster="tmdb:/poster3.jpg",
        backdrop="tmdb:/bd3.jpg", genres=["Drama", "Mystery"], tmdb=95396, makers=[{"name": "Dan Erickson", "id": 21}],
        makers_label="Creators", official="MA15+", status_line="On your server · 16 episodes · 3 to watch · S2 E6 next",
        play={"href": "#", "label": "Next to watch: S2 E6 ▶"},
        numbers={"community": "8.4 / 10", "imdb": "8.7", "rt": "96 %"},
        overview="Mark leads a team of office workers whose memories have been surgically divided between their work "
                 "and personal lives.",
        facts={"runtime": None, "seasons": "2 seasons · 19 episodes", "languages": "Audio English · Subtitles English",
               "added": "18 Feb 2022", "releases": []},
        file=media_film.file_panel(f3, "tv", "18 Feb 2022"), files=f3, crew=media_film.crew_for(raw3, "tv"),
        cast=_cast([("Adam Scott", "Mark Scout"), ("Britt Lower", "Helly R."), ("Zach Cherry", "Dylan George"),
                    ("John Turturro", "Irving Bailiff"), ("Patricia Arquette", "Harmony Cobel")]))

    # 4. A film not on the server
    off = _base(
        title="Past Lives", year=2023, tagline="", poster="tmdb:/poster4.jpg", backdrop="tmdb:/bd4.jpg",
        genres=["Drama", "Romance"], tmdb=666277, on_server=False, makers=[{"name": "Celine Song", "id": 31}],
        status_line="Not on your server · Requested 3 hours ago", show_request=False,
        numbers={"community": "7.6 / 10", "runtime": "1h 46m"},
        overview="Nora and Hae Sung, two childhood friends, are reunited in New York for one fateful week.",
        facts={"runtime": "1h 46m", "seasons": None, "languages": None, "added": None,
               "releases": [{"label": "Cinema", "date": "2 Jun 2023"}]},
        crew=media_film.crew_for({"credits": {"crew": [{"name": "Celine Song", "job": "Director", "id": 31},
                                                       {"name": "Celine Song", "job": "Writer", "id": 31}]}}, "movie"),
        cast=_cast([("Greta Lee", "Nora"), ("Teo Yoo", "Hae Sung"), ("John Magaro", "Arthur")]),
        requested_when="3 hours ago", requested_by="B.")
    return {"1-bluray-1080p": summer, "2-4k-hdr-webdl": dune, "3-tv-show": show, "4-not-on-server": off}


def _placeholder(ref: str, h: int) -> str:
    hue = sum(ref.encode()) * 37 % 360
    wide = ref.startswith(("jfb:", "tmdb:/bd"))
    w, hh = (1280, 720) if wide else (200, 300)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {hh}"><defs><linearGradient id="g" x1="0" y1="0" '
           f'x2="1" y2="1"><stop offset="0" stop-color="hsl({hue},45%,42%)"/><stop offset="1" stop-color="hsl({(hue + 50) % 360},'
           f'40%,18%)"/></linearGradient></defs><rect width="{w}" height="{hh}" fill="url(#g)"/>'
           + ("" if wide else f'<circle cx="100" cy="118" r="46" fill="hsl({hue},30%,70%)" opacity=".55"/>'
              f'<ellipse cx="100" cy="270" rx="86" ry="74" fill="hsl({hue},30%,70%)" opacity=".45"/>') + "</svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _localise(html: str) -> str:
    html = re.sub(r'(["\'(])/static/', r"\1../../hub/static/", html)
    return re.sub(r"/img/([A-Za-z0-9:_./-]+)\?h=(\d+)[^\"')]*",
                  lambda m: _placeholder(m.group(1), int(m.group(2))), html)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _setup(Path(tmp))
        import hub.main
        importlib.reload(hub.main)
        from fastapi.testclient import TestClient
        from hub import media_film, media_rank

        media_rank.clear_cache()
        films = _films()
        current = {}
        media_film.build_film = lambda *a, **k: current["film"]
        OUT.mkdir(parents=True, exist_ok=True)
        links = []
        with TestClient(hub.main.app) as client:
            for slug, film in films.items():
                current["film"] = film
                resp = client.get(f"/media/title/{film['kind']}/{film['tmdb']}")
                resp.raise_for_status()
                (OUT / f"{slug}.html").write_text(_localise(resp.text), encoding="utf-8")
                links.append(f'<li><a href="{slug}.html">{slug}</a> — {film["title"]}</li>')
        (OUT / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>Film page preview</title>'
            '<body style="font-family:sans-serif;background:#09090b;color:#fafafa;padding:24px">'
            "<h1>Film page preview (fixtures, no network)</h1><ul>" + "".join(links) + "</ul></body>", encoding="utf-8")
    print(f"wrote {len(films)} pages to {OUT}")


if __name__ == "__main__":
    main()
