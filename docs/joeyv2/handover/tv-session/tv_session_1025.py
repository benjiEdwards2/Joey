"""Joey TV grouped TV session, 2026-10-25: the 40-check list at the top of JoeyTV\\TV_UI_PLAN.md.

Runs every automatable check on B.'s TCL (debug build net.joeyhome.media.debug, signed in as joeytest) in order and
prints PASS / FAIL / DEFERRED / WAITING / BYEYE per check number. Reuses tv_ui_capture.py (page capture, audit, probe,
local/browser headless Chrome) and wp_b9_device.py (adb, DevTools). Output goes to review\\tv-ui-2026-10-25\\ (its own
capture.json and shots); the 2026-10-23 capture is only read (item 36).

Side effects (B.'s limits, 2026-10-25): joeytest only. Item 14 plays one episode in the Jellyfin app (only after the
Jellyfin session is confirmed as joeytest) and stops it. Item 16 opens the Rate strip and moves focus, never OK on a
number. Item 18 opens the request confirm step and cancels it, never Confirm. Item 10 signs joeytest out and back in
(Quick Connect approval as joeytest, no stale-device delete; a fallback delete runs only to restore the session after a
FAIL). Before every check the NAS deploy lock is read; while it exists the run waits, then 60 s warm-up.
Items 32-35 (shell 1.0.2) are WAITING: not run here.

Usage:
  python tv_session_1025.py                  # every "now" check (1-31, 36-39)
  python tv_session_1025.py --only 3,20,21   # a subset (check numbers; 'cap' forces the device page capture again)
Log: scripts\\logs\\tv_session_1025.log
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import types
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import _joeytv as J  # noqa: E402
import wp_b9_device as D  # noqa: E402
import tv_ui_capture as C  # noqa: E402

J.STATUSES = J.STATUSES + ("DEFERRED", "WAITING", "BYEYE")

OUT = os.path.join(os.path.dirname(HERE), "review", "tv-ui-2026-10-25")
BASE = os.path.join(os.path.dirname(HERE), "review", "tv-ui-2026-10-23", "capture.json")
C.OUT, C.SHOT_DEV, C.SHOT_LOC = OUT, os.path.join(OUT, "shots", "device"), os.path.join(OUT, "shots", "local")
C.CAPTURE = os.path.join(OUT, "capture.json")
C.ARGS = types.SimpleNamespace(only=None, dry_run=False, allow_write=True)
PKG = D.PKG_DEBUG
D.ARGS = types.SimpleNamespace(pkg=PKG)
JOEYTEST_NAME = "joeytest"
RESULTS = {}   # n -> (status, detail)

FOCUS2_JS = r"""(() => { const e = document.activeElement; if (!e || e === document.body) return null;
 const r = e.getBoundingClientRect();
 return { d: e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : ''),
  t: (e.innerText || e.getAttribute('aria-label') || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 40),
  href: e.getAttribute('href'), jf: e.getAttribute('data-jf-id'), cur: e.getAttribute('aria-current'),
  top: e.closest('.topbar') ? 1 : 0, brand: e.closest('.brand') ? 1 : 0, chip: e.closest('.userchip') ? 1 : 0,
  srch: e.hasAttribute('data-tv-search') ? 1 : 0, ro: e.readOnly === true ? 1 : 0, rate: e.closest('.tv-rate') ? 1 : 0,
  ratebtn: e.hasAttribute('data-tv-rate') ? 1 : 0, eps: e.closest('.tv-eps') ? 1 : 0, grid: e.closest('.reqgrid-wrap') ? 1 : 0,
  btns: e.closest('.hero-detail-btns') ? 1 : 0, poster: e.classList.contains('card-poster') ? 1 : 0,
  x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
  inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth ? 1 : 0,
  sy: Math.round(scrollY), url: location.pathname + location.search }; })()"""

POSTER_PROBE_JS = r"""(() => { const dpr = devicePixelRatio, H = innerHeight, W = innerWidth, out = [];
 document.querySelectorAll('.card-pic img, .poster-grid img').forEach(i => { const r = i.getBoundingClientRect();
  if (!r.width || r.bottom <= 0 || r.top >= H || r.right <= 0 || r.left >= W) return;
  const src = (i.getAttribute('src') || ''); if (/\/img\/none/.test(src)) return;
  out.push({ src: src.replace(/^.*\/img\//, '').slice(0, 44), nw: i.complete ? i.naturalWidth : -1, dev: Math.round(r.width * dpr) }); });
 return out; })()"""


def log(r, msg):
    r.log(msg)


# ------------------------------------------------------------------------------------------------- NAS deploy lock
def lock_wait(r):
    waited = False
    t0 = time.time()
    while True:
        out = r.ssh("ls -d /tmp/joey-deploy.lock 2>/dev/null || true")
        if "joey-deploy.lock" not in out:
            break
        if not waited:
            r.log("deploy lock present: waiting until it is gone (+60 s warm-up)")
        waited = True
        if time.time() - t0 > 1800:
            raise RuntimeError("deploy lock still present after 30 min")
        time.sleep(15)
    if waited:
        time.sleep(60)
        r.log(f"deploy lock gone after {round(time.time() - t0)} s (incl. warm-up)")


def check(r, n, name, fn):
    """One numbered check: deploy lock first, then the body. Records the result under its number."""
    def body():
        lock_wait(r)
        return fn()
    st = r.step(f"#{n} {name}", body)
    RESULTS[n] = (st, r.rows[-1][2])
    return st


# ------------------------------------------------------------------------------------------------- device helpers
class T(C.Dev):
    def f(self):
        return self.js(FOCUS2_JS)

    def clear_memory(self):
        self.js("try { sessionStorage.removeItem('joeyTV.back'); } catch (e) {} 1")

    def fresh(self, path, settle=5):
        """Navigate, forget Back memory, reload so tv.js's first focus applies."""
        self.goto(path, settle=settle)
        self.clear_memory()
        self.goto(path, settle=settle)
        time.sleep(0.8)
        return self.f()

    def ups_to_top(self, n=4):
        stops = []
        for _ in range(n):
            self.key("DPAD_UP")
            f = self.f()
            stops.append(f)
            if f and f["top"]:
                break
        return stops


def ime_shown(r):
    out = D.sh(r, "dumpsys input_method | grep -E 'mInputShown|mIsInputViewShown|isInputViewShown' | head -3")
    return "=true" in out, out.replace("\n", " ").strip()[:120]


def wake(r):
    """The TV's ambient screen (dreamx) swallows launches: wake it and dismiss the dream first."""
    top = D.top_pkg(r)
    if "dream" in top or not top:
        D.sh(r, "input keyevent KEYCODE_WAKEUP")
        time.sleep(1.0)
        D.sh(r, "input keyevent KEYCODE_HOME")
        time.sleep(2.0)


def ui_dump(r):
    out = D.adb(r, "shell", "uiautomator dump /sdcard/tvs_ui.xml >/dev/null 2>&1; cat /sdcard/tvs_ui.xml", timeout=30, binary=True)
    return (out or b"").decode("utf-8", "replace")


def dismiss_update(r):
    """The 1.0.1 shell offers 1.0.2 (JY-191, the orchestrator's update): press Later, never Update now. Acts only
    when the native update dialog is up, and presses OK only when the focused button reads Later."""
    x = ui_dump(r)
    if "id/update_title" not in x:
        return False
    for _ in range(3):
        m = re.search(r'<node[^>]*text="Later"[^>]*id/update_later"[^>]*focused="true"', x)
        if m:
            D.sh(r, "input keyevent KEYCODE_DPAD_CENTER")
            time.sleep(1.5)
            STATE_NOTES.append("update dialog (1.0.2 offered) dismissed with Later")
            return True
        D.sh(r, "input keyevent KEYCODE_DPAD_RIGHT")
        time.sleep(0.8)
        x = ui_dump(r)
    raise J.Manual("update dialog up but focus never reached Later - nothing pressed")


STATE_NOTES = []


def ensure_app(r):
    wake(r)
    if D.top_pkg(r) != PKG:
        D.launch_app(r, wait=7)
    dismiss_update(r)


def fdesc(f):
    return None if not f else f"{f['d']} '{f['t']}'"


def cap():
    return C.load_capture()


def pages_fixed(t):
    """tv_ui_capture.pages() with the JY-192 TV markup: seasons sit in .tv-seasons, episodes in .tv-eps (aired cards
    link to Jellyfin; the episode page is /media/item/<data-jf-id>)."""
    def first_href(path, sel, rx=r"^/media/item/"):
        t.goto(path, settle=3)
        hrefs = t.js(f"[...document.querySelectorAll({json.dumps(sel)})].map(a => a.getAttribute('href'))") or []
        return next((h for h in hrefs if h and re.search(rx, h)), None)

    movie = first_href("/media/movies", "a.card-poster")
    series = first_href("/media/tv", "a.card-poster")
    season = episode = person = title = None
    if series:
        t.goto(series, settle=3)
        season = t.js("(() => { const a = [...document.querySelectorAll('.tv-seasons a.card-poster, .seasons a[href]')]"
                      ".map(a => a.getAttribute('href')).filter(h => h && h.startsWith('/media/item/')); return a[0] || null; })()")
        person = t.js("(() => { const a = document.querySelector('a[href^=\"/media/person/\"]'); return a && a.getAttribute('href'); })()")
    if season:
        t.goto(season, settle=3)
        episode = t.js("(() => { const a = [...document.querySelectorAll('.tv-eps a.card-poster')]; for (const e of a) {"
                       " const h = e.getAttribute('href') || ''; if (h.startsWith('/media/item/')) return h;"
                       " if (e.dataset.jfId) return '/media/item/' + e.dataset.jfId; } return null; })()")
    if not person and movie:
        t.goto(movie, settle=3)
        person = t.js("(() => { const a = document.querySelector('a[href^=\"/media/person/\"]'); return a && a.getAttribute('href'); })()")
    t.goto("/media/discover", settle=3)
    links = t.js("[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))") or []
    title = next((h for h in links if re.match(r"^/media/title/(movie|tv)/\d+$", h or "")), None)
    p = [("overview", "/a/media"), ("movies", "/media/movies"), ("movies_watchlist", "/media/movies/watchlist"),
         ("movies_tonight", "/media/movies/tonight"), ("movies_torate", "/media/movies/to-rate"),
         ("movies_awards", "/media/movies/awards"), ("tv", "/media/tv"), ("tv_watchlist", "/media/tv/watchlist"),
         ("title_movie", movie), ("title_series", series), ("title_season", season), ("title_episode", episode),
         ("person", person), ("title_tmdb", title), ("diary", "/media/diary"), ("diary_tv", "/media/diary?kind=tv"),
         ("history", "/media/history"), ("discover", "/media/discover"), ("discover_search", "/media/discover/search?q=star"),
         ("search", "/media/search?q=the"), ("notfound", "/media/nope-404")]
    return [(n, u) for n, u in p if u]


C.pages = pages_fixed


def dev_page(name):
    return cap().get("device", {}).get(name)


def page_url_of(name):
    return cap().get("device", {}).get("_pages", {}).get(name)


def need_cap(*names):
    for n in names:
        if not dev_page(n):
            raise RuntimeError(f"device capture has no '{n}' page (run with --only cap)")


# ================================================================================================= checks
def run(r, want):
    t = None

    def dev():
        nonlocal t
        if t is None:
            D.need_device(r)
            ensure_app(r)
            C.device_ready(r)
            t = T(r)
        ensure_app(r)
        return t

    def on(n):
        return want is None or str(n) in want

    # ---------------------------------------------------------------- device page capture (feeds 5, 9, 13, 17, 18, 24, 26, 36)
    if (want is None and not cap().get("device")) or (want and "cap" in want):
        lock_wait(r)
        tt = dev()
        C.capture_pages(r, tt, "device")

    # ---------------------------------------------------------------- JY-187
    def open_back(path, rights, downs, name, need_scroll):
        tt = dev()
        tt.goto(path, settle=5)
        tt.clear_memory()
        tt.goto(path, settle=5)
        for _ in range(downs):
            tt.key("DPAD_DOWN")
        for _ in range(rights):
            tt.key("DPAD_RIGHT")
        before = tt.f()
        tt.key("DPAD_CENTER", 0.2)
        u, ms = C.wait_url(tt, r"^/media/(item|title)/")
        time.sleep(1.2)
        tt.shot(f"j_{name}_opened")
        tt.key("BACK", 0.2)
        bu, bms = C.wait_url(tt, "^" + re.escape(path))
        time.sleep(1.5)
        after = tt.f()
        tt.shot(f"j_{name}_back")
        same = bool(before and after and before["href"] == after["href"])
        scroll_ok = (not need_scroll) or (before and after and before["sy"] > 0 and abs(before["sy"] - after["sy"]) <= 40)
        det = (f"focus {before and (before['href'], before['sy'])} -> OK -> {u} ({ms} ms) -> Back -> {bu} ({bms} ms), "
               f"focus {after and (after['href'], after['sy'], after['inView'])}")
        return ("PASS" if same and scroll_ok else "FAIL"), det

    if on(1):
        check(r, 1, "J3 Movies row 2 col 4 -> title -> Back: focus restored",
              lambda: open_back("/media/movies", 3, 1, "mv_open", False))
    if on(2):
        check(r, 2, "J4 Movies row 5 -> title -> Back: scroll restored",
              lambda: open_back("/media/movies", 1, 4, "mv_deep", True))

    def j5():
        tt = dev()
        first = tt.fresh("/media/movies")
        stops = tt.ups_to_top()
        tt.shot("j5_up_pill")
        last = stops[-1] if stops else None
        ok = bool(last and last["top"] and last["cur"] and "Movies" in last["t"])
        return ("PASS" if ok else "FAIL",
                f"first {fdesc(first)}; Up x{len(stops)} stops {[fdesc(s) for s in stops]} (aria-current={last and last['cur']})")
    if on(3):
        check(r, 3, "J5 Up from Movies lands on the current pill", j5)

    # 4 + 16 share the title page and the Rate strip
    state = {}

    def rate_movie(tt):
        if state.get("movie"):
            return state["movie"]
        tt.goto("/media/movies", settle=4)
        hrefs = tt.js("[...document.querySelectorAll('a.card-poster')].map(a => a.getAttribute('href'))"
                      ".filter(h => h && h.startsWith('/media/item/')).slice(0, 8)") or []
        for h in hrefs:
            tt.goto(h, settle=4)
            lbl = tt.js("(() => { const b = document.querySelector('[data-tv-rate]'); return b ? b.innerText.trim() : null; })()")
            if lbl and lbl.startswith("Rate") and not lbl.startswith("Rated"):
                state["movie"] = h
                return h
        raise RuntimeError(f"no unrated film with a Rate button in the first {len(hrefs)} Movies posters")

    def to_rate_btn(tt):
        h = rate_movie(tt)
        tt.fresh(h, settle=4)
        stops = [tt.f()]
        for _ in range(7):
            if stops[-1] and stops[-1]["ratebtn"]:
                break
            tt.key("DPAD_RIGHT", 0.45)
            stops.append(tt.f())
        return h, stops

    def j9():
        tt = dev()
        h, stops = to_rate_btn(tt)
        if not (stops[-1] and stops[-1]["ratebtn"]):
            return "FAIL", f"Right along the buttons never reached the Rate button: {[fdesc(s) for s in stops]}"
        # strip closed: Down from the buttons (info)
        tt.key("DPAD_DOWN")
        closed_down = tt.f()
        tt.key("DPAD_UP")
        # open the strip (OK on Rate only opens it; no rating is sent)
        f = tt.f()
        if not (f and f["ratebtn"]):
            to_rate_btn(tt)
        tt.key("DPAD_CENTER", 0.8)
        opened = tt.f()
        tt.key("DPAD_UP")
        up = tt.f()
        tt.key("DPAD_DOWN")
        down = tt.f()
        tt.shot("j9_down_into_strip")
        tt.key("BACK", 1.0)   # closes the strip (joeyTV.back -> closeRate)
        ok = bool(up and up["btns"] and down and down["rate"] and down["t"].strip() == "1")
        return ("PASS" if ok else "FAIL",
                f"{h}: strip open focus {fdesc(opened)}; Up -> {fdesc(up)}; Down -> {fdesc(down)} (want chip 1); "
                f"strip closed, Down from Rate -> {fdesc(closed_down)}")
    if on(4):
        check(r, 4, "J9 Down from the title buttons lands on the first rating control", j9)

    # ---------------------------------------------------------------- JY-188
    def c5():
        need_cap("title_movie", "title_series", "notfound", "overview")
        bad, det = [], []
        for n in ("title_movie", "title_series", "notfound", "overview"):
            a = dev_page(n)
            det.append(f"{n} tiny {a['tinyN']} lowC {a['lowContrastN']}")
            if a["tinyN"] or a["lowContrastN"] > 2:
                bad.append(n + ":" + ";".join(f"{x[0]}|{x[1]}|{x[2]}" for x in (a["tiny"] + a["lowContrast"])[:4]))
        return ("PASS" if not bad else "FAIL", ", ".join(det) + ("" if not bad else " || " + " || ".join(bad)))
    if on(5):
        check(r, 5, "device title_movie,title_series,notfound,overview: 0 tiny, lowContrast <= 2", c5)

    def c6():
        tt = dev()
        tt.fresh("/a/media")
        m = tt.js(r"""(() => { const bar = document.querySelector('.topbar'); const br = bar && bar.getBoundingClientRect();
          const cards = [...document.querySelectorAll('main .card-poster')].filter(c => { const r = c.getBoundingClientRect(); return r.width && r.top < innerHeight && r.bottom > 0; });
          const tops = {}; cards.forEach(c => { const y = Math.round(c.getBoundingClientRect().top / 10); tops[y] = (tops[y] || 0) + 1; });
          const metas = cards.map(c => c.querySelector('.row-meta')).filter(m => m && m.getBoundingClientRect().height && getComputedStyle(m).visibility !== 'hidden' && +getComputedStyle(m).opacity > 0);
          const c0 = cards[0] && cards[0].getBoundingClientRect();
          return { bar: br ? Math.round(br.height) : null, perRow: Object.values(tops), metaShown: metas.length,
                   card: c0 ? [Math.round(c0.width), Math.round(c0.height)] : null }; })()""")
        s = tt.shot("by_eye_06_overview")
        return "BYEYE", f"{s}; bar {m['bar']} px, cards per row in view {m['perRow']}, card {m['card']}, visible meta lines {m['metaShown']}"
    if on(6):
        check(r, 6, "by eye: Home 8 across, 64 px bar, meta only on the focused card", c6)

    # 7 is judged from the signin shots (#10) and the 404 shot; recorded after #10

    # ---------------------------------------------------------------- JY-189
    def c8():
        tt = dev()
        det, bad = [], []
        for name, path in (("movies", "/media/movies"), ("overview", "/a/media"), ("tonight", "/media/movies/tonight")):
            tt.fresh(path, settle=10)
            for _ in range(20):
                if not tt.js("[...document.images].filter(i => !i.complete).length"):
                    break
                time.sleep(0.5)
            res = tt.js(POSTER_PROBE_JS) or []
            low = [x for x in res if x["nw"] < x["dev"]]
            det.append(f"{name}: {len(res)} posters, min natural {min([x['nw'] for x in res] or [0])}, max device px {max([x['dev'] for x in res] or [0])}")
            bad += [f"{name}:{x['src']} {x['nw']}<{x['dev']}" for x in low[:3]]
        return ("PASS" if not bad else "FAIL", "; ".join(det) + ("" if not bad else " || low: " + ", ".join(bad)))
    if on(8):
        check(r, 8, "poster probe Movies / Home / Tonight: naturalWidth >= device px", c8)

    def c9():
        need_cap("movies_tonight")
        a = dev_page("movies_tonight")
        tt = dev()
        tt.fresh("/media/movies/tonight", settle=6)
        lab = tt.js(r"""(() => { const sub = document.querySelector('.sectabs.sub'); const sb = sub ? sub.getBoundingClientRect().bottom : 0;
          const el = [...document.querySelectorAll('h1,h2,.seclabel,p,span,div')].find(e => e.children.length === 0 && /Three for tonight/i.test(e.innerText || ''));
          if (!el) return { found: false, sb: Math.round(sb) }; const r = el.getBoundingClientRect();
          return { found: true, top: Math.round(r.top), bottom: Math.round(r.bottom), sb: Math.round(sb), visible: r.top >= sb - 1 && r.bottom <= innerHeight }; })()""")
        stops = [tt.f()]
        for _ in range(4):
            tt.key("DPAD_RIGHT")
            stops.append(tt.f())
            if stops[-1] and "Deal again" in stops[-1]["t"]:
                break
        tt.shot("tonight_deal_again")
        deal = stops[-1] and "Deal again" in stops[-1]["t"] and stops[-1]["inView"]
        rights = len(stops) - 1
        ok = a["outsideSafeN"] == 0 and not a["probe"]["offscreen"] and lab.get("visible") and deal and rights == 3
        return ("PASS" if ok else "FAIL",
                f"outsideSafe {a['outsideSafeN']}, offscreen {a['probe']['offscreen']}, label {lab}, Right stops "
                f"{[fdesc(s) for s in stops]} (Deal again after {rights} Rights)")
    if on(9):
        check(r, 9, "Tonight: outsideSafe 0, offscreen [], label visible, Deal again reachable", c9)

    # ---------------------------------------------------------------- JY-190
    def c11():
        tt = dev()
        tt.goto("/media/nope-404", settle=4)
        u = tt.js(r"""(() => { const c = document.querySelector('.topbar .userchip'); const t = document.querySelector('.topbar');
          return { chip: !!c, name: c ? (c.querySelector('.uname') || c).innerText.trim() : null,
                   notSigned: /Not signed in/i.test(t ? t.innerText : '') }; })()""")
        is_jt = (u.get("name") or "").lower() == JOEYTEST_NAME
        s = tt.shot("by_eye_07_notfound")
        return ("PASS" if u["chip"] and is_jt and not u["notSigned"] else "FAIL",
                f"chip {u['chip']}, chip names joeytest {is_jt}, 'Not signed in' {u['notSigned']}; {s}")
    if on(11):
        check(r, 11, "404 as joeytest: the bar shows joeytest's chip", c11)

    MONTH_Q = r"""
import sqlite3, sys, json, datetime as dt
c = sqlite3.connect('file:/data/sqlite/media.db?mode=ro', uri=True)
m = dt.date.today().strftime('%Y-%m')
own = 'jf:' + sys.argv[1]
def cnt(q, *a): return c.execute(q, a).fetchone()[0]
print(json.dumps({
 'own_diary': cnt("select count(*) from diary where owner=? and watched_on like ?", own, m + '%'),
 'own_play_films': cnt("select count(*) from play where owner=? and kind='movie' and finished=1 and started_at like ?", own, m + '%'),
 'own_play_eps': cnt("select count(*) from play where owner=? and kind='episode' and finished=1 and started_at like ?", own, m + '%'),
 'hh_diary_films': cnt("select count(*) from diary where owner='you' and kind='movie' and watched_on like ?", m + '%'),
 'hh_diary_eps': cnt("select count(*) from diary where owner='you' and kind!='movie' and watched_on like ?", m + '%')}))
"""

    def c12():
        tt = dev()
        tt.goto("/media/diary", settle=4)
        card = tt.js("(() => { const c = document.querySelector('.monthcard, .tvmonth'); return c ? c.innerText.replace(/\\s+/g, ' ').trim().slice(0, 120) : null; })()")
        body = tt.js("(document.querySelector('main') || document.body).innerText.replace(/\\s+/g, ' ').slice(0, 160)")
        nums = r.hub_json(MONTH_Q, J.full_id(r, J.JOEYTEST))
        s = tt.shot("diary_month_card")
        if not card:
            ok = bool(re.search(r"empty|nothing", body or "", re.I))
            return ("PASS" if ok else "FAIL", f"no month card; page '{(body or '')[:100]}'; counts {nums}; {s}")
        if re.search(r"nothing yet", card, re.I):
            return "PASS", f"card '{card}'; counts {nums}; {s}"
        f_ = re.search(r"(\d+)\s*films?", card)
        e_ = re.search(r"(\d+)\s*episodes?", card)
        cf, ce = int(f_.group(1)) if f_ else 0, int(e_.group(1)) if e_ else 0
        own_total = nums["own_diary"] + nums["own_play_films"] + nums["own_play_eps"]
        household = (cf, ce) == (nums["hh_diary_films"], nums["hh_diary_eps"]) and (cf + ce) > 0
        ok = (cf + ce) <= max(own_total, 0) and not household
        return ("PASS" if ok else "FAIL", f"card '{card}' -> films {cf} eps {ce}; counts {nums}; {s}")
    if on(12):
        check(r, 12, "Diary month card = joeytest's own numbers (or nothing yet)", c12)

    # ---------------------------------------------------------------- JY-192
    def c13():
        need_cap("title_series", "title_season", "title_episode")
        det = [f"{n} tiny {dev_page(n)['tinyN']} {[x[0] + '|' + str(x[1]) for x in dev_page(n)['tiny'][:3]]}"
               for n in ("title_series", "title_season", "title_episode")]
        ok = all(dev_page(n)["tinyN"] == 0 for n in ("title_series", "title_season", "title_episode"))
        return ("PASS" if ok else "FAIL", "; ".join(det))
    if on(13):
        check(r, 13, "device title_series,title_season,title_episode: 0 tiny", c13)

    def c14():
        tt = dev()
        series = page_url_of("title_series")
        if not series:
            raise RuntimeError("no series page in the capture")
        tt.fresh(series, settle=5)
        stops = []
        for _ in range(8):
            tt.key("DPAD_DOWN")
            f = tt.f()
            stops.append(f)
            if f and f["eps"]:
                break
        f = stops[-1] if stops else None
        if not (f and f["eps"] and f["jf"]):
            return "FAIL", f"Down never reached an aired episode card: {[fdesc(s) for s in stops]}"
        ep = f["jf"].replace("-", "")
        tt.shot("j6_episode_focused")
        tt.key("DPAD_CENTER", 0.2)
        J.wait_for(r, "Jellyfin in front", lambda: D.top_pkg(r) == D.JF_PKG, 20, 1)
        time.sleep(4)
        if D.top_pkg(r) != D.JF_PKG:
            return "FAIL", f"OK on episode {ep[:8]} did not bring Jellyfin to the front (top {D.top_pkg(r)})"
        D.shot(r, "j6_jellyfin")
        tt.shot("j6_jellyfin_front")
        jt = J.JOEYTEST

        def tv_sess():
            return [s for s in J.sessions(r) if s["client"] == "Jellyfin Android TV"]
        ss = J.wait_for(r, "Jellyfin Android TV session", tv_sess, 15, 2) or []
        users = {s["user"] for s in ss}
        if not ss or users - {jt}:
            D.force_stop(r, D.JF_PKG)
            ensure_app(r)
            return "DEFERRED", f"hand-off brought Jellyfin to the front for episode {ep[:8]}, but the TV's Jellyfin app user(s) {sorted(u if u == jt else 'other' for u in users) or 'none'}: not joeytest, nothing played (stopped)"
        playing = J.wait_for(r, "episode playing", lambda: next((s for s in tv_sess() if s["playing"]), None), 8, 2)
        pressed = False
        if not playing:   # route 1b lands on the details page: one OK = Play
            D.key(r, "KEYCODE_DPAD_CENTER", 4)
            pressed = True
            playing = J.wait_for(r, "episode playing", lambda: next((s for s in tv_sess() if s["playing"]), None), 25, 2)
        now = (playing or {}).get("now") or ""
        D.shot(r, "j6_playing")
        tt.shot("j6_playing")
        # stop it
        D.key(r, "KEYCODE_MEDIA_STOP", 2)
        D.force_stop(r, D.JF_PKG)
        stopped = not any(s["playing"] for s in tv_sess())
        ensure_app(r)
        ok = bool(playing) and now.replace("-", "") == ep and stopped
        return ("PASS" if ok else "FAIL",
                f"episode card {ep[:8]} -> Jellyfin (joeytest session){' -> OK on details' if pressed else ''} -> "
                f"playing {bool(playing)}, now {now.replace('-', '')[:8]} (want {ep[:8]}); stopped {stopped}")
    if on(14):
        check(r, 14, "J6 OK on an episode card: Jellyfin plays that episode (then stopped)", c14)

    def c15():
        tt = dev()
        series, ep = page_url_of("title_series"), page_url_of("title_episode")
        if not ep:
            raise RuntimeError("no episode page in the capture")
        # the episode's own series (the episode page's season card links up)
        tt.goto("/media/movies", settle=4)
        # Home as a real page navigation (a DevTools Page.navigate entry is not what a friend's history holds)
        tt.js("location.href = '/a/media'; 1")
        C.wait_url(tt, r"^/a/media$")
        time.sleep(1.5)
        tt.js("try { sessionStorage.removeItem('joeyTV.trail'); } catch (e) {} 1")
        tt.js(f"location.href = {json.dumps(ep)}; 1")
        u, _ = C.wait_url(tt, "^" + re.escape(ep))
        time.sleep(1.5)
        tt.shot("ep_from_home")
        tt.key("BACK", 0.2)
        b1, _ = C.wait_url(tt, r"^/media/item/(?!" + re.escape(ep.split("/")[-1]) + ")", timeout=10)
        time.sleep(1.2)
        p1 = tt.js("location.pathname")
        tt.shot("ep_back1")
        up = tt.js("(document.querySelector('[data-tv-up]') || {getAttribute: () => null}).getAttribute('data-tv-up')")
        trail_ = tt.js("sessionStorage.getItem('joeyTV.trail')")
        r.log(f"   #15 series page data-tv-up={up} trail={trail_}")
        tt.key("BACK", 0.2)
        b2, _ = C.wait_url(tt, r"^/a/media$", timeout=10)
        time.sleep(1.0)
        p2 = tt.js("location.pathname") if D.top_pkg(r) == PKG else "<exited>"
        tt.shot("ep_back2")
        ensure_app(r)
        ok = u and b1 and p1 == series and b2 == "/a/media"
        return ("PASS" if ok else "FAIL", f"Home -> episode {u} -> Back -> {p1} (series {series}) -> Back -> {p2}")
    if on(15):
        check(r, 15, "Episode from Home: Back -> series, Back -> Home", c15)

    def c16():
        tt = dev()
        h, stops = to_rate_btn(tt)
        if not (stops[-1] and stops[-1]["ratebtn"]):
            return "FAIL", f"Rate button not reached: {[fdesc(s) for s in stops]}"
        tt.key("DPAD_CENTER", 0.8)
        opened = tt.f()
        is_open = tt.js("!document.getElementById('tv-rate').hasAttribute('hidden')")
        moves = []
        for _ in range(7):
            tt.key("DPAD_RIGHT", 0.4)
            moves.append(tt.f())
        tt.shot("rate_strip_on_8")
        on8 = moves[-1] and moves[-1]["rate"] and moves[-1]["t"].strip() == "8"
        tt.key("BACK", 1.0)
        closed = tt.js("document.getElementById('tv-rate').hasAttribute('hidden')")
        back_f = tt.f()
        lbl = tt.js("document.querySelector('[data-tv-rate]').innerText.trim()")
        ok = is_open and opened and opened["rate"] and opened["t"].strip() == "1" and on8 and closed and back_f and back_f["ratebtn"]
        return ("PASS" if ok else "FAIL",
                f"{h}: OK on Rate -> open {is_open}, focus {fdesc(opened)} (want 1); Right x7 -> {fdesc(moves[-1])} (focus only, "
                f"no OK); Back -> closed {closed}, focus {fdesc(back_f)}, label '{lbl}'. 'OK on 8 -> Rated 8' DEFERRED: "
                f"it writes a joeytest rating (no test-safe path)")
    if on(16):
        check(r, 16, "Rate strip opens on 1; Back closes it (OK on 8 not pressed)", c16)

    # ---------------------------------------------------------------- JY-193
    def c17():
        """Live: films from Movies until one has a 'More on Joey' shelf; time = navigation start to every in-view image
        complete (lazy off-screen shelf images never complete, so the capture's images_ms hits its 8 s cap)."""
        tt = dev()
        tt.goto("/media/movies", settle=4)
        hrefs = tt.js("[...document.querySelectorAll('a.card-poster')].map(a => a.getAttribute('href'))"
                      ".filter(h => h && h.startsWith('/media/item/')).slice(0, 10)") or []
        tried = []
        for h in hrefs:
            t0 = time.time()
            ws = D.page_ws(r)
            try:
                ws.call("Page.navigate", url=C.HOST + h)
            finally:
                ws.close()
            ms = None
            while time.time() - t0 < 12:
                time.sleep(0.2)
                try:
                    st = tt.js("[document.readyState, location.pathname, [...document.images].filter(i => { const r = i.getBoundingClientRect();"
                               " return r.width && r.top < innerHeight && r.bottom > 0 && !i.complete; }).length]")
                except Exception:  # noqa: BLE001
                    continue
                if st and st[0] == "complete" and st[1] == h and st[2] == 0:
                    ms = round((time.time() - t0) * 1000)
                    break
            heads = tt.js("[...document.querySelectorAll('main .seclabel, main h2')].map(x => x.innerText.trim())") or []
            more = [x for x in heads if x.lower().startswith("more on joey")]
            offsrv = tt.js("/Not on server/.test(document.querySelector('main').innerText)")
            tried.append(f"{h[-8:]} {ms} ms shelf {bool(more)}")
            if more:
                tt.shot("title_more_on_joey")
                ok = ms is not None and ms < 3000 and not offsrv
                return ("PASS" if ok else "FAIL", f"{h}: in-view images settled {ms} ms, heading '{more[0]}', 'Not on server' {offsrv}; tried {tried}")
        return "FAIL", f"no 'More on Joey' shelf on {len(tried)} films: {tried}"

    def c17_old():
        need_cap("title_movie")
        a = dev_page("title_movie")
        heads = a.get("headings", [])
        more = any(h.startswith("More on Joey") for h in heads)
        notsrv = "Not on server" in (a.get("main") or "")
        ok = a["wall"]["images_ms"] < 3000 and more
        return ("PASS" if ok else "FAIL", f"{a['url'][-40:]}: images_ms {a['wall']['images_ms']}, headings {heads[:8]}, 'Not on server' in main {notsrv}")
    if on(17):
        check(r, 17, "title_movie images_ms < 3000, shelf 'More on Joey'", c17)

    def c18():
        need_cap("title_tmdb")
        a = dev_page("title_tmdb")
        tt = dev()
        url = page_url_of("title_tmdb")
        first = tt.fresh(url, settle=5)
        if not (first and first["t"] == "Request"):
            return "FAIL", f"outsideSafe {a['outsideSafeN']}; first focus {fdesc(first)} (want Request); nothing pressed"
        tt.shot("tmdb_request_focused")
        tt.key("DPAD_CENTER", 0.3)
        for _ in range(20):
            if tt.js("!!document.querySelector('#request-block form.confirm')"):
                break
            time.sleep(0.3)
        conf = tt.js("(() => { const f = document.querySelector('#request-block form.confirm'); return f ? f.innerText.replace(/\\s+/g, ' ').slice(0, 80) : null; })()")
        tt.shot("tmdb_confirm_step")
        # cancel: click the Cancel link (never Confirm)
        tt.js("(() => { const c = document.querySelector('#request-block form.confirm a.btn-ghost'); if (c) c.click(); return !!c; })()")
        time.sleep(1.5)
        idle = tt.js("!document.querySelector('#request-block form.confirm') && !!document.querySelector('#request-block a.btn')")
        ok = a["outsideSafeN"] == 0 and bool(conf) and idle
        return ("PASS" if ok else "FAIL",
                f"{url}: outsideSafe {a['outsideSafeN']}, Request focused on load, OK -> confirm '{conf}', Cancel -> idle {idle}. "
                f"'Requested, Back focused' DEFERRED (a real request downloads media)")
    if on(18):
        check(r, 18, "title_tmdb: outsideSafe 0, Request focused, OK opens confirm (cancelled)", c18)

    def c19():
        tt = dev()
        mv = page_url_of("title_movie")
        tt.goto(mv, settle=4)
        person = tt.js("(() => { const a = document.querySelector('a[href^=\"/media/person/\"]'); return a && a.getAttribute('href'); })()")
        if not person:
            return "FAIL", f"{mv}: no cast link to a person page on the TV title page"
        tt.clear_memory()
        tt.js(f"location.href = {json.dumps(person)}; 1")
        C.wait_url(tt, "^" + re.escape(person))
        time.sleep(2.0)
        f = tt.f()
        m = tt.js(r"""(() => { const h = document.querySelector('main h1') || document.querySelector('h1'); const bar = document.querySelector('.topbar');
          if (!h) return null; const r = h.getBoundingClientRect(), b = bar ? bar.getBoundingClientRect().bottom : 0;
          return { top: Math.round(r.top), bottom: Math.round(r.bottom), bar: Math.round(b), visible: r.top >= b - 1 && r.bottom <= innerHeight, len: h.innerText.trim().length }; })()""")
        s = tt.shot("person_from_cast")
        first_poster = tt.js("(() => { const a = document.querySelector('main a.card-poster'); return a && a === document.activeElement; })()")
        ok = bool(m and m["visible"] and m["len"]) and f and f["poster"] and first_poster
        return ("PASS" if ok else "FAIL", f"{person}: name {m}, focus {fdesc(f)}, first poster focused {first_poster}; {s}")
    if on(19):
        check(r, 19, "Person page from a film's cast: name under the bar, first poster focused", c19)

    # ---------------------------------------------------------------- JY-194 (20-23 run as one journey)
    disc = {}

    def c20():
        tt = dev()
        first = tt.fresh("/media/discover", settle=6)
        tt.key("DPAD_UP")
        f = tt.f()
        disc["field"] = bool(f and f["srch"])
        tt.shot("disc_field_focused")
        return ("PASS" if f and f["srch"] and f["ro"] else "FAIL", f"first {fdesc(first)} -> Up -> {fdesc(f)} (search {f and f['srch']}, read-only {f and f['ro']})")

    def c21():
        tt = dev()
        if not disc.get("field"):
            raise RuntimeError("#20 did not focus the field")
        tt.key("DPAD_CENTER", 1.5)
        ro = tt.js("document.querySelector('[data-tv-search]').readOnly")
        shown, raw = ime_shown(r)
        D.sh(r, "input text apothecary")
        q = lbl = None
        for _ in range(20):
            time.sleep(0.5)
            q = tt.js("(document.querySelector('.reqgrid-wrap') || {getAttribute: () => null}).getAttribute('data-q')")
            lbl = tt.js("(() => { const g = document.querySelector('.reqgrid-wrap'); const h = g && (g.querySelector('.seclabel,h2') || g); return h ? h.innerText.trim().split('\\n')[0].slice(0, 40) : null; })()")
            if q == "apothecary" and lbl and lbl.lower().startswith("results"):
                break
        tt.shot("disc_results")
        disc["typed"] = q == "apothecary"
        ok = ro is False and shown and q == "apothecary" and bool(lbl and re.match(r"Results\s*·\s*\d+", lbl, re.I))
        return ("PASS" if ok else "FAIL", f"OK -> readOnly {ro}, keyboard shown {shown} ({raw[:60]}); typed -> grid q '{q}', label '{lbl}'")

    def c22():
        tt = dev()
        if not disc.get("typed"):
            raise RuntimeError("#21 did not get results")
        tt.key("ENTER", 1.5)
        f = tt.f()
        shown, _ = ime_shown(r)
        tt.shot("disc_enter")
        disc["ime_after_enter"] = shown
        return ("PASS" if f and f["grid"] and f["poster"] else "FAIL", f"Enter -> focus {fdesc(f)} (in grid {f and f['grid']}); keyboard still shown {shown}")

    def c23():
        tt = dev()
        if not disc.get("typed"):
            raise RuntimeError("#21 did not get results")
        extra = ""

        def st():
            return (tt.f(), tt.js("(document.querySelector('.reqgrid-wrap') || {getAttribute: () => null}).getAttribute('data-q')"),
                    tt.js("(document.querySelector('[data-tv-search]') || {}).value"), tt.js("location.pathname"))
        if ime_shown(r)[0]:
            tt.key("BACK", 2.0)
            f0, q0, v0, p0 = st()
            extra = f" (keyboard was still up after Enter; Back #1 -> {p0}, q '{q0}', field '{v0}', focus {fdesc(f0)}, keyboard {ime_shown(r)[0]})"
            if p0 == "/media/discover" and not q0 and not v0:
                f, q, val = f0, q0, v0   # that Back closed the keyboard AND cleared the search
            else:
                tt.key("BACK", 2.0)
                f, q, val, _ = st()
        else:
            tt.key("BACK", 2.0)
            f, q, val, _ = st()
        tt.shot("disc_back_trending")
        tt.key("BACK", 0.3)
        time.sleep(2.5)
        top = D.top_pkg(r)
        p = tt.js("location.pathname") if top == PKG else "<exited>"
        tt.shot("disc_back_leave")
        ensure_app(r)
        ok = f and f["srch"] and not q and not val and p != "/media/discover"
        return ("PASS" if ok else "FAIL", f"Back -> focus {fdesc(f)}, grid q '{q}', field '{val}'{extra}; Back -> {p}")
    if on(20):
        check(r, 20, "Discover: Up from the first poster focuses the field", c20)
    if on(21):
        check(r, 21, "Discover: OK raises the keyboard, typing shows 'Results · n'", c21)
    if on(22):
        check(r, 22, "Discover: Enter moves focus to the first result", c22)
    if on(23):
        check(r, 23, "Discover: Back -> trending + field focused; Back again leaves", c23)

    # ---------------------------------------------------------------- JY-195
    def c24():
        need_cap("overview")
        tt = dev()
        tt.fresh("/a/media", settle=5)
        m = tt.js(r"""(() => { const sh = [...document.querySelectorAll('main section')].filter(s => s.querySelector('.card-poster'));
          const empties = [...document.querySelectorAll('main .empty')].filter(e => e.getBoundingClientRect().height);
          const w = document.querySelector('.welcome');
          return { shelves: sh.length, labels: sh.map(s => (s.querySelector('.seclabel') || {}).innerText || '').map(x => x.trim().slice(0, 30)),
                   empties: empties.length, welcome: !!w }; })()""")
        ok = m["shelves"] >= 4 and m["empties"] == 0
        return ("PASS" if ok else "FAIL", f"{m['shelves']} shelves {m['labels']}, grey .empty boxes {m['empties']}, welcome line {m['welcome']}")
    if on(24):
        check(r, 24, "Home >= 4 shelves, no grey empty box", c24)

    def c25():
        tt = dev()
        det, ok = [], True
        for name, path in (("watchlist", "/media/movies/watchlist"), ("to rate", "/media/movies/to-rate")):
            tt.fresh(path, settle=4)
            m = tt.js(r"""(() => { const main = document.querySelector('main') || document.body;
              const be = main.querySelector('.bigempty, [class*="bigempty"]'); const cards = main.querySelectorAll('.card-poster').length;
              const greys = [...main.querySelectorAll('.empty')].filter(e => e.getBoundingClientRect().height).length;
              return { big: be ? be.innerText.replace(/\s+/g, ' ').trim().slice(0, 90) : null, cards, greys,
                       zero: /0 on your watchlist/.test(main.innerText) }; })()""")
            s = tt.shot(f"empty_{name.replace(' ', '_')}")
            good = (m["big"] or m["cards"]) and not m["zero"] and m["greys"] == 0
            ok &= bool(good)
            det.append(f"{name}: words '{m['big']}', cards {m['cards']}, grey {m['greys']}, '0 on your watchlist' {m['zero']} ({s})")
        return ("PASS" if ok else "FAIL", "; ".join(det))
    if on(25):
        check(r, 25, "Watchlist / To rate: words-first state, no '0 on your watchlist'", c25)

    # ---------------------------------------------------------------- JY-196
    def c26():
        need_cap("diary", "history", "movies_awards")
        det = [f"{n} tiny {dev_page(n)['tinyN']} outsideSafe {dev_page(n)['outsideSafeN']} "
               f"{[x[0] for x in (dev_page(n)['tiny'] + dev_page(n)['outsideSafe'])[:3]]}" for n in ("diary", "history", "movies_awards")]
        ok = all(dev_page(n)["tinyN"] == 0 and dev_page(n)["outsideSafeN"] == 0 for n in ("diary", "history", "movies_awards"))
        return ("PASS" if ok else "FAIL", "; ".join(det))
    if on(26):
        check(r, 26, "device diary,history,movies_awards: 0 tiny, outsideSafe 0", c26)

    def c27():
        tt = dev()
        first = tt.fresh("/media/movies/awards", settle=6)
        m = tt.js(r"""(() => { const ch = [...document.querySelectorAll('.awtv-cer a')]; const rs = ch.map(c => c.getBoundingClientRect());
          return { chips: ch.length, maxRight: Math.round(Math.max(0, ...rs.map(r => r.right))), minLeft: Math.round(Math.min(9999, ...rs.map(r => r.left))),
                   rows: new Set(rs.map(r => Math.round(r.top))).size, cur: (ch.find(c => c.getAttribute('aria-current')) || {}).innerText,
                   shelves: [...document.querySelectorAll('.awtv-shelf .seclabel')].map(h => h.innerText.replace(/\s+/g, ' ').trim().slice(0, 34)),
                   edition: (document.querySelector('.awtv-ed') || {}).innerText }; })()""")
        s = tt.shot("awards_tv")
        ok = m["chips"] and m["maxRight"] <= 912 and m["minLeft"] >= 47 and first and first["cur"] and m["shelves"]
        return ("PASS" if ok else "FAIL", f"{m['chips']} chips in {m['rows']} row(s), x {m['minLeft']}..{m['maxRight']} (<= 912), current '{m['cur']}', "
                f"first focus {fdesc(first)} (aria-current {first and first['cur']}), edition '{m['edition']}', shelves {m['shelves']}; {s}")
    if on(27):
        check(r, 27, "Awards: chips inside the safe area, current chip first focus, shelves by group", c27)

    def c28():
        tt = dev()
        tt.fresh("/media/diary", settle=5)
        m = tt.js(r"""(() => { const vis = e => e && e.getBoundingClientRect().height > 0;
          const mc = document.querySelector('.tvmonth'); const chips = [...document.querySelectorAll('main .chips a, main .chips button')].filter(vis).map(c => c.innerText.trim());
          return { month: vis(mc) ? Math.round(mc.getBoundingClientRect().height) : null, chips,
                   log: /Log a watch/.test(document.querySelector('main').innerText), okrate: document.querySelectorAll('details.tvrate').length,
                   empty: (document.querySelector('.bigempty') || {}).innerText }; })()""")
        s1 = tt.shot("diary_tv")
        opened = None
        if m["okrate"]:
            tt.js("document.querySelector('details.tvrate summary').focus(); 1")
            tt.key("DPAD_CENTER", 0.8)
            opened = tt.js("(() => { const d = document.querySelector('details.tvrate'); return d.open ? d.querySelectorAll('button, a, input').length : 0; })()")
            tt.shot("diary_okrate_open")
            tt.key("DPAD_UP", 0.3)
            tt.js("document.querySelector('details.tvrate').open = false; 1")   # close again: nothing picked
        tt.fresh("/media/history", settle=4)
        h = tt.js("(() => ({ ratetv: /Rate TV by/.test(document.querySelector('main').innerText), head: [...document.querySelectorAll('main .seclabel, main h2')].map(x => x.innerText.trim().slice(0, 30)).slice(0, 4), okrate: document.querySelectorAll('details.tvrate').length }))()")
        s2 = tt.shot("history_tv")
        chips_ok = all(any(c.startswith(x) for c in m["chips"]) for x in ("All", "Films", "TV"))
        parts = [f"month row {m['month']} px", f"chips {m['chips'][:5]}", f"Log a watch {m['log']}", f"'OK to rate' rows {m['okrate']}",
                 f"strip opened ({opened} controls)" if opened is not None else "no unrated row to open", f"empty '{m['empty']}'",
                 f"To rate: 'Rate TV by' {h['ratetv']}, heads {h['head']}, OK-to-rate rows {h['okrate']}", s1, s2]
        if not m["month"] and not m["okrate"] and m["empty"]:
            return "DEFERRED", "joeytest has no diary rows: slim month row / chips / OK to rate not testable (JY-195 empty state shown). " + "; ".join(parts)
        ok = bool(m["month"]) and chips_ok and not m["log"] and not h["ratetv"] and (opened is None or opened > 0)
        return ("PASS" if ok else "FAIL", "; ".join(parts))
    if on(28):
        check(r, 28, "Diary: slim month row, All/Films/TV chips, OK to rate; To rate without 'Rate TV by'", c28)

    # ---------------------------------------------------------------- JY-248
    def c29():
        tt = dev()
        first = tt.fresh("/a/media", settle=5)
        tt.key("DPAD_UP")
        stops = [tt.f()]
        for _ in range(5):
            tt.key("DPAD_RIGHT", 0.45)
            stops.append(tt.f())
        tt.shot("j8_signout_pill")
        ok = first and first["poster"] and stops[0] and stops[0]["brand"] and stops[-1] and stops[-1]["chip"]
        return ("PASS" if ok else "FAIL", f"first {fdesc(first)}; Up -> {fdesc(stops[0])}; Right x5 -> {[s and s['t'][:14] for s in stops[1:]]} "
                f"(6 presses, pill reached {bool(stops[-1] and stops[-1]['chip'])})")
    if on(29):
        check(r, 29, "Home poster: Up = 'Joey Media', Right x5 = sign-out pill (6 presses)", c29)

    def c30():
        tt = dev()
        tt.fresh("/media/movies", settle=5)
        tt.goto("/a/media", settle=3)
        tt.clear_memory()
        tt.goto("/media/movies", settle=5)
        stops = tt.ups_to_top()
        pill = stops[-1] if stops else None
        tt.key("DPAD_LEFT")
        left = tt.f()
        tt.key("DPAD_CENTER", 0.2)
        u, ms = C.wait_url(tt, r"^/a/media$")
        time.sleep(1.5)
        f = tt.f()
        firstp = tt.js("(() => { const a = document.querySelector('main a.card-poster'); return a && a === document.activeElement; })()")
        tt.shot("j248_home_from_brand")
        ok = pill and pill["cur"] and "Movies" in pill["t"] and left and left["brand"] and u and firstp
        return ("PASS" if ok else "FAIL", f"Up x{len(stops)} -> {fdesc(pill)}; Left -> {fdesc(left)}; OK -> {u} in {ms} ms, focus {fdesc(f)}, first poster {firstp}")
    if on(30):
        check(r, 30, "Movies: Up = Movies pill, Left = 'Joey Media', OK = Home on the first poster", c30)

    def c31():
        tt = dev()
        det, ok = [], True
        for label, path in (("Movies", "/media/movies"), ("TV shows", "/media/tv"), ("Diary", "/media/diary"), ("Discover", "/media/discover")):
            first = tt.fresh(path, settle=5)
            stops = tt.ups_to_top(5)
            last = stops[-1] if stops else None
            good = bool(last and last["top"] and last["cur"] and label in last["t"])
            ok &= good
            det.append(f"{label}: {fdesc(first)} -> Up x{len(stops)} -> {fdesc(last)}{'' if good else ' FAIL'}")
        return ("PASS" if ok else "FAIL", "; ".join(det))
    if on(31):
        check(r, 31, "Up from Movies / TV shows / Diary / Discover lands on that pill", c31)

    # ---------------------------------------------------------------- JY-190 sign-in (#10) + by-eye #7
    def c10():
        tt = dev()
        r.write_guard("sign joeytest out of the debug app, capture sign-in, approve a new Quick Connect code as joeytest")
        uid = J.full_id(r, J.JOEYTEST).replace("-", "")
        before = D.joeytest_devices(r, uid)
        tt.goto("/a/media", settle=3)
        tt.key("DPAD_UP")
        for _ in range(6):
            fo = tt.f()
            if fo and fo["chip"]:
                break
            tt.key("DPAD_RIGHT", 0.45)
        tt.key("DPAD_CENTER", 1.2)
        tt.key("DPAD_LEFT", 0.6)
        fo = tt.f()
        if not fo or "sign out" not in (fo["t"] or "").lower():
            tt.key("BACK")
            return "FAIL", f"focus not on Sign out ({fdesc(fo)}) - nothing pressed"
        tt.key("DPAD_CENTER", 0.2)
        u, ms = C.wait_url(tt, r"^/signin")
        time.sleep(2.5)
        tt.shot("dev_signin")
        tt.js("window.joeyTV && window.joeyTV.focusFirst()")
        tt.js("(() => { const s = document.querySelector('.signin-panel summary'); if (s) s.focus(); return !!s; })()")
        tt.key("DPAD_CENTER", 1.0)
        pw = tt.js(r"""(() => { const p = document.querySelector('input[type=password]'); if (!p) return null; const r = p.getBoundingClientRect();
          const qc = document.querySelector('.qc-code'); return { top: Math.round(r.top), bottom: Math.round(r.bottom), H: innerHeight,
          full: r.top >= 0 && r.bottom <= innerHeight && r.height > 0, qcShown: !!(qc && qc.getBoundingClientRect().height) }; })()""")
        state["pw"] = pw
        state["pw_shot"] = tt.shot("by_eye_07_signin_password")
        tt.key("BACK", 1.5)
        if D.top_pkg(r) != PKG:
            ensure_app(r)
        time.sleep(1.5)
        time.sleep(1.0)
        code = (tt.js("(document.querySelector('.qc-code') || {}).innerText || ''") or "").strip().replace(" ", "")
        if not re.fullmatch(r"\d{6}", code or ""):
            return "FAIL", f"no 6-digit code on /signin ({len(code or '')} chars); joeytest is SIGNED OUT on the TV - sign in by hand"
        mid = D.joeytest_devices(r, uid)
        try:
            out = r.hub_py(D.QC_AUTHORIZE, code, J.full_id(r, J.JOEYTEST)).strip()
        except Exception as e:  # noqa: BLE001
            out = f"error {type(e).__name__}"
        fallback = ""
        if out != "true":   # restore the session the old way, but the check is a FAIL
            devs = sorted(D.joeytest_devices(r, uid), key=lambda d: d.get("DateLastActivity", ""))
            if len(devs) >= 2:
                r.hub_py(C.DEVICE_DELETE, devs[-1]["Id"])
            tt.goto("/signin", settle=4)
            code = (tt.js("(document.querySelector('.qc-code') || {}).innerText || ''") or "").strip().replace(" ", "")
            out2 = r.hub_py(D.QC_AUTHORIZE, code, J.full_id(r, J.JOEYTEST)).strip() if re.fullmatch(r"\d{6}", code) else "no code"
            fallback = f"; fallback (stale-device delete) approve -> {out2[:10]}"
        u2, ms2 = C.wait_url(tt, r"^/(a/media|media/)", timeout=25)
        after = D.joeytest_devices(r, uid)
        tt.shot("dev_signin_done")
        ok = out == "true" and bool(u2) and len(after) == 1
        return ("PASS" if ok else "FAIL",
                f"Joey Media devices before {len(before)}, after sign-out {len(mid)}; signed out in {ms} ms; QC approve -> {out[:12]}"
                f"{fallback}; back on {u2} in {ms2} ms; devices now {len(after)} (want 1)")
    if on(10):
        check(r, 10, "signin --allow-write without the stale-device step (no 403)", c10)

    def c7():
        pw = state.get("pw")
        nf = os.path.join(OUT, "shots", "device", "by_eye_07_notfound.png")
        return "BYEYE", (f"password field {pw} ({state.get('pw_shot')}); 404 shot {os.path.relpath(nf, OUT) if os.path.exists(nf) else 'missing (run #11)'}")
    if on(7):
        check(r, 7, "by eye: sign-in password form fully shown; bad URL centred 'No page here' + Back", c7)

    # ---------------------------------------------------------------- 36-39 whole-run comparison
    if on(36):
        def c36():
            if want is not None and "cap" not in want and not cap().get("device"):
                raise RuntimeError("no device capture")
            C.cmd_local(r)
            C.cmd_browser(r)
            base = json.load(open(BASE, encoding="utf-8"))
            now = cap()
            rises, compared = [], 0
            for sec in ("device", "local", "browser"):
                for name, a in now.get(sec, {}).items():
                    b = base.get(sec, {}).get(name)
                    if name.startswith("_") or not isinstance(a, dict) or not b:
                        continue
                    compared += 1
                    for k, lab in (("tinyN", "tiny"), ("lowContrastN", "lowC"), ("outsideSafeN", "outSafe")):
                        if a.get(k, 0) > b.get(k, 0):
                            rises.append(f"{sec}/{name} {lab} {b.get(k, 0)}->{a.get(k, 0)}")
                    if "probe" in a and "probe" in b and len(a["probe"]["offscreen"]) > len(b["probe"]["offscreen"]):
                        rises.append(f"{sec}/{name} offscreen {len(b['probe']['offscreen'])}->{len(a['probe']['offscreen'])}")
            return ("PASS" if not rises else "FAIL", f"{compared} page captures compared; rises: {rises or 'none'}")
        check(r, 36, "capture.json vs 2026-10-23: tiny / lowContrast / outsideSafe / offscreen do not rise", c36)

    if on(38) or on(39) or on("F"):
        multi_device(r, on)

    if on(37):
        def c37():
            n = sum(len([f for f in fs if f.endswith(".png")]) for _, _, fs in os.walk(os.path.join(OUT, "shots")))
            return ("PASS" if n else "FAIL", f"{n} screenshots under {OUT}")
        check(r, 37, "screenshots saved to review\\tv-ui-2026-10-25", c37)

    if want and want & {"32", "33", "34", "35"}:
        shell_102(r, want)


# ------------------------------------------------------------------------------------------------- 32-35: shell 1.0.2
PY = sys.executable
CODE_102 = 2026102501
RUN_102 = "40165149330"   # tv.yml on main 18c0d86 (JY-191 merge): app-debug.apk + the release


def sub(r, args, timeout=900):
    """Run one of the window scripts; return (exit code, its summary lines)."""
    p = subprocess.run([PY, os.path.join(HERE, args[0])] + args[1:], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=HERE)
    lines = [ln for ln in (p.stdout or "").splitlines() if re.search(r"\b(PASS|FAIL|SKIP|MANUAL|INFO)\b", ln)]
    r.log(f"[{' '.join(args)}] exit {p.returncode}")
    for ln in lines[-14:]:
        r.log("   " + ln)
    return p.returncode, lines


def shell_102(r, want):
    def on(n):
        return str(n) in want

    def node_text(x, rid):
        m = re.search(r'<node[^>]*text="([^"]*)"[^>]*id/' + rid + r'"[^>]*focused="(true|false)"', x)
        return (m.group(1), m.group(2) == "true") if m else (None, None)

    def c32():
        det = []
        rc_in, _ = sub(r, ["release_check.py", "inside"])
        rc_out, _ = sub(r, ["release_check.py", "outside"])
        det.append(f"release_check inside exit {rc_in}, outside exit {rc_out}")
        # the release build updates itself (the friend path): Update now -> installer Update (focus starts on Cancel)
        rel = D.PKG_RELEASE
        v0 = D.installed_version(r, rel)
        if v0 != CODE_102:
            wake(r)
            D.force_stop(r, rel)
            D.launch_app(r, rel, wait=10)
            x = ui_dump(r)
            txt, foc = node_text(x, "update_now")
            if not txt:
                det.append(f"release {v0}: no update prompt on launch (throttle?)")
            else:
                if not foc:
                    D.sh(r, "input keyevent KEYCODE_DPAD_LEFT")
                    time.sleep(0.8)
                    txt, foc = node_text(ui_dump(r), "update_now")
                if foc:
                    D.sh(r, "input keyevent KEYCODE_DPAD_CENTER")
                    time.sleep(12)
                    x = ui_dump(r)
                    # Android's installer: "Do you want to update this app?" with Cancel focused; press Update only
                    for _ in range(3):
                        m = re.search(r'<node[^>]*text="(Update|Install)"[^>]*focused="true"', x)
                        if m:
                            D.sh(r, "input keyevent KEYCODE_DPAD_CENTER")
                            break
                        if re.search(r'text="(Update|Install)"', x):
                            D.sh(r, "input keyevent KEYCODE_DPAD_LEFT")
                            time.sleep(0.8)
                            x = ui_dump(r)
                        else:
                            break
                    J.wait_for(r, "release versionCode 1.0.2", lambda: D.installed_version(r, rel) == CODE_102, 90, 5)
            D.sh(r, "input keyevent KEYCODE_HOME")
        v1 = D.installed_version(r, rel)
        det.append(f"release build {v0} -> {v1}")
        # the debug build (DevTools for 33-35): CI app-debug.apk of the same commit, adb install -r (keeps sign-in)
        dv0 = D.installed_version(r, PKG)
        if dv0 != CODE_102:
            sub(r, ["wp_b9_device.py", "install", "--run-id", RUN_102, "--allow-write"])
        dv1 = D.installed_version(r, PKG)
        ensure_app(r)
        ua = D.js(r, "navigator.userAgent") or ""
        ua_v = (re.search(r"JoeyTV/(\S+ \(\d+\))", ua) or [None, "?"])[1]
        signed = "/signin" not in D.page_url(r)
        det.append(f"debug build {dv0} -> {dv1}, UA JoeyTV/{ua_v}, still signed in {signed}")
        ok = rc_in == 0 and rc_out == 0 and v1 == CODE_102 and dv1 == CODE_102
        return ("PASS" if ok else "FAIL"), "; ".join(det)
    if on(32):
        check(r, 32, "1.0.2 published (release_check) and the TV updated to 1.0.2", c32)

    def c33():
        rc, lines = sub(r, ["wp_b9_device.py", "back"], timeout=900)
        cases = {c: next((ln for ln in lines if f"back ({c})" in ln), "") for c in "abcd"}
        ok = all(re.search(r"\bPASS\b", v) for v in cases.values())
        ensure_app(r)
        return ("PASS" if ok else "FAIL"), " | ".join(f"({c}) " + re.sub(r"^.*?\b(PASS|FAIL|MANUAL|SKIP)\b", r"\1", v)[:120] for c, v in cases.items())
    if on(33):
        check(r, 33, "wp_b9_device.py back (a)-(d) on 1.0.2", c33)

    def c34():
        r.write_guard("case (f): sign joeytest out of the debug app, Back on /signin, reopen, approve Quick Connect as joeytest")
        ensure_app(r)
        t = T(r)
        uid = J.full_id(r, J.JOEYTEST).replace("-", "")
        t.goto("/a/media", settle=4)
        t.key("DPAD_UP")
        for _ in range(6):
            fo = t.f()
            if fo and fo["chip"]:
                break
            t.key("DPAD_RIGHT", 0.45)
        t.key("DPAD_CENTER", 1.2)
        t.key("DPAD_LEFT", 0.6)
        fo = t.f()
        if not fo or "sign out" not in (fo["t"] or "").lower():
            t.key("BACK")
            return "FAIL", f"focus not on Sign out ({fdesc(fo)}) - nothing pressed"
        t.key("DPAD_CENTER", 0.2)
        C.wait_url(t, r"^/signin")
        time.sleep(2.5)
        code1 = (t.js("(document.querySelector('.qc-code') || {}).innerText || ''") or "").strip().replace(" ", "")
        t.shot("f_signin")
        D.sh(r, "input keyevent KEYCODE_BACK")
        time.sleep(3)
        exited = D.top_pkg(r) != PKG
        D.shot(r, "f_after_back")
        D.launch_app(r, PKG, wait=9)
        dismiss_update(r)
        u = D.page_url(r)
        code2 = (D.js(r, "(document.querySelector('.qc-code') || {}).innerText || ''") or "").strip().replace(" ", "")
        t.shot("f_reopen")
        out = r.hub_py(D.QC_AUTHORIZE, code2, J.full_id(r, J.JOEYTEST)).strip() if re.fullmatch(r"\d{6}", code2) else "no code"
        u2, _ = C.wait_url(t, r"^/(a/media|media/)", timeout=25)
        devs = D.joeytest_devices(r, uid)
        same = bool(code1) and code1 == code2
        ok = exited and "/signin" in u and same and out == "true" and u2
        return ("PASS" if ok else "FAIL",
                f"sign out -> /signin; Back -> app exited {exited}; reopen -> {urllib.parse.urlparse(u).path}, same code {same} "
                f"(no second code burnt); QC approve -> {out[:10]}; signed in again on {u2}; Joey Media devices {len(devs)}")
    if on(34):
        check(r, 34, "case (f): Back on /signin exits; reopen = same flow, no second code", c34)

    def c35():
        ensure_app(r)
        t = T(r)
        t.goto("/a/media", settle=3)
        ws = D.page_ws(r)
        try:
            ws.call("Page.navigate", url="https://media.joeyhome.net:9/")
        except Exception:  # noqa: BLE001 - the load fails by design
            pass
        finally:
            ws.close()
        time.sleep(5)
        x = ui_dump(r)
        texts = re.findall(r'text="([^"]{4,})"', x)
        s = t.shot("n_badurl_102")
        good = any("Couldn't open this page" in s_ or "Couldn’t open this page" in s_ for s_ in texts)
        bad = any("Check that this TV is online" in s_ for s_ in texts)
        D.force_stop(r, PKG)
        ensure_app(r)
        return ("PASS" if good and not bad else "FAIL", f"native texts {texts[:5]}; {s}")
    if on(35):
        check(r, 35, "optional: bad URL shows 'Couldn't open this page'", c35)


# ------------------------------------------------------------------------------------------------- 38 / 39: headless Chrome
PROFILES = {
    "desktop": (1440, 900, 1, False, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
    "ipad": (820, 1180, 2, True, "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
    "phone": (390, 844, 3, True, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
}

NAV_JS = r"""(() => { const vis = e => e.getBoundingClientRect().height > 0;
  const links = [...document.querySelectorAll('a')].filter(vis).map(a => a.innerText.trim());
  return { tv: document.documentElement.classList.contains('tv'), overviewLink: links.includes('Overview'), title: document.title,
           head: [...document.querySelectorAll('h1, .pagehead h1, .seclabel')].filter(vis).map(h => h.innerText.trim().slice(0, 30)).slice(0, 10),
           welcome: !!document.querySelector('.welcome'), hOverflow: document.documentElement.scrollWidth > innerWidth + 1,
           following: (document.body.innerText.match(/Following [^\n]{0,40}/g) || []).length }; })()"""


def multi_device(r, on):
    def body():
        D.need_device(r)
        cookies = [c for c in C.tv_cookies(r) if "joeyhome.net" in c.get("domain", "")]
        pg = cap().get("device", {}).get("_pages", {})
        res = {}
        for prof, (w, h, dpr, mobile, ua) in PROFILES.items():
            udir = os.path.join(J.SCRATCH, f"tvs_chrome_{prof}")
            port = 9340 + list(PROFILES).index(prof)
            proc = subprocess.Popen([C.CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={udir}",
                                     f"--window-size={w},{h}", "--hide-scrollbars", "--no-first-run", "about:blank"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                pages_ = []
                for _ in range(40):
                    try:
                        pages_ = [p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)) if p["type"] == "page"]
                        if pages_:
                            break
                    except OSError:
                        time.sleep(0.25)
                ws = D.WS(pages_[0]["webSocketDebuggerUrl"])
                ws.call("Network.enable")
                ws.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=mobile)
                ws.call("Emulation.setUserAgentOverride", userAgent=ua)
                for c in cookies:
                    ws.call("Network.setCookie", **{k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly") if k in c},
                            **({"sameSite": c["sameSite"]} if c.get("sameSite") else {}))
                t = C.Loc(r, ws, prof)
                for name in ("overview", "title_movie", "title_tmdb", "person", "movies_tonight", "title_series"):
                    url = {"overview": "/a/media", "movies_tonight": "/media/movies/tonight"}.get(name) or pg.get(name)
                    if not url:
                        continue
                    t.goto(url, settle=6)
                    m = t.js(NAV_JS)
                    m["shot"] = t.shot(f"{prof}_{name}")
                    sh = ws.call("Page.getLayoutMetrics")["cssContentSize"]["height"]
                    full = ws.call("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                                   clip={"x": 0, "y": 0, "width": w, "height": min(sh, 3200), "scale": 1})
                    with open(os.path.join(t.dir, f"{prof}_{name}_full.png"), "wb") as f:
                        f.write(base64.b64decode(full["data"]))
                    res[f"{prof}/{name}"] = m
                ws.close()
            finally:
                proc.terminate()
        C.save("multidevice", "all", res)
        return res

    res = {}

    def run_once():
        if not res:
            res.update(body())
        return res

    def c38():
        rr = run_once()
        det = [f"{k}: tv {v['tv']}, overflow {v['hOverflow']}" for k, v in rr.items() if not k.endswith("/overview") and not k.startswith("ipad")]
        return "BYEYE", "; ".join(det) + f"; shots in {os.path.join(OUT, 'shots')}\\(desktop|phone)"
    def c39():
        rr = run_once()
        det = [f"{k}: Overview link {v['overviewLink']}, welcome {v['welcome']}, heads {v['head'][:6]}, title '{v['title']}'" for k, v in rr.items() if k.endswith("/overview")]
        bad = any(v["overviewLink"] or v["tv"] for k, v in rr.items() if k.endswith("/overview"))
        return ("FAIL" if bad else "BYEYE"), "; ".join(det)
    def cF():
        rr = run_once()
        hits = {k: v["following"] for k, v in rr.items() if k.split("/")[1] in ("title_tmdb", "title_series", "title_movie")}
        return ("PASS" if not any(hits.values()) else "FAIL", f"'Following' occurrences per page (any device): {hits}")
    if on("F"):
        check(r, "F", "phone/desktop TMDB + show page as joeytest: no household 'Following'", cF)
    if on(38):
        check(r, 38, "desktop 1440 / phone 390: title, TMDB, person, Tonight as before", c38)
    if on(39):
        check(r, 39, "desktop / iPad / phone Home: same shelves + welcome, no Overview pill", c39)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="comma list of check numbers (and/or 'cap')")
    p.add_argument("--out", help="output folder name under review (default tv-ui-2026-10-25)")
    a = p.parse_args()
    if a.out:
        global OUT
        OUT = os.path.join(os.path.dirname(HERE), "review", a.out)
        C.OUT, C.SHOT_DEV, C.SHOT_LOC = OUT, os.path.join(OUT, "shots", "device"), os.path.join(OUT, "shots", "local")
        C.CAPTURE = os.path.join(OUT, "capture.json")
    want = set(a.only.split(",")) if a.only else None
    r = J.Runner("tv_session_1025", allow_write=True)
    r.log_path = os.path.join(J.LOGDIR, "tv_session_1025.log")
    os.makedirs(OUT, exist_ok=True)
    r.log(f"=== tv_session_1025 {dt.datetime.now():%Y-%m-%d %H:%M} only={a.only or 'all now-items'} ===")
    try:
        run(r, want)
    finally:
        if want is None:
            for n in (32, 33, 34, 35):
                RESULTS.setdefault(n, ("WAITING", "shell 1.0.2 (JY-191): run with --only 32,33,34,35"))
        r.log("=== RESULTS by check number ===")
        for n in sorted(RESULTS, key=lambda x: (isinstance(x, str), str(x).zfill(3))):
            st, d = RESULTS[n]
            r.log(f"#{str(n):<3} {st:<8} {d[:400]}")
        prev = {}
        rp = os.path.join(J.LOGDIR, "tv_session_1025_by_check.json")
        if os.path.exists(rp):
            prev = json.load(open(rp, encoding="utf-8"))
        prev.update({str(n): {"status": s, "detail": J.redact(d), "at": dt.datetime.now().isoformat(timespec="seconds")} for n, (s, d) in RESULTS.items()})
        json.dump(prev, open(rp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
