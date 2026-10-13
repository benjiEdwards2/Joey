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
