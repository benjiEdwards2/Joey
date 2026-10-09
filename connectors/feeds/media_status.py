"""Media / Server app probes: is each app on the NAS answering at all."""

from __future__ import annotations

import os

from connectors.base import Connector, mode
from connectors.feeds._common import FIXTURE_MEDIA_HOST
from connectors.feeds._http import reason


# The Media area's app list (hard-coded by decision 2026-10-05): id, display
# name, port, health path. Any HTTP answer counts as up — a 401 still means the
# app is alive (qBittorrent), and redirects are not followed, so a 30x (ADM's
# http -> https bounce) is up too; only no answer or a 5xx is down.
# wud, adm, gluetun, homepage joined 2026-10-06 (WP-S2) for the Server area.
MEDIA_APPS = (
    {"id": "jellyfin", "name": "Jellyfin", "port": 8096, "path": "/health"},
    {"id": "radarr", "name": "Radarr", "port": 7878, "path": "/ping"},
    {"id": "sonarr", "name": "Sonarr", "port": 8989, "path": "/ping"},
    {"id": "jellyseerr", "name": "Jellyseerr", "port": 5055, "path": "/api/v1/status"},
    {"id": "prowlarr", "name": "Prowlarr", "port": 9696, "path": "/ping"},
    {"id": "qbittorrent", "name": "qBittorrent", "port": 8080, "path": "/api/v2/app/version"},
    # Gluetun's control server (8000) lives inside its own network namespace and is
    # NOT published, so it is never probed. Rule: gluetun is Up iff prowlarr OR
    # qbittorrent answers — both are routed through gluetun, so either answering
    # proves the VPN container is alive. Its link is qBittorrent's (the UI behind it).
    {"id": "gluetun", "name": "Gluetun", "port": 8080, "path": None,
     "via": ("prowlarr", "qbittorrent")},
    {"id": "uptime_kuma", "name": "Uptime Kuma", "port": 3001, "path": "/"},
    {"id": "portainer", "name": "Portainer", "port": 9000, "path": "/api/status"},
    {"id": "wud", "name": "WUD", "port": 3030, "path": "/"},
    {"id": "adm", "name": "ADM", "port": 8000, "path": "/"},  # Asustor ADM web UI, plain http
    {"id": "homepage", "name": "Homepage", "port": 3000, "path": "/"},
)


def probe_targets() -> dict[str, tuple[str, int]]:
    """MEDIA_STATUS_HOSTS `app=host[:port][,app=host[:port]]` -> {app: (host, port)} (N-09):
    where to PROBE an app from inside Docker once Joey shares the media stack's network, e.g.
    `jellyfin=jellyfin,qbittorrent=gluetun,prowlarr=gluetun,wud=wud:3000` (the port defaults
    to the app's published one; give it when the container port differs, as WUD's does).
    Only the probe moves: the card `href` stays MEDIA_STATUS_HOST + the published port, so
    the link still works from a phone on the LAN. Unknown ids and bad pairs are ignored."""
    ports = {app["id"]: app["port"] for app in MEDIA_APPS if "via" not in app}
    targets = {}
    for pair in (os.environ.get("MEDIA_STATUS_HOSTS") or "").split(","):
        app, sep, where = (s.strip() for s in pair.partition("="))
        host, colon, port = where.partition(":")
        if not (sep and app in ports and host.strip()) or (colon and not port.strip().isdigit()):
            continue
        targets[app] = (host.strip(), int(port) if colon else ports[app])
    return targets


class MediaStatus(Connector):
    id = "media_status"
    requires_env = ("MEDIA_STATUS_HOST",)

    def fetch(self) -> list[dict]:
        from concurrent.futures import ThreadPoolExecutor

        import requests

        host = os.environ["MEDIA_STATUS_HOST"]
        targets = probe_targets()

        def probe(app: dict) -> dict:
            up, note = False, None
            where, port = targets.get(app["id"], (host, app["port"]))
            try:
                response = requests.get(f"http://{where}:{port}{app['path']}",
                                        timeout=5, allow_redirects=False)
                up = response.status_code < 500
                if not up:
                    note = f"HTTP {response.status_code}"
            except Exception as exc:  # one app failing never fails the run
                note = reason(exc)
            return {"id": app["id"], "up": up, "note": note}

        # A status probe, not a JSON fetch: any answer below 500 is up, so it calls requests
        # directly (one call per app, no connection to reuse) and shares only `reason`.
        # Six probes at a time (C-12): one after another, 5 s timeouts stretched the fast loop
        # to ~55 s. map() keeps MEDIA_APPS order; transform rebuilds it from MEDIA_APPS anyway.
        probes = [app for app in MEDIA_APPS if "via" not in app]  # derived apps are never probed
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(probe, probes))
        probed = {r["id"]: r["up"] for r in results}
        for app in MEDIA_APPS:
            if "via" in app:
                up = any(probed.get(v) for v in app["via"])
                results.append({"id": app["id"], "up": up,
                                "note": None if up else "no answer via Prowlarr or qBittorrent"})
        return results

    def transform(self, raw: list[dict]) -> dict:
        host = FIXTURE_MEDIA_HOST if mode() == "fixture" else os.environ["MEDIA_STATUS_HOST"]
        probes = {p["id"]: p for p in raw}
        apps = []
        for app in MEDIA_APPS:
            probe = probes.get(app["id"], {"up": False, "note": "no result"})
            apps.append({
                "id": app["id"],
                "name": app["name"],
                "href": f"http://{host}:{app['port']}",
                "up": bool(probe["up"]),
                "status_text": "Up" if probe["up"] else "Down",
                "note": None if probe["up"] else probe.get("note"),
            })
        down = [a["name"] for a in apps if not a["up"]]
        return {
            "summary": f"{len(apps) - len(down)} of {len(apps)} up",
            "secondary": f"Down: {', '.join(down)}" if down else "All apps up",
            "apps": apps,
        }
