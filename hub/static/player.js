/* Joey's own web and phone player (JY-054, 2026-10-27): look A "Classic overlay" (B., "JY-052: A").
   The page is hub/templates/media_watch.html; the API is docs/playback-contract.md (JY-053, B.: "JY-053: A A A A").

   - Browsers never direct-play and never use native HLS: hls.js (vendored, hub/static/hls.min.js) plays the HLS stream
     and sends the Authorization header on every request (xhrSetup), only to the stream's own origin. On an iPhone it runs
     over ManagedMediaSource (iOS 17.1+); below that, words instead of a broken player. No AirPlay (disableRemotePlayback).
   - The header carries the member's full Jellyfin token: it lives in one closure (attach), never in storage, a cookie, a
     URL, the DOM, a log or an error text.
   - Start -> stream -> hls.js; progress every heartbeat_s and at once on pause, play and seek; stop on Back (fetch
     keepalive) or navigator.sendBeacon on pagehide, once per session. A track change stops and starts a new session at
     the same point (the contract's way); a session the hub forgot (session_unknown) starts a new one at the position.
   - createPlayer() is the logic, with every browser object passed in (tests/hub/test_player_js.py runs it under node with
     a fake hls.js and a fake fetch); mount() wires it to the page. */
(function (root) {
  'use strict';
  var TICKS = 10000000;
  var API = '/api/play';
  var SEEK_S = 10;
  var WORDS = {
    unsupported: 'This browser can’t run Joey’s player. On an iPhone it needs iOS 17.1 or later.',
    offline: 'Can’t reach Joey. Check the connection and try again.',
    file: 'This file can’t play in the browser yet.',
    stopped: 'Playback stopped. Try again, or go back to Joey.',
    method: {direct: 'Direct play', remux: 'Remux', transcode: 'Transcode'}
  };

  function ticksOf(seconds) { return Math.max(0, Math.round((seconds || 0) * TICKS)); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(seconds) {
    var s = Math.max(0, Math.floor(seconds || 0)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
    return (h ? h + ':' + pad(m) : m) + ':' + pad(s % 60);
  }
  function originOf(url) {
    try { return new URL(url).origin; } catch (e) { return null; }
  }
  function noop() {}

  /* A Jellyfin DeviceProfile for this browser: HLS (fMP4) with the codecs `can` says Media Source plays; text subtitles
     inside the HLS stream, image subtitles burned in (JY-053 Q4 A). The phone is stereo. */
  function deviceProfile(kind, can) {
    can = can || function () { return false; };
    var video = ['h264'], audio = ['aac', 'mp3'];
    if (can('video/mp4; codecs="hvc1.1.6.L120.90"') || can('video/mp4; codecs="hev1.1.6.L120.90"')) video.push('hevc');
    if (can('video/mp4; codecs="av01.0.08M.08"')) video.push('av1');
    if (can('audio/mp4; codecs="ac-3"')) audio.push('ac3');
    if (can('audio/mp4; codecs="ec-3"')) audio.push('eac3');
    if (can('audio/mp4; codecs="flac"')) audio.push('flac');
    if (can('audio/mp4; codecs="opus"')) audio.push('opus');
    var v = video.join(','), a = audio.join(',');
    var subs = ['vtt', 'webvtt', 'srt', 'subrip', 'ass', 'ssa', 'mov_text', 'ttml', 'smi', 'sami'].map(function (f) {
      return {Format: f, Method: 'Hls'};
    }).concat(['pgssub', 'pgs', 'dvdsub', 'vobsub', 'dvbsub'].map(function (f) { return {Format: f, Method: 'Encode'}; }));
    return {
      Name: 'Joey player ' + kind, MaxStreamingBitrate: 120000000, MaxStaticBitrate: 120000000,
      DirectPlayProfiles: [{Container: 'mp4,m4v', Type: 'Video', VideoCodec: v, AudioCodec: a}],
      TranscodingProfiles: [{Container: 'mp4', Type: 'Video', Protocol: 'hls', Context: 'Streaming', VideoCodec: v,
                             AudioCodec: a, MaxAudioChannels: kind === 'phone' ? '2' : '6', BreakOnNonKeyFrames: true,
                             MinSegments: 1}],
      ContainerProfiles: [], CodecProfiles: [], SubtitleProfiles: subs
    };
  }

  /* Desktop keys -> an action name; null leaves the key alone (a focused button keeps Space / Enter, the seek slider
     keeps its arrows, a text box keeps everything). */
  function keyAction(key, tag, type) {
    tag = (tag || '').toUpperCase();
    if (tag === 'TEXTAREA' || (tag === 'INPUT' && type !== 'range')) return null;
    if ((key === ' ' || key === 'Enter') && (tag === 'BUTTON' || tag === 'A')) return null;
    if (tag === 'INPUT' && /^Arrow/.test(key)) return null;
    return {' ': 'toggle', k: 'toggle', K: 'toggle', ArrowLeft: 'back', ArrowRight: 'fwd', ArrowUp: 'volup',
            ArrowDown: 'voldown', f: 'full', F: 'full', m: 'mute', M: 'mute', Escape: 'close'}[key] || null;
  }

  /* Touch: one tap -> 'toggle' (after `wait` ms, so a second tap can still make it a double); two taps on the same
     half within `wait` -> 'back' (left) or 'fwd' (right), and no toggle. */
  function makeTapper(setT, clearT, act, wait) {
    var last = null, timer = null;
    wait = wait || 280;
    return function tap(x, width, now) {
      var side = x < width / 2 ? 'back' : 'fwd';
      if (last && now - last.at <= wait && last.side === side) {
        clearT(timer);
        timer = null;
        last = {at: now, side: side};   // a third quick tap on the same half seeks again
        act(side);
        return;
      }
      last = {at: now, side: side};
      clearT(timer);
      timer = setT(function () { timer = null; act('toggle'); }, wait);
    };
  }

  function createPlayer(o) {
    var on = o.on || noop;
    var st = {sid: null, hls: null, timer: null, stopped: true, audio: null, sub: null, tracks: null, chapters: [],
              runtime: 0, method: null, starting: false, retried: false, recovered: false, framed: false};
    var video = o.video;
    var now = o.now || function () { return Date.now(); };

    function post(path, body, keepalive) {
      var init = {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: {}};
      if (body !== undefined) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(body);
      }
      if (keepalive) init.keepalive = true;
      return o.fetch(path, init);
    }
    function json(resp) {
      return resp.json().then(function (body) {
        if (resp.ok) return body;
        var e = (body && body.error) || {};
        throw {status: resp.status, code: e.code || 'http_' + resp.status, message: e.message};
      }, function () { throw {status: resp.status, code: 'http_' + resp.status}; });
    }
    function position() { return ticksOf(video.currentTime); }
    function clearBeat() {
      if (st.timer !== null) o.clearInterval(st.timer);
      st.timer = null;
    }
    function teardown() {
      clearBeat();
      if (st.hls) st.hls.destroy();
      st.hls = null;
      st.sid = null;
    }
    function fail(err) {
      // only the API's own words (its error shape) or ours reach the screen; a browser exception's text never does
      var words = err && err.code && err.message ? err.message : (err && err.status ? WORDS.stopped : WORDS.offline);
      var p = st.sid && !st.stopped ? stop() : Promise.resolve();
      teardown();
      st.starting = false;
      on('error', words);
      return p;
    }

    function attach(hand, startTicks) {
      if (hand.protocol !== 'hls') return fail({code: 'not_hls', message: WORDS.file});
      var auth = hand.headers && hand.headers.Authorization;   // the token: this closure only
      var origin = originOf(hand.url);
      var Hls = o.Hls;
      var hls = new Hls({
        startPosition: startTicks / TICKS, preferManagedMediaSource: true, enableWorker: true,
        xhrSetup: function (xhr, url) { if (auth && originOf(url) === origin) xhr.setRequestHeader('Authorization', auth); }
      });
      st.hls = hls;
      st.retried = st.recovered = false;
      hls.on(Hls.Events.MANIFEST_PARSED, function () {
        if (st.sub !== null && st.sub !== -1 && hls.subtitleTracks && hls.subtitleTracks.length) {
          hls.subtitleTrack = 0;
          hls.subtitleDisplay = true;
        } else {
          hls.subtitleDisplay = false;
        }
        var p = video.play();
        if (p && p.catch) p.catch(function () { on('paused'); });
      });
      hls.on(Hls.Events.ERROR, function (ev, data) {
        if (!data || !data.fatal || hls !== st.hls) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR && !st.retried) { st.retried = true; hls.startLoad(); return; }
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR && !st.recovered) { st.recovered = true; hls.recoverMediaError(); return; }
        fail({code: 'hls_fatal', message: WORDS.stopped});
      });
      hls.loadSource(hand.url);
      hls.attachMedia(video);
      st.timer = o.setInterval(function () { beat(video.paused); }, st.heartbeat);
      st.starting = false;
      on('playing-soon');
    }

    function start(atTicks, audio, sub) {
      if (!o.Hls || !o.Hls.isSupported || !o.Hls.isSupported()) { on('error', WORDS.unsupported); return Promise.resolve(); }
      if (st.starting) return Promise.resolve();
      st.starting = true;
      var body = {item_id: o.itemId, device: {kind: o.kind, profile: o.profile}};
      if (atTicks === undefined || atTicks === null) body.resume = true; else body.start_ticks = atTicks;
      if (audio !== undefined && audio !== null) body.audio_index = audio;
      if (sub !== undefined && sub !== null) body.subtitle_index = sub;
      on('starting');
      return post(API + '/sessions', body).then(json).then(function (s) {
        st.sid = s.session_id;
        st.stopped = false;
        st.heartbeat = Math.max(2, s.heartbeat_s || 10) * 1000;
        st.audio = s.audio_index === undefined ? null : s.audio_index;
        st.sub = s.subtitle_index === undefined ? null : s.subtitle_index;
        st.tracks = s.tracks || {audio: [], subtitles: []};
        if (s.chapters && s.chapters.length) st.chapters = s.chapters;
        st.runtime = s.runtime_ticks || st.runtime;
        st.method = s.play_method;
        on('session', {method: s.play_method, words: WORDS.method[s.play_method] || '', tracks: st.tracks,
                       audio: st.audio, sub: st.sub, chapters: st.chapters, runtime: st.runtime});
        if (s.resumed) on('resumed', s.start_ticks);
        return post(s.stream).then(json).then(function (hand) { return attach(hand, s.start_ticks || 0); });
      }).catch(fail);
    }

    function beat(paused) {
      if (!st.sid || st.stopped) return Promise.resolve();
      var sid = st.sid;
      return post(API + '/sessions/' + sid + '/progress', {position_ticks: position(), paused: !!paused}).then(function (r) {
        if (r.status !== 404) return;
        return r.json().then(function (b) {
          if (b && b.error && b.error.code === 'session_unknown' && sid === st.sid) return restart();
        }, noop);
      }, noop);   // a failed heartbeat is not fatal: the next one carries on
    }

    function restart() {   // the hub forgot the session (restart, 30 min idle): a new one at the same point
      var at = position(), a = st.audio, s = st.sub;
      st.stopped = true;
      teardown();
      return start(at, a, s);
    }

    function stop() {
      if (!st.sid || st.stopped) return Promise.resolve();
      st.stopped = true;
      clearBeat();
      return post(API + '/sessions/' + st.sid + '/stop', {position_ticks: position()}, true).then(noop, noop);
    }

    function beacon() {   // pagehide: the page is going away, a fetch may not finish
      if (!st.sid || st.stopped) return false;
      st.stopped = true;
      clearBeat();
      var url = API + '/sessions/' + st.sid + '/stop', body = JSON.stringify({position_ticks: position()});
      var sent = o.sendBeacon ? o.sendBeacon(url, body) : false;
      if (!sent) post(url, {position_ticks: position()}, true).then(noop, noop);
      return true;
    }

    function switchTracks(audio, sub) {
      if (audio === st.audio && sub === st.sub) return Promise.resolve();
      var at = position();
      var p = stop();
      teardown();
      return p.then(function () { return start(at, audio, sub); });
    }

    video.addEventListener('pause', function () { if (!video.ended) beat(true); });
    video.addEventListener('play', function () { beat(false); });
    video.addEventListener('seeked', function () { beat(video.paused); });
    video.addEventListener('ended', function () { stop(); on('ended'); });
    video.addEventListener('playing', function () {
      st.retried = st.recovered = false;   // playing again: a later fatal error gets its one retry / recovery again
      if (!st.framed && st.sid) {          // press to first frame (JY-050 Q8 A): `now` is ms since the page's navigation
        st.framed = true;
        on('firstframe', Math.round(now()));
      }
    });

    /* bfcache (JY-054 review): a page restored from the back-forward cache after pagehide / Back has a stopped or no
       session; it never stays a session-less player: hls.js is destroyed and a fresh session starts at the position. */
    function revive() {
      if (st.sid && !st.stopped) return Promise.resolve();
      var at = position(), a = st.audio, s = st.sub;
      st.stopped = true;
      teardown();
      st.starting = false;
      return start(at, a, s);
    }

    return {
      start: function () { return start(); }, stop: stop, beacon: beacon, beat: beat, switchTracks: switchTracks,
      revive: revive,
      position: position,
      state: function () {
        return {sid: st.sid, stopped: st.stopped, audio: st.audio, sub: st.sub, tracks: st.tracks,
                chapters: st.chapters, runtime: st.runtime, method: st.method};
      }
    };
  }

  /* ---- the page (look A) ---- */

  function mount(rootEl, win) {
    var doc = win.document;
    var q = function (name) { return rootEl.querySelector('[data-pl="' + name + '"]'); };
    var video = rootEl.querySelector('video');
    var phone = /iPhone|iPod|Android.+Mobile/.test(win.navigator.userAgent || '');
    var touch = (win.matchMedia && win.matchMedia('(pointer: coarse)').matches) || phone;
    var MS = win.ManagedMediaSource || win.MediaSource;
    var can = function (t) { try { return !!(MS && MS.isTypeSupported(t)); } catch (e) { return false; } };
    var kind = phone ? 'phone' : 'web';
    var info = {runtime: 0, chapters: []};
    var hideTimer = null, toastTimer = null, countdown = null, dragging = false, dismissed = false;
    var upnext = q('upnext'), nextHref = upnext ? upnext.getAttribute('data-next') : null;

    video.disableRemotePlayback = true;
    rootEl.classList.toggle('pl-touch', touch);

    function text(name, value) { var el = q(name); if (el) el.textContent = value; }
    function show(name, yes) { var el = q(name); if (el) el.hidden = !yes; }
    function message(words, retry) {
      text('msg-text', words || '');
      show('msg', !!words);
      show('retry', !!retry);
    }

    var ctl = createPlayer({
      itemId: rootEl.getAttribute('data-item'), kind: kind, profile: deviceProfile(kind, can),
      fetch: win.fetch.bind(win), Hls: win.Hls, video: video,
      sendBeacon: win.navigator.sendBeacon ? win.navigator.sendBeacon.bind(win.navigator) : null,
      setInterval: win.setInterval.bind(win), clearInterval: win.clearInterval.bind(win),
      now: win.performance && win.performance.now ? win.performance.now.bind(win.performance) : null,
      on: function (ev, data) {
        if (ev === 'starting') message('Starting…');
        else if (ev === 'playing-soon') message('');
        else if (ev === 'error') { message(data, true); rootEl.classList.add('pl-show'); }
        else if (ev === 'session') session(data);
        else if (ev === 'resumed') toast('Resumed at ' + clock(data / TICKS));
        else if (ev === 'ended') ended();
        else if (ev === 'paused') paint();
        else if (ev === 'firstframe') {   // B.'s device checks record this number (spec accept checklist)
          text('frame', 'First frame ' + (data / 1000).toFixed(1) + ' s after Play');
          show('frame', true);
        }
      }
    });

    function session(s) {
      info.runtime = s.runtime / TICKS || info.runtime;
      info.chapters = s.chapters || [];
      var m = q('method');
      if (m) { m.textContent = s.words; m.hidden = !s.words; }
      ticks();
      tracks(s);
    }

    function toast(words) {
      text('toast-text', words);
      show('toast', true);
      win.clearTimeout(toastTimer);
      toastTimer = win.setTimeout(function () { show('toast', false); }, 4000);
    }

    function duration() { return isFinite(video.duration) && video.duration > 0 ? video.duration : info.runtime; }

    function ticks() {
      var box = q('ticks'), d = duration();
      if (!box || !d) return;
      box.textContent = '';
      info.chapters.forEach(function (c) {
        var at = c.start_ticks / TICKS;
        if (at <= 0 || at >= d) return;
        var i = doc.createElement('i');
        i.className = 'pl-tick';
        i.style.left = (at / d * 100) + '%';
        box.appendChild(i);
      });
    }

    function chapterAt(t) {
      var n = -1;
      info.chapters.forEach(function (c, i) { if (c.start_ticks / TICKS <= t + 0.5) n = i; });
      return n;
    }

    function paint() {
      var d = duration(), t = video.currentTime || 0;
      rootEl.classList.toggle('pl-paused', video.paused);
      var pp = q('play');
      if (pp) pp.setAttribute('aria-label', video.paused ? 'Play' : 'Pause');
      var cp = q('cplay');
      if (cp) cp.setAttribute('aria-label', video.paused ? 'Play' : 'Pause');
      text('time', clock(t) + ' / ' + clock(d));
      text('left', d ? '−' + clock(d - t) : '');
      var n = chapterAt(t);
      text('chapter', n >= 0 && info.chapters.length > 1
        ? 'Ch ' + (n + 1) + ' of ' + info.chapters.length + ' · ' + (info.chapters[n].name || '') : '');
      var pct = d ? Math.min(100, t / d * 100) : 0;
      if (!dragging) {
        q('fill').style.width = pct + '%';
        q('thumb').style.left = pct + '%';
        q('seek').value = String(Math.round(pct * 10));
        q('seek').setAttribute('aria-valuetext', clock(t) + ' of ' + clock(d));
      }
      var b = video.buffered;
      if (b && b.length && d) q('buf').style.width = Math.min(100, b.end(b.length - 1) / d * 100) + '%';
      if (upnext && nextHref) {
        var near = !!d && d - t <= 60;
        if (!near && countdown !== null && !video.ended) {   // sought back during the countdown: call it off
          win.clearInterval(countdown);
          countdown = null;
          text('count', 'Up next');
        }
        if (near && !dismissed) upnext.hidden = false;
        else if (countdown === null) upnext.hidden = true;   // sought back out of the last minute
      }
      q('mute').setAttribute('aria-label', video.muted ? 'Unmute' : 'Mute');
      rootEl.classList.toggle('pl-muted', !!video.muted);
    }

    function ended() {
      paint();
      if (!upnext || !nextHref || dismissed) { rootEl.classList.add('pl-show'); return; }
      upnext.hidden = false;
      if (countdown !== null) win.clearInterval(countdown);   // never two countdowns
      var left = 8;
      text('count', 'Up next in ' + left);
      countdown = win.setInterval(function () {
        left -= 1;
        text('count', 'Up next in ' + left);
        if (left <= 0) { win.clearInterval(countdown); countdown = null; win.location.assign(nextHref); }
      }, 1000);
    }

    function trackRow(label, detail, on, pick) {
      var b = doc.createElement('button');
      b.type = 'button';
      b.className = 'pl-trow' + (on ? ' on' : '');
      b.setAttribute('role', 'menuitemradio');
      b.setAttribute('aria-checked', on ? 'true' : 'false');
      var mark = doc.createElement('span');
      mark.className = 'pl-check';
      mark.setAttribute('aria-hidden', 'true');
      mark.textContent = on ? '✓' : '';
      var name = doc.createElement('span');
      name.textContent = label;
      b.appendChild(mark);
      b.appendChild(name);
      if (detail) {
        var em = doc.createElement('em');
        em.textContent = detail;
        b.appendChild(em);
      }
      b.addEventListener('click', pick);
      return b;
    }

    function chans(n) { return {1: 'Mono', 2: 'Stereo', 6: '5.1', 8: '7.1'}[n] || (n ? n + ' ch' : ''); }

    function tracks(s) {
      var aBox = q('audio'), sBox = q('subs');
      aBox.textContent = '';
      sBox.textContent = '';
      (s.tracks.audio || []).forEach(function (t) {
        var detail = [chans(t.channels), (t.codec || '').toUpperCase()].filter(Boolean).join(' · ');
        aBox.appendChild(trackRow(t.title || t.language || 'Track ' + t.index, detail, t.index === s.audio, function () {
          choose(t.index, s.sub);
        }));
      });
      sBox.appendChild(trackRow('Off', '', s.sub === -1 || s.sub === null, function () { choose(s.audio, -1); }));
      (s.tracks.subtitles || []).forEach(function (t) {
        var bits = [(t.codec || '').toUpperCase()];
        if (t.forced) bits.push('forced');
        if (t.text === false) bits.push('burned in');
        sBox.appendChild(trackRow(t.title || t.language || 'Track ' + t.index, bits.filter(Boolean).join(' · '),
                                  t.index === s.sub, function () { choose(s.audio, t.index); }));
      });
      var btn = q('tracks-btn');
      if (btn) btn.hidden = !(s.tracks.audio || []).length && !(s.tracks.subtitles || []).length;
    }

    function choose(audio, sub) {
      pop(false);
      ctl.switchTracks(audio, sub);
    }

    function pop(open) {
      var el = q('tracks');
      if (open === undefined) open = el.hidden;
      el.hidden = !open;
      q('tracks-btn').setAttribute('aria-expanded', open ? 'true' : 'false');
      rootEl.classList.toggle('pl-popped', open);
      if (open) { reveal(); var first = el.querySelector('.pl-trow.on') || el.querySelector('.pl-trow'); if (first) first.focus(); }
    }

    function reveal() {
      rootEl.classList.add('pl-show');
      win.clearTimeout(hideTimer);
      hideTimer = win.setTimeout(function () {
        if (!video.paused && q('tracks').hidden && !dragging) rootEl.classList.remove('pl-show');
      }, 3000);
    }

    function toggle() { if (video.paused) { var p = video.play(); if (p && p.catch) p.catch(noop); } else video.pause(); }
    function seekBy(s) {
      var d = duration();
      video.currentTime = Math.max(0, Math.min(d ? d - 0.5 : Infinity, (video.currentTime || 0) + s));
      reveal();
    }
    function fullscreen() {
      if (doc.fullscreenElement || doc.webkitFullscreenElement) {
        (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc);
      } else if (rootEl.requestFullscreen) rootEl.requestFullscreen();
      else if (rootEl.webkitRequestFullscreen) rootEl.webkitRequestFullscreen();
      else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
    }
    function act(a) {
      if (a === 'toggle') toggle();
      else if (a === 'back') seekBy(-SEEK_S);
      else if (a === 'fwd') seekBy(SEEK_S);
      else if (a === 'volup') video.volume = Math.min(1, video.volume + 0.1);
      else if (a === 'voldown') video.volume = Math.max(0, video.volume - 0.1);
      else if (a === 'full') fullscreen();
      else if (a === 'mute') video.muted = !video.muted;
      else if (a === 'close') pop(false);
      reveal();
      paint();
    }

    q('play').addEventListener('click', toggle);
    var cplay = q('cplay');
    if (cplay) cplay.addEventListener('click', toggle);
    rootEl.querySelectorAll('[data-pl-seek]').forEach(function (b) {
      b.addEventListener('click', function () { seekBy(Number(b.getAttribute('data-pl-seek'))); });
    });
    q('mute').addEventListener('click', function () { act('mute'); });
    q('tracks-btn').addEventListener('click', function () { pop(); });
    q('tracks-close').addEventListener('click', function () { pop(false); });
    var full = q('full');
    if (!(rootEl.requestFullscreen || rootEl.webkitRequestFullscreen || video.webkitEnterFullscreen)) full.hidden = true;
    full.addEventListener('click', fullscreen);
    q('retry').addEventListener('click', function () { win.location.reload(); });

    var seek = q('seek');
    seek.addEventListener('input', function () {
      dragging = true;
      var pct = Number(seek.value) / 10;
      q('fill').style.width = pct + '%';
      q('thumb').style.left = pct + '%';
      text('time', clock(duration() * pct / 100) + ' / ' + clock(duration()));
    });
    seek.addEventListener('change', function () {
      dragging = false;
      video.currentTime = duration() * Number(seek.value) / 1000;
      reveal();
    });

    var back = q('back');
    back.addEventListener('click', function (e) {
      e.preventDefault();
      var href = back.getAttribute('href');
      ctl.stop();   // keepalive: survives the navigation; pagehide then has nothing left to send
      win.location.assign(href);
    });
    if (upnext) {
      q('credits').addEventListener('click', function () {
        dismissed = true;
        upnext.hidden = true;
        if (countdown !== null) win.clearInterval(countdown);
      });
    }

    var tapper = makeTapper(win.setTimeout.bind(win), win.clearTimeout.bind(win), function (a) {
      if (a === 'toggle') {
        if (rootEl.classList.contains('pl-show') && !video.paused) rootEl.classList.remove('pl-show'); else reveal();
      } else seekBy(a === 'back' ? -SEEK_S : SEEK_S);
    });
    var hit = q('hit');
    hit.addEventListener('pointerup', function (e) {
      if (e.button) return;   // right / middle click: the browser's own menu, never play / pause
      if (e.pointerType === 'mouse') { toggle(); reveal(); return; }
      var r = hit.getBoundingClientRect();
      tapper(e.clientX - r.left, r.width, Date.now());
    });
    hit.addEventListener('dblclick', function (e) { if (!touch) { e.preventDefault(); fullscreen(); } });
    rootEl.addEventListener('pointermove', function (e) { if (e.pointerType === 'mouse') reveal(); });

    doc.addEventListener('keydown', function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      var t = e.target || {};
      if (!q('tracks').hidden && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {   // walk the picker's rows
        var rows = Array.prototype.slice.call(q('tracks').querySelectorAll('.pl-trow'));
        var i = rows.indexOf(doc.activeElement) + (e.key === 'ArrowDown' ? 1 : -1);
        if (rows.length) rows[Math.max(0, Math.min(rows.length - 1, i))].focus();
        e.preventDefault();
        return;
      }
      var a = keyAction(e.key, t.tagName, t.type);
      if (!a) return;
      e.preventDefault();
      act(a);
    });

    ['timeupdate', 'progress', 'play', 'pause', 'durationchange', 'volumechange', 'seeked'].forEach(function (ev) {
      video.addEventListener(ev, paint);
    });
    video.addEventListener('durationchange', ticks);
    video.addEventListener('play', reveal);
    video.addEventListener('pause', function () { rootEl.classList.add('pl-show'); });

    win.addEventListener('pagehide', function () { ctl.beacon(); });
    win.addEventListener('pageshow', function (e) {   // restored from the back-forward cache: a fresh session
      if (!e.persisted) return;
      if (countdown !== null) { win.clearInterval(countdown); countdown = null; }
      ctl.revive();
    });

    rootEl.classList.add('pl-show');
    paint();
    ctl.start();
    return ctl;
  }

  var api = {createPlayer: createPlayer, deviceProfile: deviceProfile, keyAction: keyAction, makeTapper: makeTapper,
             clock: clock, mount: mount, WORDS: WORDS};
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.JoeyPlayer = api;
    var boot = function () {
      var el = root.document.getElementById('player');
      if (el) mount(el, root);
    };
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }
})(typeof window !== 'undefined' ? window : this);
