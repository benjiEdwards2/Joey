"""JY-051 sitting runner: drive the TV half of the player study by adb and fill docs/specs/JY-051-matrix.md.

    python scripts/jy051_sitting.py check                  adb, TV and APK (nothing is changed)
    python scripts/jy051_sitting.py fetch-apk [--run ID]   download the Joey Study APK from the jy051-study workflow
    python scripts/jy051_sitting.py install                adb install the APK (an older copy is removed first)
    python scripts/jy051_sitting.py tv [--engines ...]     B. signs in on the TV; T1, T2, T2F, T2H on every test
                                                           file, then (OK on the remote) the resume test; logcat
    python scripts/jy051_sitting.py resume-tv              the resume test alone (B. signs in again)
    python scripts/jy051_sitting.py ingest FILE [...]      the study page's copied results (PC, phone)
    python scripts/jy051_sitting.py matrix                 rebuild the matrix from everything collected
    python scripts/jy051_sitting.py uninstall              remove the app
    python scripts/jy051_sitting.py sitting                check, install, tv (with the resume test), matrix
Every command takes --dry-run (print the adb lines, run nothing).

Laptop only. Talks to the TV by adb (B.'s TCL, Wireless debugging, serial as in the JoeyTV scripts) and to GitHub by
`gh`; never to Jellyfin or the NAS itself (the app on the TV does the Jellyfin reads). It handles no credential:
B. signs in as joeytest on the TV app's own screen (B. 2026-10-24: the study uses joeytest), the app keeps the
session in memory and signs out at the end. Collected results (item ids, timings, codec facts; no URLs, titles or
users) go to ~/.joey/jy051/ (env JY051_DIR); the matrix goes to docs/specs/JY-051-matrix.md between its markers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from player_study import TEST_ITEMS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MATRIX = REPO / "docs" / "specs" / "JY-051-matrix.md"
START, END = "<!-- jy051:matrix:start -->", "<!-- jy051:matrix:end -->"
PKG = "net.joeyhome.study"
ACTIVITY = f"{PKG}/.StudyActivity"
GH_REPO = "benjiEdwards2/Joey"
WORKFLOW = "jy051-study.yml"
BRANCH = "feat/JY-051-player-options"
ARTIFACT = "joey-study-apk"
LOOK_ROWS = (6, 7, 8, 11, 12)
BUDGET_MS = {"LAN": 5000, "Remote": 10000}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
LINE_RE = re.compile(r"\bJY051\s*:\s(\{.*\})\s*$")
TESTS = {i + 1: t[1] for i, t in enumerate(TEST_ITEMS)}
IDS = {i + 1: t[0] for i, t in enumerate(TEST_ITEMS)}
CANDIDATE = {("PC", "W1"): "W1", ("PC", "W2"): "W2", ("Phone", "W1"): "P1-W1", ("Phone", "W2"): "P1-W2",
             ("TV", "W1"): "T1-W1", ("TV", "W2"): "T1-W2", ("TV", "T2"): "T2", ("TV", "T2F"): "T2F",
             ("TV", "T2H"): "T2H"}
ORDER = ["W1", "W2", "P1-W1", "P1-W2", "T1-W1", "T1-W2", "T2", "T2F", "T2H"]
DEVICES = ["PC", "Phone", "TV"]


# ---------------------------------------------------------------- pure helpers (unit-tested)

def state_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("JY051_DIR") or "~/.joey/jy051"))


def parse_logcat(lines) -> list[dict]:
    """JSON records from `adb logcat -s JY051` lines; anything else is ignored."""
    out = []
    for line in lines:
        m = LINE_RE.search(line.rstrip("\r\n"))
        if not m:
            continue
        try:
            rec = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind"):
            out.append(rec)
    return out


def is_final_done(rec: dict) -> bool:
    """The app's last line (after sign-out): kind done with no engine (the page's T1 'done' has engine T1) and no
    phase (the matrix half's 'done' has phase matrix)."""
    return rec.get("kind") == "done" and not rec.get("engine") and not rec.get("phase")


def extract_web(text: str) -> list[dict]:
    """Every study-page results blob ({"v":1,"kind":"jy051-web",...}) found in pasted text."""
    dec, out, i = json.JSONDecoder(), [], 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and obj.get("kind") == "jy051-web":
            out.append(obj)
            i = end
        else:
            i += 1


def clean_record(rec: dict) -> dict | None:
    """Keep a run / resume record only if it names a test file; strip any URL that slipped into a text field."""
    if rec.get("kind") not in ("run", "resume", "resume_stop"):
        return None
    n = rec.get("n")
    if not isinstance(n, int) or n not in IDS or rec.get("id") != IDS[n]:
        return None
    out = {}
    for k, v in rec.items():
        if isinstance(v, str):
            v = re.sub(r"https?://\S+", "<url>", v)[:200]
        out[k] = v
    return out


def dedupe(records: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in records:
        key = json.dumps(r, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def candidate(rec: dict) -> str | None:
    return CANDIDATE.get((rec.get("device"), rec.get("engine")))


def first_frame(rec: dict) -> float | None:
    v = rec.get("ms_frame")
    if not isinstance(v, (int, float)):
        v = rec.get("ms_playing")
    return float(v) if isinstance(v, (int, float)) else None


def aggregate(records: list[dict]) -> dict:
    """(device, candidate, network, n) -> runs, ok, median_ms, method, reasons, audio, sub, verdict, err."""
    cells: dict[tuple, dict] = {}
    for r in records:
        if r.get("kind") != "run":
            continue
        cand = candidate(r)
        if not cand:
            continue
        key = (r["device"], cand, r.get("network") or "LAN", r["n"])
        c = cells.setdefault(key, {"runs": 0, "ok": 0, "times": [], "method": "", "reasons": [], "audio": "",
                                   "sub": "", "text": "", "verdict": "", "err": "", "vdec": "", "adec": "",
                                   "amime": "", "note": ""})
        c["runs"] += 1
        if r.get("ok"):
            c["ok"] += 1
            t = first_frame(r)
            if t is not None:
                c["times"].append(t)
        elif r.get("err"):
            c["err"] = r["err"]
        for k in ("method", "audio", "sub", "text", "vdec", "adec", "amime", "note"):
            if r.get(k):
                c[k] = r[k]
        if r.get("reasons"):
            c["reasons"] = list(r["reasons"])
        if r.get("verdict") in ("yes", "no"):
            c["verdict"] = r["verdict"]
    for c in cells.values():
        c["median_ms"] = statistics.median(c["times"]) if c["times"] else None
    return cells


SHORT = {"Direct (as is)": "", "DirectPlay": "DP", "DirectStream": "DS", "Remux": "remux", "Remux+Audio": "remux+A",
         "Transcode": "TRANSCODE", "None": "none"}


def cell_text(c: dict, network: str) -> str:
    if not c["ok"]:
        return f"FAIL {c['err'] or '?'}"[:60]
    s = f"{c['median_ms'] / 1000:.1f} s" if c["median_ms"] is not None else "played"
    if c["ok"] < c["runs"]:
        s += f" ({c['ok']}/{c['runs']})"
    m = SHORT.get(c["method"], c["method"])
    if m:
        s += f" {m}"
    audio = c["audio"]
    if audio.startswith("unsupported") or audio in ("none decoded", "none selected", "no track", "none"):
        s += " no-audio"
    if c["median_ms"] is not None and c["median_ms"] > BUDGET_MS.get(network, 5000):
        s += " OVER"
    if c["verdict"]:
        s += " ok-eye" if c["verdict"] == "yes" else " BAD-eye"
    return s


def resume_rows(records: list[dict]) -> list[str]:
    stops = [r for r in records if r.get("kind") == "resume_stop"]
    resumes = [r for r in records if r.get("kind") == "resume"]
    if not stops and not resumes:
        return ["Not run yet."]
    lines = []
    stop = stops[-1]["position_s"] if stops else None
    if stop is not None:
        lines.append(f"- TV stopped row 1 at {stop // 60}:{stop % 60:02d}.")
    for r in resumes:
        saved = r.get("saved_s")
        verdict = ""
        if stop is not None and isinstance(saved, int):
            verdict = " PASS" if abs(saved - stop) <= 10 else f" FAIL ({abs(saved - stop)} s apart)"
        lines.append(f"- {r.get('device')} ({r.get('network')}) saw saved position {saved} s, started at "
                     f"{r.get('started_s')} s after {r.get('ms_playing')} ms.{verdict}")
    return lines


def render_matrix(records: list[dict], sessions: list[dict], when: str) -> str:
    cells = aggregate(records)
    lines = [f"Generated {when} by `python scripts/jy051_sitting.py matrix` from {len(records)} records.",
             "Cell: median press-to-first-frame (ok runs / all if any failed), play method (DP direct play, "
             "remux, remux+A = audio transcoded, TRANSCODE = video), `no-audio` when no audio track decoded, "
             "`OVER` past the budget (LAN 5 s, remote 10 s), `ok-eye` / `BAD-eye` = B.'s verdict on the hard rows. "
             "`FAIL <reason>` = no first frame.", ""]
    for device in DEVICES:
        cols = sorted({(k[1], k[2]) for k in cells if k[0] == device},
                      key=lambda cn: (ORDER.index(cn[0]), cn[1] != "LAN"))
        lines.append(f"### {device}")
        if not cols:
            lines += ["Not measured yet.", ""]
            continue
        lines.append("| # | Tests | " + " | ".join(f"{c} {n}" for c, n in cols) + " |")
        lines.append("|---|---|" + "---|" * len(cols))
        for n in sorted(TESTS):
            row = [cell_text(cells[(device, c, net, n)], net) if (device, c, net, n) in cells else "-" for c, net in cols]
            lines.append(f"| {n} | {TESTS[n]} | " + " | ".join(row) + " |")
        lines += ["", "<details><summary>Per cell: method reasons, tracks, decoders</summary>", ""]
        for (dv, c, net, n), cell in sorted(cells.items(), key=lambda kv: (kv[0][3], ORDER.index(kv[0][1]), kv[0][2])):
            if dv != device:
                continue
            bits = [f"{cell['method'] or '-'}"]
            if cell["reasons"]:
                bits.append("reasons " + ",".join(cell["reasons"]))
            for k in ("audio", "sub", "text", "vdec", "adec", "amime", "note"):
                if cell[k]:
                    bits.append(f"{k} {cell[k]}")
            lines.append(f"- {n} {c} {net}: " + "; ".join(bits))
        lines += ["", "</details>", ""]
    lines.append("### Resume across devices (row 1)")
    lines += resume_rows(records)
    lines += ["", "### Devices"]
    if not sessions:
        lines.append("No session records yet.")
    for s in sessions:
        if s.get("device") == "TV":
            lines.append(f"- TV: {s.get('model', '?')}, Android SDK {s.get('sdk', '?')}, WebView {s.get('webview', '?')}; "
                         f"decoders video {','.join(s.get('video') or [])}, audio {','.join(s.get('audio') or [])}; "
                         f"with FFmpeg {','.join(s.get('audio_ffmpeg') or [])}; HDR types {s.get('hdr_types')}")
        else:
            caps = s.get("caps") or {}
            yes = lambda m: ",".join(k for k, v in (m or {}).items() if v) or "none"  # noqa: E731
            lines.append(f"- {s.get('device')} ({s.get('network')}): {re.sub(r'[^ -~]', '', str(s.get('ua', '')))[:140]}; "
                         f"MP4 video {yes(caps.get('mp4'))}; MKV {'yes' if caps.get('mkv') else 'no'}; "
                         f"audio {yes(caps.get('audio'))}; HLS/MSE {yes(caps.get('mse'))}; "
                         f"HDR display {'yes' if caps.get('hdr') else 'no'}")
    return "\n".join(lines)


def splice(doc: str, body: str) -> str:
    """Replace what sits between the matrix markers; everything else in the file stays as written."""
    if doc.count(START) != 1 or doc.count(END) != 1 or doc.index(START) > doc.index(END):
        raise SystemExit("matrix file must hold the two jy051:matrix markers once each, start before end")
    head, rest = doc.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{body}\n{END}{tail}"


def am_start(opts: dict) -> list[str]:
    """`adb shell am start` argv: -S restarts the app, extras carry the run settings (never a credential)."""
    argv = ["shell", "am", "start", "-S", "-W", "-n", ACTIVITY]
    for k, v in opts.items():
        if isinstance(v, bool):
            argv += ["--ez", k, "true" if v else "false"]
        elif isinstance(v, int):
            argv += ["--ei", k, str(v)]
        else:
            if not re.fullmatch(r"[A-Za-z0-9,.:/_-]*", str(v)):
                raise SystemExit(f"bad value for {k}")
            argv += ["--es", k, str(v)]
    return argv


# ---------------------------------------------------------------- adb / gh (laptop)

class Runner:
    def __init__(self, args):
        self.args = args
        self.dry = args.dry_run
        self.adb = (os.environ.get("ADB") or shutil.which("adb")
                    or os.path.expandvars(r"%LOCALAPPDATA%\Android\platform-tools\adb.exe"))
        self.serial = args.serial or os.environ.get("JY051_TV_SERIAL") or self._serial_file()
        self.dir = state_dir()
        self.log_path = self.dir / f"sitting-{dt.date.today():%Y-%m-%d}.log"

    @staticmethod
    def _serial_file() -> str:
        f = Path(os.environ.get("TEMP", ".")) / "joeytv_windows" / "b9_serial.txt"   # JoeyTV scripts' pair/connect
        return f.read_text(encoding="utf-8").strip() if f.is_file() else ""

    def log(self, msg: str):
        line = f"{dt.datetime.now():%H:%M:%S} {'(dry run) ' if self.dry else ''}{msg}"
        print(line)
        if not self.dry:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def adb_argv(self, args: list[str]) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else []) + args

    def run_adb(self, args: list[str], shown: list[str] | None = None, timeout: float = 120) -> str:
        if self.dry:
            print("DRY adb " + " ".join(shown or args))
            return ""
        p = subprocess.run(self.adb_argv(args), capture_output=True, timeout=timeout)
        return (p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()

    def need_tv(self):
        if self.dry:
            return
        if not os.path.exists(self.adb) and not shutil.which(self.adb):
            raise SystemExit("FAIL adb not found (%LOCALAPPDATA%\\Android\\platform-tools)")
        state = self.run_adb(["get-state"], timeout=20)
        if state.strip() != "device":   # the error text also contains the word "device"
            raise SystemExit("FAIL TV not on adb: wake it (power button), then Wireless debugging connect")

    def apk(self) -> Path:
        return self.dir / "apk" / "joey-study.apk"

    # ---- commands
    def check(self):
        ok = True
        self.log(("PASS" if self.apk().is_file() else "FAIL") + f" APK at {self.apk()}")
        ok &= self.apk().is_file() or self.dry
        try:
            self.need_tv()
            self.log("PASS TV on adb")
        except SystemExit as exc:
            ok = False
            self.log(str(exc))
        return 0 if ok else 1

    def fetch_apk(self):
        run_id = self.args.run
        if not run_id:
            if self.dry:
                run_id = "<latest>"
            else:
                out = subprocess.run(["gh", "run", "list", "-R", GH_REPO, "-w", WORKFLOW, "-b", BRANCH, "-s", "success",
                                      "-L", "1", "--json", "databaseId", "-q", ".[0].databaseId"],
                                     capture_output=True, text=True, timeout=60).stdout.strip()
                if not out:
                    raise SystemExit("FAIL no successful jy051-study run on the branch yet")
                run_id = out
        dest = self.apk().parent
        cmd = ["gh", "run", "download", "-R", GH_REPO, str(run_id), "-n", ARTIFACT, "-D", str(dest)]
        if self.dry:
            print("DRY " + " ".join(cmd))
            return 0
        dest.mkdir(parents=True, exist_ok=True)
        if self.apk().exists():
            self.apk().unlink()
        subprocess.run(cmd, check=True, timeout=300)
        self.log(f"PASS APK from run {run_id}: {self.apk().stat().st_size} bytes")
        return 0

    def install(self):
        self.need_tv()
        if not self.dry and not self.apk().is_file():
            raise SystemExit("FAIL no APK: run fetch-apk first")
        self.run_adb(["uninstall", PKG])           # a CI debug key differs per run: never install over it
        out = self.run_adb(["install", str(self.apk())], timeout=300)
        if not self.dry and "Success" not in out:
            raise SystemExit(f"FAIL adb install: {out[-200:]}")
        self.log("PASS Joey Study installed")
        return 0

    def _launch_and_collect(self, opts: dict, label: str, timeout_s: float) -> list[dict]:
        self.run_adb(["logcat", "-c"])
        self.run_adb(am_start(opts))
        self.log("B.: sign in as joeytest on the TV (user name, password, Sign in).")
        if self.dry:
            print("DRY adb logcat -v epoch -s JY051:I  (until the app's final done line)")
            return []
        out_file = self.dir / f"tv-{label}-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
        recs: list[dict] = []
        proc = subprocess.Popen(self.adb_argv(["logcat", "-v", "epoch", "-s", "JY051:I"]), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout_s
        try:
            with open(out_file, "w", encoding="utf-8") as fh:
                while time.time() < deadline:
                    raw = proc.stdout.readline()
                    if not raw:
                        if proc.poll() is not None:
                            break
                        continue
                    for rec in parse_logcat([raw.decode("utf-8", "replace")]):
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()
                        recs.append(rec)
                        if rec.get("kind") == "run":
                            t = first_frame(rec)
                            self.log(f"  {rec.get('engine')} row {rec.get('n')} run {rec.get('run')}: "
                                     f"{'ok' if rec.get('ok') else 'FAIL ' + str(rec.get('err'))}"
                                     f"{f' {t / 1000:.2f} s' if t is not None else ''} {rec.get('method', '')}")
                        if is_final_done(rec):
                            deadline = 0
                            break
        finally:
            proc.terminate()
        done = [r for r in recs if is_final_done(r)]
        self.log(("PASS" if done and not done[-1].get("aborted") else "FAIL") +
                 f" {label}: {sum(1 for r in recs if r.get('kind') == 'run')} runs -> {out_file}")
        return recs

    def tv(self):
        self.need_tv()
        opts = {"engines": self.args.engines, "runs": self.args.runs, "runs_t1": self.args.runs_t1,
                "network": self.args.network, "look": ",".join(map(str, LOOK_ROWS)),
                "hold_ms": self.args.hold_ms, "look_ms": 8000}
        if self.args.rows:
            opts["rows"] = self.args.rows
        self.log("After the matrix the TV asks: OK = resume test (skip to about 5:00, then Back), Back = finish.")
        self._launch_and_collect(opts, "matrix", timeout_s=self.args.timeout * 60)
        return 0

    def resume_tv(self):
        self.need_tv()
        self.log("B.: on the TV press right on the progress bar until about 5:00, then Back.")
        self._launch_and_collect({"mode": "resume", "network": self.args.network}, "resume", timeout_s=15 * 60)
        return 0

    def uninstall(self):
        self.need_tv()
        out = self.run_adb(["uninstall", PKG])
        self.log(f"{'PASS' if self.dry or 'Success' in out else 'NOTE'} uninstall: {out[-80:] if out else 'dry run'}")
        return 0

    def ingest(self):
        total = 0
        for name in self.args.files:
            text = Path(name).read_text(encoding="utf-8-sig")
            blobs = extract_web(text)
            if not blobs:
                raise SystemExit(f"FAIL {name}: no study-page results (copy them with the page's Copy results)")
            for b in blobs:
                runs = [r for r in (clean_record(x) for x in b.get("runs") or []) if r]
                sess = b.get("session") or {}
                keep = {"kind": "jy051-web", "session": {k: sess.get(k) for k in ("device", "network", "ua", "caps", "when")},
                        "runs": runs}
                dev = re.sub(r"\W", "", str(sess.get("device") or "web")) or "web"
                out = self.dir / f"web-{dev}-{dt.datetime.now():%Y%m%d-%H%M%S}-{total}.json"
                if self.dry:
                    print(f"DRY would keep {len(runs)} runs from {dev} -> {out}")
                else:
                    self.dir.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(keep), encoding="utf-8")
                    self.log(f"PASS kept {len(runs)} runs from {dev} -> {out.name}")
                total += 1
        return 0

    def collect(self) -> tuple[list[dict], list[dict]]:
        records, sessions = [], []
        for f in sorted(self.dir.glob("tv-*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("kind") == "session":
                    sessions.append(rec)
                elif (c := clean_record(rec)):
                    records.append(c)
        for f in sorted(self.dir.glob("web-*.json")):
            blob = json.loads(f.read_text(encoding="utf-8"))
            if blob.get("session"):
                sessions.append(blob["session"])
            records += [r for r in (clean_record(x) for x in blob.get("runs") or []) if r]
        # one line per device + network for the device list (the newest)
        latest = {}
        for s in sessions:
            latest[(s.get("device"), s.get("network"))] = s
        return dedupe(records), list(latest.values())

    def matrix(self):
        records, sessions = self.collect()
        body = render_matrix(records, sessions, f"{dt.datetime.now():%Y-%m-%d %H:%M}")
        path = Path(self.args.out)
        doc = splice(path.read_text(encoding="utf-8"), body)
        if self.dry:
            print(body)
            return 0
        path.write_text(doc, encoding="utf-8", newline="\n")
        self.log(f"PASS matrix: {len(records)} records -> {path}")
        return 0

    def sitting(self):
        for step in (self.check, self.install, self.tv, self.matrix):
            rc = step()
            if rc:
                self.log(f"STOP at {step.__name__}")
                return rc
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="JY-051 sitting runner (adb + matrix).")
    ap.add_argument("cmd", choices=("check", "fetch-apk", "install", "tv", "resume-tv", "ingest", "matrix",
                                    "uninstall", "sitting"))
    ap.add_argument("files", nargs="*", help="ingest: files holding the study page's copied results")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--serial", default="", help="adb serial (default env JY051_TV_SERIAL, then the JoeyTV serial file)")
    ap.add_argument("--run", default="", help="fetch-apk: workflow run id (default: newest green run on the branch)")
    ap.add_argument("--engines", default="T1,T2,T2F,T2H")
    ap.add_argument("--runs", type=int, default=3, help="timed runs per file for T2/T2F/T2H")
    ap.add_argument("--runs-t1", type=int, default=1, help="timed runs per file and engine inside the WebView")
    ap.add_argument("--rows", default="", help="comma list of test-file numbers (default all 12)")
    ap.add_argument("--network", choices=("LAN", "Remote"), default="LAN")
    ap.add_argument("--hold-ms", type=int, default=1000)
    ap.add_argument("--timeout", type=int, default=60, help="tv: minutes before giving up on the app")
    ap.add_argument("--out", default=str(MATRIX))
    args = ap.parse_args(argv)
    if args.rows and not re.fullmatch(r"\d{1,2}(,\d{1,2})*", args.rows):
        ap.error("--rows is a comma list of numbers")
    if not re.fullmatch(r"(T1|T2|T2F|T2H)(,(T1|T2|T2F|T2H))*", args.engines):
        ap.error("--engines: comma list of T1, T2, T2F, T2H")
    r = Runner(args)
    fn = {"check": r.check, "fetch-apk": r.fetch_apk, "install": r.install, "tv": r.tv, "resume-tv": r.resume_tv,
          "ingest": r.ingest, "matrix": r.matrix, "uninstall": r.uninstall, "sitting": r.sitting}[args.cmd]
    if args.cmd == "ingest" and not args.files:
        ap.error("ingest needs at least one file")
    return fn() or 0


if __name__ == "__main__":
    sys.exit(main())
