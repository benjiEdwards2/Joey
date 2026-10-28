"""JY-264: a small Jellyfin library for the re-attach tests, with a simulated rebuild.

It hands the hub what the connector would write (`snapshot()`: the `jellyfin` data block's `movies` / `shows` rows,
in the connector's row shape, plus `library_fetched_at`) and fills a FakeJellyfin's `/Shows/{id}/Episodes` with the
same episodes (12.2 item shapes: Id, SeriesId, SeasonId, ParentIndexNumber, IndexNumber, Path, ProviderIds).

`rebuild()` re-mints EVERY item id (films, series, seasons, episodes) while keeping titles, years, provider ids and
paths, as a library removed and re-added does. Options: drop some provider ids, move the path prefix, or return a
half-scanned library. Names and ids are invented.
"""
from __future__ import annotations

import secrets

PREFIX = "/data/media"

FILMS = (
    # name, title, year, provider ids, file
    ("arrival", "Arrival", 2016, {"Tmdb": "329865", "Imdb": "tt2543164"}, "/movies/Arrival (2016)/Arrival.mkv"),
    ("home_video", "Home Video", 2019, {}, "/movies/Home Video (2019)/Home Video.mkv"),   # no TMDB id: a jf: key
    ("dune", "Dune", 2021, {"Tmdb": "438631", "Imdb": "tt1160419"}, "/movies/Dune (2021)/Dune (2160p).mkv"),
)
SERIES = (
    # name, title, year, provider ids, folder, {season: episode count}
    ("severance", "Severance", 2022, {"Tvdb": "371980", "Tmdb": "95396", "Imdb": "tt11280740"},
     "/tv/Severance", {1: 3, 2: 2}),
    ("bluey", "Bluey", 2018, {"Tvdb": "353546", "Tmdb": "82728"}, "/tv/Bluey", {1: 2}),
)


def _mint() -> str:
    return secrets.token_hex(16)


class FakeLibrary:
    def __init__(self, fake_jellyfin=None):
        self.fj = fake_jellyfin
        self.prefix = PREFIX
        self.dropped: tuple = ()
        self.partial = False
        self.extra_films: list[tuple] = []
        self.ids: dict = {}
        self._mint_all()

    # ---- ids ----
    def _mint_all(self) -> None:
        ids = {}
        for name, *_ in (*FILMS, *self.extra_films):
            ids[name] = _mint()
        for name, _t, _y, _p, _f, seasons in SERIES:
            ids[name] = _mint()
            for s, n in seasons.items():
                ids[f"{name}/s{s}"] = _mint()
                for e in range(1, n + 1):
                    ids[f"{name}/s{s}e{e}"] = _mint()
        self.ids = ids
        self._publish_episodes()

    def rebuild(self, drop_provider_ids=(), move_prefix=None, partial=False) -> dict:
        """Every id re-minted; returns {name: (old id, new id)}."""
        old = dict(self.ids)
        self.dropped = tuple(drop_provider_ids)
        if move_prefix:
            self.prefix = move_prefix
        self.partial = partial
        if self.fj is not None:
            for sid in [old[n] for n, *_ in SERIES]:
                self.fj.episodes.pop(sid, None)
        self._mint_all()
        return {name: (old[name], self.ids[name]) for name in old if name in self.ids}

    def add_duplicate_film(self, name: str, like: str, folder: str) -> None:
        """A second film with the same title, year and provider ids as `like` (another library's copy)."""
        base = next(f for f in FILMS if f[0] == like)
        self.extra_films.append((name, base[1], base[2], dict(base[3]), folder))
        self.ids[name] = _mint()

    # ---- shapes ----
    def _providers(self, ids: dict) -> dict:
        return {k: v for k, v in ids.items() if k.lower() not in self.dropped}

    def _films(self):
        rows = [*FILMS, *self.extra_films]
        return rows[: max(1, len(rows) // 2)] if self.partial else rows

    def _series(self):
        return SERIES[:1] if self.partial else SERIES

    def snapshot(self, fetched_at: str) -> dict:
        """The connector's `jellyfin` data block (only the keys the index reads)."""
        movies, shows = [], []
        for name, title, year, prov, path in self._films():
            prov = self._providers(prov)
            row = {"title": title, "year": year, "jf_id": self.ids[name],
                   "item_key": f"tmdb:{prov['Tmdb']}" if prov.get("Tmdb") else f"jf:{self.ids[name]}",
                   "path": self.prefix + path}
            if prov.get("Imdb"):
                row["imdb"] = prov["Imdb"]
            movies.append(row)
        for name, title, year, prov, folder, _s in self._series():
            prov = self._providers(prov)
            key = (f"tmdb:{prov['Tmdb']}" if prov.get("Tmdb") else f"tvdb:{prov['Tvdb']}" if prov.get("Tvdb")
                   else f"jf:{self.ids[name]}")
            row = {"title": title, "year": year, "jf_id": self.ids[name], "item_key": key,
                   "path": self.prefix + folder}
            if prov.get("Tvdb"):
                row["tvdb"] = prov["Tvdb"]
            if prov.get("Imdb"):
                row["imdb"] = prov["Imdb"]
            shows.append(row)
        return {"movies": movies, "shows": shows, "library_fetched_at": fetched_at, "up_next": [], "now_playing": []}

    def episodes_of(self, name: str) -> list[dict]:
        _n, title, _y, _p, folder, seasons = next(s for s in SERIES if s[0] == name)
        out = []
        for s, n in seasons.items():
            for e in range(1, n + 1):
                out.append({"Id": self.ids[f"{name}/s{s}e{e}"], "Type": "Episode", "Name": f"Episode {e}",
                            "SeriesId": self.ids[name], "SeriesName": title, "SeasonId": self.ids[f"{name}/s{s}"],
                            "ParentIndexNumber": s, "IndexNumber": e, "ProviderIds": {},
                            "Path": f"{self.prefix}{folder}/Season {s:02d}/{title} S{s:02d}E{e:02d}.mkv"})
        return out

    def _publish_episodes(self) -> None:
        if self.fj is None:
            return
        for name, *_ in SERIES:
            self.fj.episodes[self.ids[name]] = self.episodes_of(name)
