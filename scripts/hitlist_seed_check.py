"""Check that HITLIST.md covers every source item considered when it was seeded (JY-004).

Stdlib only. Run from anywhere:  python scripts/hitlist_seed_check.py

Each SOURCES entry is (source file, short item text, target, note).
  target = "JY-###"  -> the item has a row in HITLIST.md (several items may share one row = merged duplicates)
  target = "SKIP"    -> the item was left out; the note says why

Checks (all must hold for PASS):
  1. every JY id named below is an ID cell in HITLIST.md exactly once
  2. no ID appears twice in HITLIST.md
  3. every HITLIST row is named by at least one source entry (0 unmatched rows)
  4. every Status is one of the allowed words; `[x] ` leads the Status cell on shipped rows only
  5. every Spec cell is "—" (no spec files exist yet) or links a file that exists
  6. every table row has 7 cells
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HITLIST = ROOT / "HITLIST.md"
STATUSES = {"idea", "spec", "ready", "building", "review", "accept", "shipped", "parked"}

PLAN = "JOEYV2_PLAN.md section 4"
BL = "BACKLOG.md"
LH = "LifeDashboard HANDOVER.md"
DEF = "JoeyTV DEFERRED.md"
UI = "JoeyTV TV_UI_PLAN.md"
JH = "JoeyTV HANDOVER.md"
SR = "SERVER_REVIEW.md section 2"

SOURCES = [
    # ---- JoeyV2 plan, section 4 (one row each) ----
    (PLAN, "JY-001 repo CLAUDE.md", "JY-001", ""),
    (PLAN, "JY-002 PROCESS.md + templates", "JY-002", ""),
    (PLAN, "JY-003 PLAN.md", "JY-003", ""),
    (PLAN, "JY-004 HITLIST seeded", "JY-004", ""),
    (PLAN, "JY-005 tech-notes", "JY-005", ""),
    (PLAN, "JY-006 CI fast check", "JY-006", ""),
    (PLAN, "JY-007 repo settings + labels", "JY-007", ""),
    (PLAN, "JY-008 JoeyV2 docs into repo", "JY-008", ""),
    ("coordinator request (repo rename)", "JY-009 repo renamed to Joey", "JY-009", "added after the plan; not in section 4"),
    (PLAN, "JY-010 worktree helper", "JY-010", ""),
    (PLAN, "JY-011 close-out script", "JY-011", ""),
    (PLAN, "JY-012 preview slot", "JY-012", ""),
    (PLAN, "JY-013 budgets script", "JY-013", ""),
    (PLAN, "JY-014 hands bundle", "JY-014", ""),
    (PLAN, "JY-020 archive old files", "JY-020", ""),
    (PLAN, "JY-021 remove merged worktrees", "JY-021", ""),
    (PLAN, "JY-022 memory pointers", "JY-022", ""),
    (PLAN, "JY-030 stale Grouped comment", "JY-030", ""),
    (PLAN, "JY-031 P1b disk forecast", "JY-031", ""),
    (PLAN, "JY-040 W6 close + W7 sitting", "JY-040", ""),
    (PLAN, "JY-041 one-week check", "JY-041", ""),
    (PLAN, "JY-042 TV UI round (umbrella)", "JY-042", ""),
    (PLAN, "JY-049 transcode box research", "JY-049", ""),
    (PLAN, "JY-050 player spec", "JY-050", ""),
    (PLAN, "JY-051 player options study", "JY-051", ""),
    (PLAN, "JY-052 player options page", "JY-052", ""),
    (PLAN, "JY-053 playback-session contract", "JY-053", ""),
    (PLAN, "JY-054 web/phone player", "JY-054", ""),
    (PLAN, "JY-055 progress + resume sync", "JY-055", ""),
    (PLAN, "JY-056 track picker", "JY-056", ""),
    (PLAN, "JY-057 TV shell player", "JY-057", ""),
    (PLAN, "JY-058 friends' path + gate", "JY-058", ""),
    (PLAN, "JY-059 transcoding on the new box", "JY-059", ""),

    # ---- BACKLOG.md ----
    (BL, "Money / Track E", "JY-220", ""),
    (BL, "WP38 soak / runbook", "JY-210", ""),
    (BL, "Re-enable home_assistant / macromates / nas_stats", "JY-221", ""),
    (BL, "Posters", "JY-222", ""),
    (BL, "7-day forecast on weather glimpse", "SKIP", "DONE in E5 (note 2026-10-13)"),
    (BL, "Georgina's account / her Media view", "JY-223", ""),
    (BL, "Media speed: stale-while-revalidate", "SKIP", "DONE (note 2026-10-13; E1)"),
    (BL, "By-year rankings", "SKIP", "DECIDED 2026-10-09: delete"),
    (BL, "Grid-layout Media sections", "SKIP", "DECIDED 2026-10-09: delete"),
    (BL, "wt-icons / server-icons logo work", "SKIP", "DECIDED 2026-10-09: dropped"),
    (BL, "BOM radar", "SKIP", "DECIDED 2026-10-09: delete"),
    (BL, "Naming leftovers (Movies / My films / TV show; Not on server wording)", "JY-123", "TIDYUP 8.4: not decided"),
    (BL, "Unused style recipes / pre-commit guard / Server -> Activity", "SKIP", "DECIDED 2026-10-09"),
    (BL, "Uptime Kuma 1 -> 2 upgrade", "JY-200", ""),
    (BL, "Jellyseerr image frozen -> Seerr", "JY-201", "may already be done (Seerr 3.5.0 in use); row says verify"),
    (BL, "Homepage retirement (decided; script + Cloudflare cleanup not run)", "JY-209", "decision is made, the work is open"),
    (BL, "Off-box backup", "SKIP", "DECIDED 2026-10-09: no"),
    (BL, "Other NAS items (N-34, N-35, N-43, N-52, N-53)", "JY-202", ""),
    (BL, "7 pre-fix Jellyseerr requests unsent", "JY-211", ""),
    (BL, "DECISIONS index/HANDOVER rewrite (D-66, D-67)", "SKIP", "superseded by JY-020 (old files archived, not rewritten)"),
    (BL, "Open phone checks / first Follow / Update now / manifest colour", "JY-212", "merged with HANDOVER phone checks"),
    (BL, "Decided 2026-10-09 summary block", "SKIP", "decision record, not an item"),
    (BL, "qBit queue limits (8 / 12, slow torrents)", "JY-203", ""),
    (BL, "qBit interface tun0 + gluetun BLOCK_MALICIOUS=off", "JY-204", ""),
    (BL, "gluetun on latest dev build -> pin v3", "JY-205", ""),
    (BL, "Mullvad has no port forwarding (structural)", "SKIP", "superseded: Proton switch 2026-10-12 (note in the source)"),
    (BL, "E0 egress fix (tidyup_t0.sh, ADM IPv6 DNS)", "JY-206", "qBit cap DONE by B.; tidyup_t0.sh run 2026-10-18; left = ADM IPv6 DNS + deploy.sh pull retry; N-04 (dockerd --debug) was dropped by t0; merged with HANDOVER E0 line"),
    (BL, "E1 resilience + per-minute costs", "SKIP", "built, in main and deployed (HANDOVER 2026-10-22 close)"),
    (BL, "E2 UI polish batch", "SKIP", "built, in main and deployed"),
    (BL, "E3 first screens", "SKIP", "built, in main and deployed"),
    (BL, "E4 film page order + action row", "SKIP", "built, in main and deployed"),
    (BL, "E5 features batch 1 / E6 Wrapped / E7 Awards weight", "SKIP", "built, in main and deployed"),
    (BL, "Note: qBit item predates Proton switch", "SKIP", "note, not an item"),
    (BL, "Episode pages N to watch -> N left", "JY-100", "merged with HANDOVER 'Open / parked' line"),
    (BL, "media_pages.py:175 N h this month", "JY-101", "merged with HANDOVER 'Open / parked' line"),
    (BL, "Service page H1 = service name", "JY-102", "merged with HANDOVER 'Open / parked' line"),
    (BL, "Georgina's scores in the both view", "JY-103", "merged with HANDOVER 'Open / parked' line"),
    (BL, "Later: Cloudflare edge-cache rule", "JY-207", "merged with HANDOVER optional step 5"),
    (BL, "Later: per-container RAM (#9)", "JY-137", ""),
    (BL, "Later: S.M.A.R.T. into Attention (#10)", "JY-138", ""),
    (BL, "Later: Because you rated X 9 shelf", "JY-105", ""),
    (BL, "Later: read-only leaving soon list", "JY-106", ""),
    (BL, "Later: favourites synced to Jellyfin", "JY-107", ""),
    (BL, "Later: forecast beside timed events", "JY-160", ""),
    (BL, "Upgrades: profile-minimum hint only when every rejection", "JY-108", ""),
    (BL, "Upgrades: per-episode Why?", "JY-109", ""),
    (BL, "Upgrades: live rejections shape unverified", "JY-213", "merged with HANDOVER Why? on Brothers live check"),
    (BL, "Requests page 4K badge lag", "JY-110", ""),
    (BL, "Old arr profile id shows no Quality line", "JY-111", ""),
    (BL, "Quality chips hide when profile list unreadable", "JY-112", ""),
    (BL, "Server proposals P1-P10 (umbrella line)", "SKIP", "covered by the per-proposal rows (P1a/P2/P4 shipped, P1b = JY-031, P3 and P5-P10 = JY-130..136)"),
    (BL, "Disk forecast reaches Attention only (hub card + Discord)", "JY-031", "duplicate of 2026-10-22 P1b item; merged into the plan's pilot item"),
    (BL, "Sonarr-only seasons get no Seasons row", "JY-113", ""),
    (BL, "Recently added / hub progress words lack season state", "JY-114", ""),
    (BL, "WUD check interval vs 180-min Stale rule", "JY-142", ""),
    (BL, "Prowlarr indexerstats window", "JY-143", "merged with HANDOVER tidy-round Prowlarr count check"),
    (BL, "media_status connector keeps episodes: 0 series", "JY-115", ""),
    (BL, "Gated hostnames per app", "JY-139", "merged with 4 HANDOVER mentions"),
    (BL, "Health rows do not say LAN", "JY-140", ""),
    (BL, "Season page head eyebrow + S-switch", "JY-116", "merged with HANDOVER episodes 'Open'"),
    (BL, "Previous / Next cards verify", "JY-117", "merged with HANDOVER episodes 'Open'"),
    (BL, "Guest / crew names plain text", "JY-118", "merged with HANDOVER episodes 'Open'"),
    (BL, "Off-server shows no episode ratings", "JY-119", "merged with HANDOVER episodes 'Open'"),
    (BL, "Song-category / awards parser leftovers pointer", "SKIP", "pointer to the awards section; row is JY-152"),
    (BL, "Awards: page height at 375 px", "JY-150", ""),
    (BL, "Awards: long TV pill names", "JY-151", ""),
    (BL, "Awards: year strip in picker sheet", "SKIP", "DONE 2026-10-16 (struck through in the source)"),
    (BL, "Awards: year coverage report re-run (dim years)", "JY-154", "merged with backlog fill / HANDOVER awards kick"),
    (BL, "Awards parser leftovers (5 small)", "JY-152", "merged with HANDOVER awards 'Known leftovers'"),
    (BL, "Awards: N on your watchlist refreshes on reload only", "JY-153", ""),
    (BL, "Awards: placeholder posters until backlog fill", "JY-154", ""),
    (BL, "Awards: archive three review mockups", "JY-216", ""),
    (BL, "Library grid: her view 'Nothing left to watch'", "JY-120", "merged with HANDOVER 'Nothing in progress' line"),
    (BL, "tv.css:99 Grouped comment", "JY-030", "duplicate of the plan's pilot item"),
    (BL, "Other sessions' merged worktrees (5)", "JY-021", "covered by the plan's worktree clean-up"),
    (BL, "P1b disk forecast off the page", "JY-031", "same item as the plan's JY-031"),
    (BL, "P4 QUIET_MBPS vs live cap", "JY-141", "merged with HANDOVER server-assist env step"),
    (BL, "P2 unverified live (first digest text)", "JY-214", "merged with HANDOVER server-assist live checks"),
    (BL, "P3, P5-P10 unpicked (pointer)", "SKIP", "covered by SERVER_REVIEW rows JY-130..136"),

    # ---- LifeDashboard HANDOVER.md ----
    (LH, "Eval round: push + deploy (B.'s hands 1-2)", "SKIP", "pushed and deployed (2026-10-22 close)"),
    (LH, "Eval round: live check on the phone (hands 3)", "JY-213", "merged"),
    (LH, "Eval round: delete merged worktrees (hands 4)", "JY-021", "merged"),
    (LH, "Eval round: optional Cloudflare edge cache (hands 5)", "JY-207", "merged"),
    (LH, "Eval: E0 tidyup_t0.sh + ADM IPv6 DNS still open", "JY-206", "merged"),
    (LH, "Open: N to watch / Georgina scores / H1 / media_pages:175", "JY-100", "merged with BACKLOG (see JY-100..103)"),
    (LH, "Open: episode runtimes come from recorded plays", "JY-104", ""),
    (LH, "Open: phone checks only B. can do", "JY-212", "merged"),
    (LH, "Library grid 10-13: push + deploy", "SKIP", "rescued and pushed 2026-10-22"),
    (LH, "Library grid 10-13: filter chips wrap at 375 px", "SKIP", "fixed in the rescue (one scrolling row)"),
    (LH, "Library grid: her TV Continue watching 'Nothing in progress'", "JY-120", "merged"),
    (LH, "Nav tidy: her rows in Everyone show B.'s picker", "SKIP", "fixed in the library-grid rescue (live check says no picker)"),
    (LH, "Nav tidy: merge play stats into History", "JY-121", ""),
    (LH, "Nav tidy: manifest shortcut TV Shows", "JY-122", ""),
    (LH, "Nav tidy: unused tab_counts read", "JY-217", ""),
    (LH, "Nav tidy: phone eyes-on of Activity row", "JY-212", "merged"),
    (LH, "Server assist 10-22: deploy.sh run (hands 1)", "SKIP", "main carried by later NAS deploys (JoeyTV HANDOVER: main a2b43d5 deployed)"),
    (LH, "Server assist: DIGEST_AT / QUIET_MBPS env (hands 2)", "JY-141", "merged"),
    (LH, "Server assist: live checks Quiet tap, digest, Free space (hands 3)", "JY-214", "merged"),
    (LH, "Server assist: remove worktrees (hands 4)", "JY-021", "merged"),
    (LH, "Server assist: P1b held", "JY-031", "merged"),
    (LH, "Server assist: P3, P5-P10 unpicked", "SKIP", "covered by JY-130..136"),
    (LH, "Library grid rescue 10-22: deploy (hands)", "SKIP", "carried by later deploys"),
    (LH, "Library grid rescue: live checks (Suggestions, Caught up, sorts)", "JY-213", "merged"),
    (LH, "Library grid rescue: other merged worktrees left", "JY-021", "merged"),
    (LH, "Closed session: pick from Server proposals", "SKIP", "covered by JY-130..136 and JY-031"),
    (LH, "Closed session: gated hostnames", "JY-139", "merged"),
    (LH, "Closed session: remove merged worktrees", "JY-021", "merged"),
    (LH, "Closed session: live checks 4K request, Why? Brothers, WAR, Updates", "JY-213", "Updates 'checked N ago' part also in JY-214"),
    (LH, "Closed session: stale launch.json previews", "JY-215", ""),
    (LH, "Upgrades 10-21: push (hands)", "SKIP", "IN MAIN and DEPLOYED"),
    (LH, "Upgrades 10-21: live checks Brothers row, Why?", "JY-213", "merged"),
    (LH, "Request quality 10-21: push (hands)", "SKIP", "IN MAIN"),
    (LH, "Request quality: live checks 4K request, Open links", "JY-213", "merged"),
    (LH, "Request quality: open items (badge lag, old id, chips)", "JY-110", "merged with BACKLOG (JY-110..112)"),
    (LH, "Tidy round 10-19: push + deploy (hands 1-2)", "SKIP", "IN MAIN"),
    (LH, "Tidy round: awards backlog kick (hands 3)", "JY-154", "merged"),
    (LH, "Tidy round: live checks WAR, Caught up, hub cards, Server bands, Prowlarr", "JY-214", "Media-side checks in JY-213"),
    (LH, "Tidy round: pick from P1-P10 (hands 5)", "SKIP", "covered by JY-130..136"),
    (LH, "Tidy round: remove merged worktrees (hands 6)", "JY-021", "merged"),
    (LH, "Tidy round: open after (Sonarr-only seasons etc.)", "JY-113", "merged with BACKLOG (JY-113..115, 139, 142, 143)"),
    (LH, "Health logos: push + deploy", "SKIP", "carried inside the tidy branch, IN MAIN"),
    (LH, "Health logos: gated hostnames note", "JY-139", "merged"),
    (LH, "Episodes 10-16: push + deploy, phone check (open a show twice)", "JY-213", "push part SKIP (in main)"),
    (LH, "Episodes: open items (eyebrow, prev/next, names, ratings)", "JY-116", "merged with BACKLOG (JY-116..119)"),
    (LH, "Awards round 2: push + deploy + backlog kick + coverage re-run", "JY-154", "push/deploy part SKIP (in main)"),
    (LH, "Awards round 2: known leftovers", "JY-152", "merged"),
    (LH, "Ballot 10-14: phone checks (sheet padding, sticky row, sentinel, button, height)", "JY-212", "merged; page-height decision is JY-150"),
    (LH, "Ballot: open page height / pill names / year strip", "JY-150", "merged with BACKLOG (JY-150, JY-151)"),
    (LH, "Working notes (preview, pattern, clock tests)", "SKIP", "notes, not items"),

    # ---- JoeyTV DEFERRED.md ----
    (DEF, "D1 F7 NAS 24/7", "JY-170", ""),
    (DEF, "D2 go-gate metrics", "JY-040", "covered by the W6 soak inside JY-040"),
    (DEF, "D3 4K bitrate-cap read", "JY-171", ""),
    (DEF, "D4 Georgina's Access JWT audit half 2", "JY-172", ""),
    (DEF, "D5 transcoded stream during a deploy", "JY-173", ""),
    (DEF, "D6 Fire TV paths", "JY-174", ""),
    (DEF, "D7 external uptime monitor", "JY-175", ""),
    (DEF, "D8 swappiness boot hook", "SKIP", "DONE 2026-10-20, PASS 2026-10-23"),
    (DEF, "D9 Kuma metrics failed on /server", "JY-144", "merged with JoeyTV HANDOVER follow-on"),
    (DEF, "D10 7-day owner follow-up", "JY-176", "merged with JoeyTV HANDOVER queue"),
    (DEF, "D11 clean-TV store path", "JY-177", ""),
    (DEF, "D12 play-row duplicate cleanup", "SKIP", "DONE 2026-10-21"),
    (DEF, "D13 forced update no Later", "JY-178", ""),
    (DEF, "D14 update tamper test + Settings Back", "JY-179", ""),
    (DEF, "D15 cache/updates empty after self-update", "JY-180", ""),
    (DEF, "D16 W5 hotspot stretch", "SKIP", "DONE 2026-10-22/23"),

    # ---- JoeyTV TV_UI_PLAN.md ----
    (UI, "U1 Back memory", "JY-187", ""),
    (UI, "U2 Hero scrim + type floor + scale", "JY-188", ""),
    (UI, "U3 Posters at 400 + Tonight", "JY-189", ""),
    (UI, "U4 Server fixes", "JY-190", ""),
    (UI, "U5 Shell Back", "JY-191", ""),
    (UI, "U6 Series + episodes", "JY-192", ""),
    (UI, "U7 Shelves + TMDB page", "JY-193", ""),
    (UI, "U8 Discover search", "JY-194", ""),
    (UI, "U9 Overview + empty states", "JY-195", ""),
    (UI, "U10 Diary + Awards on TV", "JY-196", ""),
    (UI, "U11 Docs", "JY-197", ""),
    (UI, "Open decisions 1-8 (Gate 1 picks, scale, approve Wave 1)", "JY-186", ""),

    # ---- JoeyTV HANDOVER.md (top sections) ----
    (JH, "TV UI review: Gate 1 picks open", "JY-186", "merged"),
    (JH, "TV UI review handed to JoeyV2 as JY-042", "JY-042", "merged"),
    (JH, "Docs PR for Downloader wording", "JY-181", ""),
    (JH, "First friend's TV invite", "JY-182", ""),
    (JH, "W6 / WP-Z: soak, test-account revoke drill, F7", "JY-040", "F7 part = JY-170"),
    (JH, "Coordinator queue: 7-day owner follow-up", "JY-176", "merged"),
    (JH, "Coordinator queue: go-gate 10-28, step 12 sweep, step 14 GO", "SKIP", "go-gate skipped by B. 2026-10-21; Phase B GO given; soak = JY-040"),
    (JH, "Coordinator queue: step 13 test-account disable", "JY-040", "WP-Z part"),
    (JH, "Desktop key files to delete once password manager holds the key", "JY-185", ""),
    (JH, "Revisit the 20 Mbps cap if 2 streams wanted", "JY-183", ""),
    (JH, "Friend session visible in B.'s now-playing view", "JY-184", ""),
    (JH, "Duplicate HSTS header", "SKIP", "fixed (one HSTS header after the ca51964 deploy)"),
    (JH, "MASTER_PLAN Q3 line / G5 loop header text", "SKIP", "MASTER_PLAN is archived by JY-020"),
    (JH, "Deploy-time clock-fix PR note (no deploy 23:45-00:00 UTC)", "SKIP", "later deploys passed; not marked open"),
    (JH, "Q42 pilot device list from B.", "SKIP", "answered 2026-10-21 (Samsung Frame -> Google TV stick)"),
    (JH, "Flagged: shared clone on another branch", "SKIP", "covered by JY-010 / JY-021 (one worktree per item)"),
    (JH, "Flagged: NAS runs a TailScale container", "JY-208", ""),

    # ---- SERVER_REVIEW.md section 2 ----
    (SR, "P1 Disk forecast + free space", "SKIP", "P1a shipped; P1b = JY-031"),
    (SR, "P2 Overnight digest", "SKIP", "shipped"),
    (SR, "P3 One-tap fixes on Attention", "JY-130", ""),
    (SR, "P4 Quiet mode toggle", "SKIP", "shipped (cap mismatch = JY-141)"),
    (SR, "P5 Internet health card", "JY-131", ""),
    (SR, "P6 Backups card", "JY-132", ""),
    (SR, "P7 Service history on the card", "JY-133", ""),
    (SR, "P8 What changed since your last visit", "JY-134", ""),
    (SR, "P9 Per-person notifications", "JY-135", ""),
    (SR, "P10 Weekly summary", "JY-136", ""),
    ("JY-006 builder report (2026-10-23)", "flaky test_metadata_long_request_state_short", "JY-224", "found under -n 16 load"),
    ("JY-006 builder report (2026-10-23)", "flaky test_runner_history_tail 2 ms limit", "JY-225", "found under -n 16 load"),
    ("JY-013 live run (2026-10-23)", "/a/server warm p95 over 50 ms", "JY-226", "measured twice: 52 and 56 ms"),
    ("JY-013 live run (2026-10-23)", "full deploy gate 15.3 min over 10 min", "JY-227", "history.log dur=918s"),
]


def parse_hitlist(text):
    """Return (rows, problems). rows = list of dicts, one per table data row."""
    rows, problems = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| ") or line.startswith("| ID ") or line.startswith("| ---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            problems.append(f"line {n}: {len(cells)} cells, expected 7")
            continue
        m = re.fullmatch(r"(JY-\d{3})", cells[0])
        if not m:
            problems.append(f"line {n}: bad ID cell {cells[0]!r}")
            continue
        status = cells[4]
        if status.startswith("[x] "):
            if status != "[x] shipped":
                problems.append(f"line {n}: [x] on a row that is not shipped")
            status = status[4:]
        elif status == "shipped":
            problems.append(f"line {n}: shipped row without [x]")
        rows.append({"id": m.group(1), "status": status, "spec": cells[6], "line": n})
    return rows, problems


def main():
    text = HITLIST.read_text(encoding="utf-8")
    rows, problems = parse_hitlist(text)
    ids = [r["id"] for r in rows]

    counts = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    for i, c in counts.items():
        if c != 1:
            problems.append(f"{i} appears {c} times in HITLIST.md")

    for r in rows:
        if r["status"] not in STATUSES:
            problems.append(f"{r['id']}: status {r['status']!r} not allowed")
        spec = r["spec"]
        if spec != "—":
            m = re.search(r"\(([^)]+)\)", spec)
            if not m or not (ROOT / m.group(1)).exists():
                problems.append(f"{r['id']}: spec link missing or file not found ({spec})")

    named = OrderedDict()
    skipped = []
    for src, item, target, note in SOURCES:
        if target == "SKIP":
            skipped.append((src, item, note))
            continue
        named.setdefault(target, []).append((src, item))
        if counts.get(target, 0) != 1:
            problems.append(f"source item {item!r} ({src}) -> {target}: row count {counts.get(target, 0)}, expected 1")

    unmatched = [i for i in ids if i not in named]
    for i in unmatched:
        problems.append(f"HITLIST row {i} has no source item")

    merged = {i: v for i, v in named.items() if len(v) > 1}
    plan_rows = [i for i in ids if int(i[3:]) < 100]
    imported_rows = [i for i in ids if int(i[3:]) >= 100]

    print("HITLIST seed check")
    print(f"  rows in HITLIST.md      : {len(ids)} (set-up {len(plan_rows)}, imported {len(imported_rows)})")
    print(f"  source items considered : {len(SOURCES)}")
    print(f"  mapped to a row         : {len(SOURCES) - len(skipped)} items -> {len(named)} distinct rows")
    print(f"  skipped                 : {len(skipped)}")
    print(f"  rows with no source     : {len(unmatched)}")
    print()
    print("Merged rows (more than one source item):")
    for i, v in merged.items():
        print(f"  {i}: " + "; ".join(f"{s.split()[0]} {it}" for s, it in v))
    print()
    print("Skipped items:")
    for src, item, note in skipped:
        print(f"  [{src}] {item} -- {note}")
    print()
    if problems:
        print("FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
