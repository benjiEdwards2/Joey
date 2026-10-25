/* Joey Media TV mode (Joey TV WP-B3, 2026-10-21; Q34, Q41, D-P12). Loaded ONLY in TV mode (base.html / guest_signin.html
   link it when hub.media_front.tv_mode is true: the shell's JoeyTV/ user agent, or the ?tv=1 cookie). Vendored, no
   external asset, no dependency.

   What it owns (Chromium WebView has no spatial navigation, so CSS alone cannot move focus):
   * geometric D-pad focus: an arrow key moves focus to the nearest focusable in that direction (the WP-M mockup's
     scoring: a sideways move stays in its row, an up/down move prefers the column it is in); inside an open dialog only
     the dialog's own controls take part;
   * first focus on load (also when the WebView itself focuses the top bar before any key): the page's remembered link
     (Back memory, below), else [data-first], else the Play button ([data-jf-id]), else the first poster in <main>, else
     the current sub-tab (JY-187 G3: an empty Watchlist / To rate tab), else the first focusable in <main>, else the
     first on the page (WP-M spec: Overview = first poster, title = Play);
   * Back memory (JY-187 B1): per URL, the link last reached with a remote key in <main> and the scroll offset, put back
     on every new page (Back's reload, a boosted swap, the hand-off reopen, a back-forward-cache pageshow);
   * Up from the page into the top bar lands on the open section's pill (JY-248: on Home, with no pill current, the
     "Joey Media" title); Down from the title buttons into the rating
     chips lands on chip 1 (JY-187 B2/B3, P5);
   * Discover search (JY-194, R2): the friends' search field ([data-tv-search]) is the stop between the grid and the top
     bar (Up from the first row; Down from it = the first poster). It stays read-only while only focused, so passing it
     never raises the keyboard; OK makes it editable (the TV keyboard). Typing uses its own htmx trigger (debounced);
     Enter never submits the form: it fires that trigger only when the grid does not already show the query, then goes
     to the first result. Back with a query clears it to the trending grid, the field focused;
   * scroll-into-view: the focused poster is centred in its shelf, clamped at both ends (WP-M call 2 - the browser
     clamps scrollLeft), and its row is kept inside the 5 % overscan margin; focus in the top bar scrolls to the top;
   * focus restore after every htmx swap: when the swap removed or hid the focused element, focus goes back to the first
     focusable (the rule above) - a boosted navigation swaps the whole body, so it always lands on the new page's first;
   * window.joeyTV.back(): the shell's Back key asks this first (tv/ BackPolicy, WP-B7). Closes an open <dialog> (the
     trailer modal) and returns true; returns false when nothing was closed (the shell then goes back / exits);
   * JY-192 (U6): the Rate button ([data-tv-rate]) opens / closes the rating strip (#tv-rate; Back closes it too), and on a
     season / episode page ([data-tv-up]) Back goes to the series unless the page before was that series; JY-250: Back
     on that series then goes to the page before the episode (history.back()).
   * Q41: a trailer opens the YouTube app - in TV mode a click on [data-yt] navigates to its youtube.com href (the
     shell's UrlPolicy hands YouTube to ACTION_VIEW) instead of the in-page player; target="_blank" is dropped from
     links so every navigation reaches the shell's UrlPolicy in this WebView. */
(function () {
  'use strict';
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]),' +
    ' textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
  var OVERSCAN_Y = 27, OVERSCAN_X = 48, PAD = 14;
  /* a focused poster grows to 1.06 (tv.css) and carries a 4 px ring 3 px out: room kept so neither crosses the 5 %
     overscan margin (W5 2026-10-22, real TCL: the grown card + ring reached 96 % of the height and 4.6 % from the left) */
  var POSTER_GROW = 0.03, RING = 7;
  var KEYS = { ArrowLeft: 1, ArrowRight: 1, ArrowUp: 1, ArrowDown: 1 };
  var current = null;
  /* no remote key yet on this page: Android's WebView puts DOM focus on the first focusable (the brand link in the top
     bar) when the shell focuses the view after a load, which beat the WP-M first-focus rule (W5 2026-10-22, release
     build on the TCL: OK on a title page went to Overview instead of Play) */
  var keyed = false;

  function visible(el) {
    if (!el || !el.isConnected) return false;
    if (el.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    var st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none';
  }

  function openDialog() {
    var d = document.querySelector('dialog[open]');
    return d && visible(d) ? d : null;
  }

  /* The one-time Set up Jellyfin card is a full-screen overlay (WP-M screen 9): while it is up the D-pad stays on it. */
  function modal() {
    var d = openDialog();
    if (d) return d;
    var card = document.querySelector('.setup-card');
    return card && visible(card) ? card : null;
  }

  function scope() { return modal() || document; }

  function candidates() {
    return Array.prototype.filter.call(scope().querySelectorAll(FOCUSABLE), visible);
  }

  function firstIn(root) {
    if (!root) return null;
    var picks = ['[data-first]', '[data-jf-id]', '.card-poster', '.sectabs.sub [aria-current]', FOCUSABLE];
    for (var i = 0; i < picks.length; i++) {
      var found = Array.prototype.filter.call(root.querySelectorAll(picks[i]), visible);
      if (found.length) return found[0];
    }
    return null;
  }

  /* JY-187 (B1, 2026-10-24): Back memory. Back reloads the page (base.html: historyCacheSize 0 + refreshOnHistoryMiss)
     and focus went to the first poster at the top. Per URL (path + query) sessionStorage keeps the link last reached
     with a remote key inside <main> (its href and which of the links with that href it was) and the scroll offset; a
     page new to this document (restore() below) focuses that link and scrolls back. A move into the top bar or a
     dialog is never kept, so going Up to a pill and on to another section still comes back to the poster. */
  var MEMORY = 'joeyTV.back', MEMORY_URLS = 40;
  var page = null;   /* the URL restore() last set up */

  function here() { return window.location.pathname + window.location.search; }

  function memory() {
    try { return JSON.parse(window.sessionStorage.getItem(MEMORY)) || {}; } catch (e) { return {}; }
  }

  function linksTo(href) {
    var main = document.querySelector('main');
    return main ? Array.prototype.filter.call(main.querySelectorAll('a[href]'), function (l) {
      return l.getAttribute('href') === href && visible(l);
    }) : [];
  }

  function remember(el) {
    var main = document.querySelector('main'), href = el.tagName === 'A' && el.getAttribute('href');
    if (!href || !main || !main.contains(el) || modal()) return;
    var m = memory(), url = here();
    delete m[url];   /* added again at the end: the oldest URL goes first */
    m[url] = { h: href, n: Math.max(0, linksTo(href).indexOf(el)), y: window.scrollY };
    var urls = Object.keys(m);
    if (urls.length > MEMORY_URLS) delete m[urls[0]];
    try { window.sessionStorage.setItem(MEMORY, JSON.stringify(m)); } catch (e) { /* storage off or full: no memory */ }
  }

  function recall() {
    var e = memory()[here()];
    if (!e) return null;
    var links = linksTo(e.h), el = links[e.n] || links[0];
    return el ? { el: el, y: e.y } : null;
  }

  function first() {
    var d = modal();
    if (d) return firstIn(d);
    var m = recall();   /* JY-187: this page's remembered link comes before the WP-M rule */
    return m ? m.el : firstIn(document.querySelector('main')) || firstIn(document.body);
  }

  /* JY-194 (U8, R2): the Discover search field and the grid it fills (#discover-grid, data-q = the query it shows) */
  var SEARCH = '[data-tv-search]', GRID = '.reqgrid-wrap';
  var opening = false;       /* OK is re-focusing the field: its blur must not lock it again */
  var wantResults = false;   /* Enter sent a search: the swap's first poster takes the focus */
  var sentQuery = null;      /* the query Enter's search sent, until Back clears the field */

  function isSearch(el) { return !!(el && el.getAttribute && el.getAttribute('data-tv-search') !== null); }

  function searchField() {
    var s = document.querySelector(SEARCH);
    return s && visible(s) ? s : null;
  }

  function grid() { return document.querySelector(GRID); }

  function shownQuery() { var g = grid(); return g ? g.getAttribute('data-q') || '' : ''; }

  /* Enter on the field (OK on the remote, or the keyboard's search key). Never the form's submit (a page load). */
  function searchEnter(e, s) {
    e.preventDefault();
    if (s.readOnly) {   /* OK: editable, then focused again, so the WebView raises the TV keyboard */
      s.readOnly = false;
      opening = true;
      s.blur();
      s.focus();
      opening = false;
      return;
    }
    if (shownQuery() !== s.value.trim()) {   /* the debounce has not fetched this query yet: the field's own trigger */
      wantResults = true;
      sentQuery = s.value.trim();
      s.dispatchEvent(new Event('search'));
    }
    s.readOnly = true;
    setFocus(firstIn(grid()) || s);
  }

  /* Back with a query: the empty query through the same trigger (the cached trending shelves), the field focused */
  function clearSearch() {
    var s = searchField();
    if (!s || !(s.value || shownQuery())) return false;
    s.value = '';
    s.readOnly = true;
    wantResults = false;
    sentQuery = null;
    s.dispatchEvent(new Event('search'));
    setFocus(s);
    return true;
  }

  /* JY-192 (U6, Gate 1 pick 1B): the title page's rating is one Rate button ([data-tv-rate]) over the existing picker in
     #tv-rate (hidden). OK opens the strip with its first control focused; picking a number (htmx swaps in the rated
     form) closes it, the button then reads "Rated N" and keeps the focus; Back closes an open strip. */
  function rateBtn() { return document.querySelector('[data-tv-rate]'); }

  function rateStrip() { var b = rateBtn(); return b ? document.querySelector('[id="' + b.getAttribute('aria-controls') + '"]') : null; }

  function rateOpen() { var s = rateStrip(); return !!(s && s.getAttribute('hidden') === null); }

  function openRate() {
    var s = rateStrip(), b = rateBtn();
    if (!s || !b) return;
    s.removeAttribute('hidden');
    b.setAttribute('aria-expanded', 'true');
    setFocus(firstIn(s) || b);
  }

  function closeRate() {
    if (!rateOpen()) return false;
    var b = rateBtn();
    rateStrip().setAttribute('hidden', '');
    b.setAttribute('aria-expanded', 'false');
    setFocus(b);
    return true;
  }

  /* JY-192 (X1): a season / episode page names its series ([data-tv-up]); Back goes there. When the page before this
     one was that series, the shell's own Back already goes there (and JY-187 puts the focus back), so nothing is done.
     The trail (this URL and the one before it) is kept in sessionStorage by restore(). */
  var TRAIL = 'joeyTV.trail';

  function trail() {
    try { return JSON.parse(window.sessionStorage.getItem(TRAIL)) || {}; } catch (e) { return {}; }
  }

  function saveTrail(t) {
    try { window.sessionStorage.setItem(TRAIL, JSON.stringify(t)); } catch (e) { /* storage off: no trail */ }
  }

  function step() {
    var t = trail(), url = here();
    if (t.last === url) return;
    t.prev = t.last || null;
    t.last = url;
    if (t.up && url.split('?')[0] !== t.up.to) delete t.up;   /* JY-250: the up-mark lives only on the series it named */
    saveTrail(t);
  }

  /* JY-250 (#15, TV session 2026-10-25): the series replaces the episode's history entry, so the entry before it is the
     page before the episode (Home). The shell's Back there is WebView goBack(), which passes over an entry Chromium
     marked skippable (a page that navigated without a user gesture), and so missed Home. goUp() leaves an up-mark;
     Back on that series, straight after, is history.back() from the page, which never skips. */
  function goUp() {
    var el = document.querySelector('[data-tv-up]'), up = el && el.getAttribute('data-tv-up'), t = trail();
    if (!up || (t.prev || '').split('?')[0] === up) return false;
    if (t.prev) { t.up = { to: up, from: here() }; saveTrail(t); }
    window.location.replace(up);
    return true;
  }

  function upBack() {
    var t = trail(), u = t.up;
    if (!u) return false;
    delete t.up;   /* used once */
    saveTrail(t);
    if (here().split('?')[0] !== u.to || t.prev !== u.from || !(window.history && window.history.length > 1)) return false;
    window.history.back();
    return true;
  }

  function centreInShelf(el) {
    var shelf = el.closest('.carousel');
    if (!shelf) return;
    var item = el;
    while (item.parentElement && item.parentElement !== shelf) item = item.parentElement;
    var i = item.getBoundingClientRect(), s = shelf.getBoundingClientRect();
    shelf.scrollLeft += (i.left + i.width / 2) - (s.left + s.width / 2);   /* the browser clamps at both ends */
  }

  /* Bottom edge of everything pinned to the top: the top bar and, on Movies / TV shows, the sticky sub-tab row. */
  function stuckBottom() {
    var low = 0;
    Array.prototype.forEach.call(document.querySelectorAll('.topbar, .pagehead'), function (b) {
      if (getComputedStyle(b).position === 'sticky') low = Math.max(low, b.getBoundingClientRect().bottom);
    });
    return low;
  }

  function keepRowInView(el) {
    if (el.closest('.topbar')) { window.scrollTo(0, 0); return; }
    if (el.closest('.pagehead') && getComputedStyle(el.closest('.pagehead')).position === 'sticky') return;   /* sub-tabs stay put */
    var box = (el.closest('.carousel') || el).getBoundingClientRect();
    var grow = (el.classList.contains('card-poster') ? el.getBoundingClientRect().height * POSTER_GROW : 0) + RING;
    var top = stuckBottom() + PAD + grow;
    var bottom = window.innerHeight - OVERSCAN_Y - grow;
    if (box.top < top) window.scrollBy(0, box.top - top);
    else if (box.bottom > bottom) window.scrollBy(0, Math.min(box.bottom - bottom, box.top - top));
  }

  /* a poster in the first / last column grows inward, so its grown edge + ring stay inside the side margins */
  function edgeOrigin(el) {
    if (!el.classList.contains('card-poster')) return;
    var b = el.getBoundingClientRect(), grow = b.width * POSTER_GROW + RING;
    el.style.transformOrigin = b.left - grow < OVERSCAN_X ? 'left center'
      : (b.right + grow > window.innerWidth - OVERSCAN_X ? 'right center' : '');
  }

  function setFocus(el) {
    if (!el) return;
    if (current && current !== el) current.classList.remove('tv-focus');
    current = el;
    el.classList.add('tv-focus');   /* the ring also shows where :focus-visible does not (headless, unfocused window) */
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    centreInShelf(el);
    edgeOrigin(el);   /* after the shelf scroll; the .12 s scale transition has not grown it yet */
    keepRowInView(el);
  }

  function active() {
    var a = document.activeElement;
    if (a && a !== document.body && visible(a) && scope().contains(a)) return a;
    return current && visible(current) && scope().contains(current) ? current : null;
  }

  function move(dir) {
    var a = active();
    if (!a) { setFocus(first()); return; }
    var r = a.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, best = null, bs = Infinity;
    candidates().forEach(function (c) {
      if (c === a || c.contains(a) || a.contains(c)) return;
      var q = c.getBoundingClientRect(), dx = q.left + q.width / 2 - cx, dy = q.top + q.height / 2 - cy, score;
      if (dir === 'ArrowRight' || dir === 'ArrowLeft') {
        if (dir === 'ArrowRight' ? dx <= 2 : dx >= -2) return;
        if (Math.abs(dy) > Math.max(r.height, q.height) * 0.6) return;   /* stay in the row */
        score = Math.abs(dx) + Math.abs(dy) * 3;
      } else {
        if (dir === 'ArrowDown' ? dy <= 2 : dy >= -2) return;
        score = Math.abs(dy) + Math.abs(dx) * 2.2;
      }
      if (score < bs) { bs = score; best = c; }
    });
    /* JY-187 (B2/B3): Up from the page into the top bar lands on the open section's pill, not the nearest control (the
       brand), so another section or the sign-out pill is one Up and a few Rights away */
    if (best && dir === 'ArrowUp' && best.closest('.topbar') && !a.closest('.topbar')) {
      var pill = document.querySelector('.toplinks a[aria-current]'), s = searchField();
      /* JY-194: the Discover search field above the page comes first */
      if (s && s !== a && s.getBoundingClientRect().bottom <= r.top) best = s;
      else if (pill && visible(pill)) best = pill;
      /* JY-248: Home has no section pill (no Overview); the "Joey Media" title is its stop (OK = Home) */
      else if (!pill) { var home = document.querySelector('.topbar .brand'); if (home && visible(home)) best = home; }
    }
    /* JY-194: Down from the search field lands on the grid's first poster */
    if (dir === 'ArrowDown' && isSearch(a)) best = firstIn(grid()) || best;
    /* JY-187 (P5): Down from the title buttons into the rating row lands on its first control (chip 1), not the chip
       nearest the button */
    if (best && dir === 'ArrowDown' && a.closest('.hero-detail-btns') && best.closest('.tv-rate')) {
      best = firstIn(best.closest('.tv-rate')) || best;
    }
    if (best) { setFocus(best); remember(best); }
  }

  function typing(el) {
    return el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !/^(button|submit|checkbox|radio)$/i.test(el.type)));
  }

  document.addEventListener('keydown', function (e) {
    keyed = true;
    var a = document.activeElement;
    if (e.key === 'Enter' && isSearch(a) && !e.altKey && !e.ctrlKey && !e.metaKey) { searchEnter(e, a); return; }
    if (!KEYS[e.key] || e.altKey || e.ctrlKey || e.metaKey) return;
    if (typing(a) && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return;   /* the caret moves in a text box */
    if (a && a.tagName === 'SELECT') return;
    e.preventDefault();
    move(e.key);
  }, true);

  document.addEventListener('focusin', function (e) {
    if (!keyed && e.target && e.target.closest && e.target.closest('.topbar')) {
      var f = first();
      if (f && f !== e.target && !f.closest('.topbar')) { setFocus(f); return; }
    }
    if (e.target && e.target.classList && e.target !== current && visible(e.target)) {
      if (current) current.classList.remove('tv-focus');
      current = e.target;
      current.classList.add('tv-focus');
    }
  });

  /* JY-194 (review 2026-10-25): Enter within the 400 ms debounce sent the query, then the pending keyup request sent it
     again. A keyup request from the field for the query Enter sent or the grid shows is cancelled. */
  document.addEventListener('htmx:beforeRequest', function (e) {
    var d = e.detail || {}, ev = d.requestConfig && d.requestConfig.triggeringEvent;
    if (!isSearch(d.elt) || !ev || ev.type !== 'keyup') return;
    var q = d.elt.value.trim();
    if (q === sentQuery || q === shownQuery()) e.preventDefault();
  });

  /* JY-194: leaving the search field locks it again (read-only until the next OK) */
  document.addEventListener('focusout', function (e) {
    if (isSearch(e.target) && !opening) e.target.readOnly = true;
  });

  /* JY-192: OK on the Rate button opens / closes the strip; a swap inside an open strip (a number picked, or Undo) */
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('[data-tv-rate]') : null;
    if (!b) return;
    e.preventDefault();
    if (!closeRate()) openRate();
  });

  document.addEventListener('htmx:afterSwap', function () {
    if (!rateOpen()) return;
    var n = rateStrip().querySelector('.rated .stat-number'), label = rateBtn().querySelector('.tv-ratelbl');
    if (label) label.textContent = n ? 'Rated ' + n.textContent.trim() : 'Rate';
    if (n) closeRate(); else setFocus(firstIn(rateStrip()) || rateBtn());
  });

  /* Q41: the trailer goes to the YouTube app, not the in-page player (capture: runs before the page's own handler). */
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[data-yt]') : null;
    if (!a || !a.href) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    window.location.href = a.href;
  }, true);

  function dropBlankTargets(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('a[target="_blank"]'), function (a) {
      a.removeAttribute('target');
    });
  }

  function restore() {
    dropBlankTargets(document);
    step();   /* JY-192: the trail Back = series reads */
    /* JY-187 (B1): a page this document has not set up yet (a full load, a boosted swap to another URL, Back, the
       pageshow below) gets its remembered link and scroll back. htmx scrolls a boosted page to the top after
       afterSettle, so the scroll is applied once more after that has run. */
    var m = page !== here() ? recall() : null;
    page = here();
    if (m) {
      window.scrollTo(0, m.y);
      setFocus(m.el);
      setTimeout(function () { if (current === m.el) { window.scrollTo(0, m.y); keepRowInView(m.el); } }, 0);
    }
    /* a new page (a full load, or a boosted swap / Back, which reset keyed - below): the WebView can focus the brand
       before this deferred script adds its focusin listener, so a top-bar focus found here before any key is also
       replaced by first() */
    /* JY-194: the search field is read-only unless it is being typed in; after Enter's search the results' first
       poster takes the focus once they land (unless focus has moved on outside the grid) */
    var s = searchField();
    if (s && s !== document.activeElement) s.readOnly = true;
    if (wantResults) {
      wantResults = false;
      var r = firstIn(grid()), held = active();
      if (r && (!held || held.closest(GRID))) { setFocus(r); return; }
    }
    var a = active(), f = first();
    if (!a || (!keyed && a.closest('.topbar') && f && !f.closest('.topbar'))) setFocus(f);
  }

  window.joeyTV = {
    /* The shell's Back key: true = a web dialog was closed, the Rate strip closed (JY-192), a Discover search cleared
       (JY-194), or a season / episode page replaced by its series (JY-192, X1), or that series gone back from
       (JY-250); false = nothing to do here. */
    back: function () {
      var d = openDialog();
      /* JY-194: results showing -> the trending grid, field focused */
      if (!d) return closeRate() || clearSearch() || goUp() || upBack();
      var close = d.querySelector('[data-close], .dialog-close, button[value="cancel"]');
      if (close) close.click(); else d.close();
      if (d.open) d.close();
      /* Joey TV WP-B4: a dialog that knows its opener (the Discover request panel: the poster) gives focus back to it */
      setFocus(d._opener && visible(d._opener) ? d._opener : first());
      return true;
    },
    focusFirst: function () { setFocus(first()); }
  };

  /* A boosted navigation is a new page in the same document (W5 2026-10-22, CDP log on the TCL: OK on a poster in
     /media/movies set keyed, htmx swapped in /media/item/<id>, the WebView then focused the brand and both guards let
     it stay, so OK went to Overview instead of Play). Reset keyed when a boosted response is swapped in (htmx 2.0.4:
     beforeSwap detail.boosted / shouldSwap, read after joey.js's asset check) and on Back (historyRestore), so the
     brand focus and restore() go to first(). A partial swap (request panel, dialog, shelf) keeps keyed. */
  document.addEventListener('htmx:beforeSwap', function (e) {
    if (e.detail.boosted && e.detail.shouldSwap) keyed = false;
  });
  document.addEventListener('htmx:afterSettle', restore);
  document.addEventListener('htmx:historyRestore', function () { keyed = false; restore(); });
  /* JY-187 (B1): a page shown again from the back-forward cache is set up again (memory focus + scroll) */
  window.addEventListener('pageshow', function (e) { if (e.persisted) { page = null; restore(); } });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restore);
  else restore();
})();
