"""The live connectors, one module per feed id (C-04).

Each module holds one `Connector` subclass: its `transform()` (written in WP23 against the
committed fixtures) and, for every live feed, its `fetch()`. Every live HTTP call goes
through `_http.http_json` with one `requests.Session` per run (C-05); helpers several
feeds share live in `_common`.

Every `data` block carries the hub display convention: a required `summary` string plus an
optional `secondary` line (D17, WP18) on top of the feed's own fields. ClickUp has no
connector — removed from v1 (2026-08-25). Money is Track E's importer, not a Connector (D14).

Importing this package registers every connector with `connectors.registry`.
"""

from __future__ import annotations

from connectors import registry
from connectors.base import Connector
from connectors.feeds.arr import Arr
from connectors.feeds.gcal import Gcal
from connectors.feeds.home_assistant import HomeAssistant
from connectors.feeds.jellyfin import Jellyfin
from connectors.feeds.jellyseerr import Jellyseerr
from connectors.feeds.macromates import MacroMates
from connectors.feeds.media_status import MediaStatus
from connectors.feeds.nas_stats import NasStats
from connectors.feeds.open_meteo import OpenMeteo
from connectors.feeds.qbittorrent import QBittorrent
from connectors.feeds.system import System
from connectors.feeds.uptime_kuma import UptimeKuma
from connectors.feeds.wud import Wud

LIVE: tuple[type[Connector], ...] = (
    OpenMeteo, Gcal, Jellyfin, MediaStatus, Arr, Jellyseerr, QBittorrent,
    System, Wud, UptimeKuma,  # Server area (2026-10-06)
)

# Parked (2026-10-09, C-01): no live fetch() yet. Their ids stay in the frozen D13 enum and
# their transforms/fixtures/schemas stay; live sweeps skip them until their requires_env are
# all set (registry.connector_ids). Fixture mode still builds them for the sample sweep.
PARKED: tuple[type[Connector], ...] = (MacroMates, HomeAssistant, NasStats)

for _cls in LIVE:
    registry.register(_cls, _cls.id)
for _cls in PARKED:
    registry.register(_cls, _cls.id, parked=True)
