/* Joey Media TV mode (Joey TV WP-B3, 2026-10-21; Q34, Q41, D-P12). Loaded ONLY in TV mode (base.html / guest_signin.html
   link it when hub.media_front.tv_mode is true: the shell's JoeyTV/ user agent, or the ?tv=1 cookie). Vendored, no
   external asset, no dependency.

   What it owns (Chromium WebView has no spatial navigation, so CSS alone cannot move focus):
   * geometric D-pad focus: an arrow key moves focus to the nearest focusable in that direction (the WP-M mockup's
     scoring: a sideways move stays in its row, an up/down move prefers the column it is in); inside an open dialog only
     the dialog's own controls take part;
   * first focus on load: [data-first], else the Play button ([data-jf-id]), else the first poster in <main>, else the
     first focusable in <main>, else the first on the page (WP-M spec: Overview = first poster, title = Play);
   * scroll-into-view: the focused poster is centred in its shelf, clamped at both ends (WP-M call 2 - the browser
     clamps scrollLeft), and its row is kept inside the 5 % overscan margin; focus in the top bar scrolls to the top;
   * focus restore after every htmx swap: when the swap removed or hid the focused element, focus goes back to the first
     focusable (the rule above) - a boosted navigation swaps the whole body, so it always lands on the new page's first;
   * window.joeyTV.back(): the shell's Back key asks this first (tv/ BackPolicy, WP-B7). Closes an open <dialog> (the
     trailer modal) and returns true; returns false when nothing was closed (the shell then goes back / exits).
   * Q41: a trailer opens the YouTube app - in TV mode a click on [data-yt] navigates to its youtube.com href (the
     shell's UrlPolicy hands YouTube to ACTION_VIEW) instead of the in-page player; target="_blank" is dropped from
     links so every navigation reaches the shell's UrlPolicy in this WebView. */
(function () {
  'use strict';
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]),' +
    ' textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
  var OVERSCAN_Y = 27, PAD = 14;
  var KEYS = { ArrowLeft: 1, ArrowRight: 1, ArrowUp: 1, ArrowDown: 1 };
  var current = null;

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

  function scope() { return openDialog() || document; }

  function candidates() {
    return Array.prototype.filter.call(scope().querySelectorAll(FOCUSABLE), visible);
  }

  function firstIn(root) {
    if (!root) return null;
    var picks = ['[data-first]', '[data-jf-id]', '.card-poster', FOCUSABLE];
    for (var i = 0; i < picks.length; i++) {
      var found = Array.prototype.filter.call(root.querySelectorAll(picks[i]), visible);
      if (found.length) return found[0];
    }
    return null;
  }

  function first() {
    var d = openDialog();
    if (d) return firstIn(d);
    return firstIn(document.querySelector('main')) || firstIn(document.body);
  }

  function centreInShelf(el) {
    var shelf = el.closest('.carousel');
    if (!shelf) return;
    var item = el;
    while (item.parentElement && item.parentElement !== shelf) item = item.parentElement;
    var i = item.getBoundingClientRect(), s = shelf.getBoundingClientRect();
    shelf.scrollLeft += (i.left + i.width / 2) - (s.left + s.width / 2);   /* the browser clamps at both ends */
  }

  function keepRowInView(el) {
    if (el.closest('header, .topbar')) { window.scrollTo(0, 0); return; }
    var box = (el.closest('.carousel') || el).getBoundingClientRect();
    var bar = document.querySelector('.topbar');
    var top = (bar && getComputedStyle(bar).position !== 'static' ? bar.getBoundingClientRect().bottom : 0) + PAD;
    var bottom = window.innerHeight - OVERSCAN_Y;
    if (box.top < top) window.scrollBy(0, box.top - top);
    else if (box.bottom > bottom) window.scrollBy(0, Math.min(box.bottom - bottom, box.top - top));
  }

  function setFocus(el) {
    if (!el) return;
    if (current && current !== el) current.classList.remove('tv-focus');
    current = el;
    el.classList.add('tv-focus');   /* the ring also shows where :focus-visible does not (headless, unfocused window) */
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    centreInShelf(el);
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
    if (best) setFocus(best);
  }

  function typing(el) {
    return el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !/^(button|submit|checkbox|radio)$/i.test(el.type)));
  }

  document.addEventListener('keydown', function (e) {
    if (!KEYS[e.key] || e.altKey || e.ctrlKey || e.metaKey) return;
    var a = document.activeElement;
    if (typing(a) && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return;   /* the caret moves in a text box */
    if (a && a.tagName === 'SELECT') return;
    e.preventDefault();
    move(e.key);
  }, true);

  document.addEventListener('focusin', function (e) {
    if (e.target && e.target.classList && e.target !== current && visible(e.target)) {
      if (current) current.classList.remove('tv-focus');
      current = e.target;
      current.classList.add('tv-focus');
    }
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
    if (!active()) setFocus(first());
  }

  window.joeyTV = {
    /* The shell's Back key: true = a web dialog was closed here (stay on the page); false = nothing to close. */
    back: function () {
      var d = openDialog();
      if (!d) return false;
      var close = d.querySelector('[data-close], .dialog-close, button[value="cancel"]');
      if (close) close.click(); else d.close();
      if (d.open) d.close();
      /* Joey TV WP-B4: a dialog that knows its opener (the Discover request panel: the poster) gives focus back to it */
      setFocus(d._opener && visible(d._opener) ? d._opener : first());
      return true;
    },
    focusFirst: function () { setFocus(first()); }
  };

  document.addEventListener('htmx:afterSettle', restore);
  document.addEventListener('htmx:historyRestore', restore);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restore);
  else restore();
})();
