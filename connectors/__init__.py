"""Joey connectors — the write side of the frozen envelope contract (D13).

Every feed subclasses `base.Connector`, writes exactly one envelope per run to
`$SNAPSHOT_DIR/{id}.json`, and is driven by `run_all.py`: hourly, plus every 120 s for
jellyfin, media_status, qbittorrent, arr, system and uptime_kuma.
"""
