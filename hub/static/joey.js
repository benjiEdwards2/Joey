/* Joey's page shell script (H-57, 2026-10-09): moved out of base.html so it is cached like every versioned asset
   (/static/joey.js?v=, immutable) instead of re-sent inline with every no-store page. Loaded with defer right after
   htmx, so every listener below is in place before htmx processes the page; nothing here has to run before first
   paint. The flash keys come from base.html's joey-flash-params meta (FLASH_PARAMS, hub/main.py). */
/* A tab kept open across a deploy would boost into new markup with the OLD stylesheet
   (2026-10-06): when a boosted response carries a different asset version, load it fully. */
document.addEventListener('htmx:beforeSwap', function (e) {
  if (!e.detail.boosted) return;
  var m = /name="joey-asset-v" content="([0-9a-f]+)"/.exec(e.detail.xhr.responseText || '');
  var mine = document.querySelector('meta[name="joey-asset-v"]');
  if (m && mine && m[1] !== mine.content) {
    e.detail.shouldSwap = false;
    window.location.href = e.detail.pathInfo.finalRequestPath || e.detail.pathInfo.requestPath;
    return;
  }
  /* Boosts swap only <body> (and <title>): carry the page's manifest + iOS app title across, so "Add to Home
     Screen" from a Media page reached by a boosted link still installs "Joey Media" (2026-10-07). */
  var text = e.detail.xhr.responseText || '';
  var mf = /<link rel="manifest" href="([^"]+)">/.exec(text);
  var link = document.querySelector('link[rel="manifest"]');
  if (mf && link && link.getAttribute('href') !== mf[1]) link.setAttribute('href', mf[1]);
  var at = /<meta name="apple-mobile-web-app-title" content="([^"]+)">/.exec(text);
  var am = document.querySelector('meta[name="apple-mobile-web-app-title"]');
  if (at && !am) { am = document.createElement('meta'); am.name = 'apple-mobile-web-app-title'; document.head.appendChild(am); }
  if (at) am.content = at[1]; else if (am && mf) am.remove();
});
/* An action is not a place (media-ux2, 2026-10-08): a boosted POST form (Mark watched, Remove, Follow, a rating,
   watchlist ...) 303s back to a page, and htmx would PUSH that as a new history entry, so Back only dropped the flash
   word. Every non-GET boosted navigation REPLACES the current entry instead: one Back goes to the page before.
   htmx 2.0.4 fires htmx:beforeHistoryUpdate with detail.history = {type, path} (the object it then acts on) and
   detail.requestConfig.verb. */
document.addEventListener('htmx:beforeHistoryUpdate', function (e) {
  var h = e.detail && e.detail.history, rc = e.detail && e.detail.requestConfig;
  if (h && h.type === 'push' && rc && String(rc.verb || 'get').toLowerCase() !== 'get') h.type = 'replace';
});
/* A flash line ("Following", "Requested", "Removed") is shown once: after render, its query params leave the
   address bar (replaceState keeps htmx's history state), so Back / Forward / reload never re-show it (2026-10-08). */
(function () {
  var meta = document.querySelector('meta[name="joey-flash-params"]');
  var keys = meta ? JSON.parse(meta.content) : [];
  function strip() {
    try {
      var u = new URL(window.location.href), hit = false;
      keys.forEach(function (k) { if (u.searchParams.has(k)) { u.searchParams.delete(k); hit = true; } });
      if (hit) history.replaceState(history.state, '', u.pathname + (u.search ? u.search : '') + u.hash);
    } catch (err) { /* never break a page over the address bar */ }
  }
  strip();
  document.addEventListener('htmx:pushedIntoHistory', strip);
  document.addEventListener('htmx:replacedInHistory', strip);
})();
/* No pinch zoom on iOS Safari (media-ux5, 2026-10-09): Safari ignores user-scalable=no, so its proprietary pinch events
   are cancelled instead (they never fire elsewhere). Double-tap zoom is off via touch-action in the CSS. */
['gesturestart', 'gesturechange'].forEach(function (t) {
  document.addEventListener(t, function (e) { e.preventDefault(); }, {passive: false});
});
/* Server clean-up (WP-T3, 2026-10-19): a fold marked data-phone-closed (the Server page's Last 24 h) is rendered open
   for a desktop and starts closed on a phone (under 640 px), on load and after a boosted swap.
   Kept above the F2 block: test_polish_e2 runs that block alone under node. */
(function () {
  function closeOnPhone(root) {
    if (!window.matchMedia || !window.matchMedia('(max-width: 639px)').matches) return;
    (root || document).querySelectorAll('details[data-phone-closed]').forEach(function (d) { d.open = false; });
  }
  closeOnPhone();
  document.addEventListener('htmx:load', function (e) { closeOnPhone(e.target); });
})();
/* JY-276 / JY-277 option B: the Home carousel. The side buttons and the arrow keys on the focused track
   move one slide (smooth unless reduced motion); the slide nearest the centre is marked .is-on (full opacity, the focus
   ring). Delegated, so a pill swap (htmx outerHTML) needs no re-binding. */
(function () {
  var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function slides(t) { return Array.prototype.slice.call(t.querySelectorAll('.homecar-slide')); }
  function current(t) {
    var mid = t.scrollLeft + t.clientWidth / 2, best = 0, gap = Infinity;
    slides(t).forEach(function (s, i) {
      var d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid);
      if (d < gap) { gap = d; best = i; }
    });
    return best;
  }
  function mark(t) {
    var i = current(t);
    slides(t).forEach(function (s, j) { s.classList.toggle('is-on', j === i); });
  }
  function go(t, step) {
    var all = slides(t), i = Math.max(0, Math.min(all.length - 1, current(t) + step)), s = all[i];
    if (!s) return;
    t.scrollTo({left: s.offsetLeft + s.offsetWidth / 2 - t.clientWidth / 2, behavior: still ? 'auto' : 'smooth'});
  }
  function init(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('[data-homecar]').forEach(function (t) {
      if (t.dataset.on) return;
      t.dataset.on = '1';
      var raf = 0;
      t.addEventListener('scroll', function () {
        if (!raf) raf = requestAnimationFrame(function () { raf = 0; mark(t); });
      }, {passive: true});
      mark(t);
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-homecar-step]');
    if (!b) return;
    var t = b.closest('.homecar').querySelector('[data-homecar]');
    if (t) go(t, parseInt(b.getAttribute('data-homecar-step'), 10));
  });
  document.addEventListener('keydown', function (e) {
    var t = e.target.closest && e.target.closest('[data-homecar]');
    if (!t || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    e.preventDefault();
    go(t, e.key === 'ArrowLeft' ? -1 : 1);
    if (e.target !== t) t.focus();
  });
  document.addEventListener('htmx:load', function (e) { init(e.target); });
  if (document.readyState !== 'loading') init(document);
  else document.addEventListener('DOMContentLoaded', function () { init(document); });
})();
/* JY-304 option C (B. 2026-11-04): every .carousel shelf off the TV gets a scroll cue - .cue-more / .cue-back (the
   CSS edge fades) follow the scroll position, and round prev / next buttons (shown from 768 px, hidden at the ends)
   scroll 80 % of a view. Wrapped once per shelf; htmx-loaded shelves are picked up too. Never on the TV (html.tv). */
(function () {
  var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var ARROWS = [['prev', 'Scroll left', 'M15 5l-7 7 7 7', -1], ['next', 'Scroll right', 'M9 5l7 7-7 7', 1]];
  function cue(c) {
    if (c.dataset.cue) return;
    c.dataset.cue = '1';
    var w = document.createElement('div'), btn = {};
    w.className = 'cue-wrap';
    c.parentNode.insertBefore(w, c);
    w.appendChild(c);
    ARROWS.forEach(function (a) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'cue-arrow ' + a[0];
      b.setAttribute('aria-label', a[1]);
      b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + a[2] + '"/></svg>';
      b.addEventListener('click', function () {
        c.scrollBy({left: a[3] * c.clientWidth * 0.8, behavior: still ? 'auto' : 'smooth'});
      });
      w.appendChild(b);
      btn[a[0]] = b;
    });
    function update() {
      var more = c.scrollLeft + c.clientWidth < c.scrollWidth - 2, back = c.scrollLeft > 2;
      c.classList.toggle('cue-more', more);
      c.classList.toggle('cue-back', back);
      btn.prev.hidden = !back;
      btn.next.hidden = !more;
    }
    c.addEventListener('scroll', update, {passive: true});
    window.addEventListener('resize', update);
    update();
  }
  function init(root) {
    if (document.documentElement.classList.contains('tv')) return;
    if (root.classList && root.classList.contains('carousel')) cue(root);
    (root.querySelectorAll ? root : document).querySelectorAll('.carousel').forEach(cue);
  }
  document.addEventListener('htmx:load', function (e) { init(e.target); });
  if (document.readyState !== 'loading') init(document);
  else document.addEventListener('DOMContentLoaded', function () { init(document); });
})();
/* ---- F2 fast item pages (2026-10-12): warm a film / show page on touch or hover ----
   A finger landing on (or a pointer resting 60 ms over) a link to a film / show page sends that page a GET with
   X-Joey-Prefetch: 1 and throws the answer away (an empty 204): the server reads Jellyfin and starts the Jellyseerr /
   OMDb read, so the real tap finds its caches warm. Once per href, one prefetch in flight at a time.
   P3c (2026-10-13): a finger that starts scrolling (touchmove) cancels the pending prefetch, so flicking through a
   shelf of posters warms nothing; a touch that ends without moving fires it at once (a quick tap), and a touch held
   60 ms without moving fires it then. The 60 ms hover path is unchanged. */
(function () {
  var SEL = 'a[href^="/media/item/"], a[href^="/media/title/"]';
  var done = {}, busy = false, timer = null, pending = null;
  function go(href) {
    if (busy || done[href]) return;
    done[href] = true;
    busy = true;
    var end = function () { busy = false; };
    fetch(href, {headers: {'X-Joey-Prefetch': '1'}, credentials: 'same-origin'}).then(end, end);
  }
  function near(e) {
    var a = e.target && e.target.closest ? e.target.closest(SEL) : null;
    var href = a ? a.getAttribute('href') : null;
    if (!href || done[href] || href.indexOf('/part/') !== -1) return;
    clearTimeout(timer);
    pending = href;
    timer = setTimeout(function () { pending = null; go(href); }, 60);
  }
  function cancel() { clearTimeout(timer); pending = null; }
  function lift() {
    clearTimeout(timer);
    var href = pending;
    pending = null;
    if (href) go(href);
  }
  document.addEventListener('touchstart', near, {passive: true});
  document.addEventListener('touchmove', cancel, {passive: true});
  document.addEventListener('touchcancel', cancel, {passive: true});
  document.addEventListener('touchend', lift, {passive: true});
  document.addEventListener('mouseover', near);
})();

/* JY-270 years (B. 2026-10-30): a <select data-nav> (the Awards year dropdown) goes to the picked option's URL */
document.addEventListener('change', function (e) {
  var s = e.target;
  if (s && s.tagName === 'SELECT' && s.hasAttribute('data-nav') && s.value) window.location.assign(s.value);
});
