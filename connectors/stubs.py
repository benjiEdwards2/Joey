"""Compatibility shim (C-04, 2026-10-09): the live connectors moved to `connectors/feeds/`,
one module per feed id, with the shared HTTP helper in `connectors/feeds/_http.py`.

This module only re-exports the names older imports use (`from connectors.stubs import
Jellyfin`, `MEDIA_APPS`, `STUBS`, ...). New code imports from `connectors.feeds.<id>`.
Re-exports are bindings, not aliases: monkeypatch a name in the feed module that uses it
(e.g. `connectors.feeds.system._read_proc`), not here. Registration happens in
`connectors.feeds`, which `connectors.registry` imports.
"""

from __future__ import annotations

from connectors.feeds import LIVE, PARKED
from connectors.feeds._common import FIXTURE_MEDIA_HOST, GIB, _ago, _dt, _duration_words, _now
from connectors.feeds._http import failure, http_json, reason
from connectors.feeds.arr import (
    ARR_APPS, ARR_COUNT_ENDPOINTS, ARR_LIMIT, ARR_WINDOW_DAYS, PROWLARR_ENV, PROWLARR_STATS, Arr,
    _arr_key, _arr_ref, _episode_code, _episode_title, _records, _timeleft, _upgrade_text,
)
from connectors.feeds.gcal import CALENDAR_WINDOW_DAYS, Gcal, _event, _iso, _when
from connectors.feeds.home_assistant import HomeAssistant, _unit
from connectors.feeds.jellyfin import (
    FIXTURE_HER_USER, HISTORY_FETCH_LIMIT, HISTORY_RECENT, HISTORY_TOP, LIBRARY_FETCH_LIMIT,
    PLAY_METHODS, TICKS_PER_HOUR, TICKS_PER_MINUTE, UP_NEXT_LIMIT, Jellyfin, _item_kind, _jf_art,
    _jf_key, _jf_levels, _jf_ref, _media_title, _play_method,
)
from connectors.feeds.jellyseerr import (
    SEERR_LIST_TAKE, SEERR_LOOKUP_CAP, SEERR_MEDIA_STATUS, SEERR_REQUEST_STATUS, SEERR_ROW_LIMIT,
    Jellyseerr, _seerr_kind, _seerr_status_text, _seerr_year,
)
from connectors.feeds.macromates import MacroMates
from connectors.feeds.media_status import MEDIA_APPS, MediaStatus
from connectors.feeds.nas_stats import NAS_RECENT_DAYS, NasStats, count_files
from connectors.feeds.open_meteo import OpenMeteo
from connectors.feeds.qbittorrent import (
    QBIT_ACTIVE_STATES, QBIT_ETA_INFINITE, QBIT_FINISHED_WINDOW, QBIT_PAUSED_STATES, QBIT_ROW_LIMIT,
    QBIT_SEEDING_STATES, QBittorrent, _bytes_text, _epoch_iso, _eta_text, _qbit_kind,
)
from connectors.feeds.system import (
    CPU_SAMPLE_S, HOST_PREFIX, PROC_ROOT, SYSTEM_VOLUMES_DEFAULT, System, _cpu_times, _gib,
    _read_proc, _uptime_words, _volume_label, _volume_labels,
)
from connectors.feeds.uptime_kuma import KUMA_ORDER, KUMA_STATUS, UptimeKuma, _kuma_parse
from connectors.feeds.wud import WUD_UPDATE_TRIGGER, Wud, wud_auto

STUBS = LIVE  # the pre-split name of the live tuple
