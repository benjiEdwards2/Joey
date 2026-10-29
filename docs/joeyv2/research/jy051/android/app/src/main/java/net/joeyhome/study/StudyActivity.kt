package net.joeyhome.study

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.media.MediaCodecList
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DecoderReuseEvaluation
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.DefaultTimeBar
import androidx.media3.ui.PlayerView
import androidx.webkit.WebViewAssetLoader
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * JY-051 "Joey Study". Started by scripts/jy051_sitting.py with `adb shell am start` extras:
 *   jf, engines (T1,T2,T2F,T2H), runs, runs_t1, rows, look, hold_ms, look_ms, network, mode (matrix | resume).
 * B. signs in as joeytest on the app's first screen (Jellyfin AuthenticateByName with what he types). The session
 * token lives in memory only (never stored, logged or passed in); the app signs out at the end to free the session
 * slot. The admin key never reaches the TV. After the matrix the app offers the resume test (OK) or finishes (Back).
 * Every result is one logcat line, tag JY051, JSON (kind session | run | resume_stop | done). No URL or token is logged.
 */
@OptIn(UnstableApi::class)
class StudyActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var root: FrameLayout
    private lateinit var playerView: PlayerView
    private lateinit var overlay: TextView
    private var token = ""
    private var base = DEFAULT_JF
    private var network = "LAN"
    private var deviceId = ""
    private var userId = ""
    private var verdict: CompletableDeferred<String>? = null
    private var stopResume: CompletableDeferred<Unit>? = null
    private var choice: CompletableDeferred<Boolean>? = null
    @Volatile private var aborted = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        playerView = PlayerView(this).apply { useController = false }
        root.addView(playerView, FrameLayout.LayoutParams(MATCH, MATCH))
        overlay = TextView(this).apply {
            setTextColor(Color.WHITE)
            setBackgroundColor(0xB0000000.toInt())
            textSize = 20f
            setPadding(32, 16, 32, 16)
        }
        root.addView(overlay, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.START).apply { setMargins(48, 27, 48, 27) })
        setContentView(root)
        start()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun start() {
        val prefs = getSharedPreferences("jy051", MODE_PRIVATE)
        val x = intent
        prefs.edit().remove("token").apply()   // an earlier draft kept a token here: make sure none is left
        // a device id is not a credential: kept so repeated sign-ins reuse one Jellyfin device entry
        deviceId = prefs.getString("device", null) ?: ("jy051-tv-" + UUID.randomUUID().toString().take(8)).also {
            prefs.edit().putString("device", it).apply()
        }
        base = (x.getStringExtra("jf") ?: DEFAULT_JF).trimEnd('/')
        network = x.getStringExtra("network") ?: "LAN"
        showSignIn { jf ->
            scope.launch {
                if (x.getStringExtra("mode") == "resume") {
                    runResume(jf)
                } else {
                    runMatrix(jf, x)
                    if (!aborted) {
                        say("Matrix done. OK = start the resume test (row 1), Back = finish.")
                        val c = CompletableDeferred<Boolean>()
                        choice = c
                        val go = c.await()
                        choice = null
                        if (go) runResume(jf)
                    }
                }
                signOut(jf)
                emit(JSONObject().put("kind", "done").put("aborted", aborted))
            }
        }
    }

    /** First screen: user name + password, then AuthenticateByName. Nothing typed is stored or logged. */
    private fun showSignIn(onReady: (Jellyfin) -> Unit) {
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.BLACK)
            setPadding(96, 54, 96, 54)
            gravity = Gravity.CENTER
        }
        val title = TextView(this).apply { text = "Joey Study: sign in as joeytest"; textSize = 26f; setTextColor(Color.WHITE) }
        val user = EditText(this).apply {
            hint = "User name"; setSingleLine(); textSize = 22f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        }
        val pass = EditText(this).apply {
            hint = "Password"; setSingleLine(); textSize = 22f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val status = TextView(this).apply { textSize = 18f; setTextColor(Color.LTGRAY) }
        val button = Button(this).apply { text = "Sign in"; textSize = 22f }
        for (v in listOf(title, user, pass, button, status)) {
            form.addView(v, LinearLayout.LayoutParams(900, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        root.addView(form, FrameLayout.LayoutParams(MATCH, MATCH))
        user.requestFocus()
        button.setOnClickListener {
            val name = user.text.toString().trim()
            val pw = pass.text.toString()
            if (name.isEmpty()) {
                status.text = "Type the user name"
                return@setOnClickListener
            }
            button.isEnabled = false
            status.text = "Signing in..."
            scope.launch {
                try {
                    val (tok, uid) = withContext(Dispatchers.IO) { Jellyfin.authenticate(base, deviceId, name, pw) }
                    token = tok
                    userId = uid
                    pass.setText("")
                    root.removeView(form)
                    onReady(Jellyfin(base, token, deviceId))
                } catch (e: Exception) {
                    // a wrong password, or joeytest's session limit is full (sign out elsewhere first)
                    status.text = "Sign-in refused (${e.message}). Check the password; a full session limit also refuses."
                    button.isEnabled = true
                }
            }
        }
    }

    /** Ends this app's Jellyfin session (frees joeytest's session slot) and forgets the token; joeytest is unchanged. */
    private suspend fun signOut(jf: Jellyfin) {
        try {
            withContext(Dispatchers.IO) { jf.post("/Sessions/Logout", JSONObject()) }
        } catch (_: Exception) {
        }
        token = ""
        say(if (aborted) "Stopped and signed out." else "Done and signed out. You can put the remote down.")
    }

    // ------------------------------------------------------------------ matrix
    private suspend fun runMatrix(jf: Jellyfin, x: android.content.Intent) {
        val engines = (x.getStringExtra("engines") ?: "T1,T2,T2F,T2H").split(',').map { it.trim() }.filter { it.isNotEmpty() }
        val runs = x.getIntExtra("runs", 3).coerceIn(1, 5)
        val runsT1 = x.getIntExtra("runs_t1", 1).coerceIn(1, 5)
        val rowsArg = x.getStringExtra("rows") ?: ""
        val rows = rowsArg.split(',').mapNotNull { it.trim().toIntOrNull() }.toSet()
        val items = Study.ITEMS.filter { rows.isEmpty() || it.n in rows }
        val look = (x.getStringExtra("look") ?: "6,7,8,11,12").split(',').mapNotNull { it.trim().toIntOrNull() }.toSet()
        val holdMs = x.getIntExtra("hold_ms", 1000).toLong()
        val lookMs = x.getIntExtra("look_ms", 8000).toLong()
        val mimes = decoderMimes()
        emitSession(mimes)

        if ("T1" in engines) runT1(items, runsT1, holdMs, look)
        val failed = mutableMapOf<String, MutableSet<Int>>()
        val facts = mutableMapOf<String, Pair<String, List<StreamFact>>>()
        for (engine in listOf("T2", "T2F", "T2H")) {
            if (engine !in engines || aborted) continue
            val todo = if (engine != "T2H") items else {
                val last = failed["T2F"] ?: failed["T2"] ?: emptySet()
                items.filter { it.n in last || x.getBooleanExtra("h_all", false) }
            }
            for (item in todo) {
                if (aborted) break
                val f = try {
                    facts.getOrPut(item.id) { withContext(Dispatchers.IO) { jf.facts(item.id) } }
                } catch (e: Exception) {
                    emit(record(engine, item, 1).put("ok", false).put("err", e.message ?: "facts"))
                    failed.getOrPut(engine) { mutableSetOf() }.add(item.n)
                    continue
                }
                var anyBad = false
                for (k in 1..runs) {
                    if (aborted) break
                    val rec = playOnce(jf, engine, item, f, k, if (k == runs && item.n in look) lookMs else holdMs,
                        askVerdict = k == runs && item.n in look, mimes = mimes)
                    emit(rec)
                    if (!rec.optBoolean("ok") || rec.optString("audio").startsWith("unsupported") ||
                        rec.optString("audio") == "none selected") anyBad = true
                    delay(500)
                }
                if (anyBad) failed.getOrPut(engine) { mutableSetOf() }.add(item.n)
            }
        }
        emit(JSONObject().put("kind", "done").put("phase", "matrix").put("aborted", aborted))
    }

    private fun record(engine: String, item: TestItem, k: Int): JSONObject =
        JSONObject().put("kind", "run").put("device", "TV").put("network", network).put("engine", engine)
            .put("n", item.n).put("id", item.id).put("run", k)

    @SuppressLint("SetJavaScriptEnabled")
    private suspend fun runT1(items: List<TestItem>, runs: Int, holdMs: Long, look: Set<Int>) {
        say("T1: the study page in the WebView")
        val done = CompletableDeferred<Unit>()
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this)).build()
        val web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)
        }
        web.addJavascriptInterface(object {
            @JavascriptInterface fun token(): String = token
            @JavascriptInterface fun emit(json: String) {
                // the page's own records (engine W1 / W2, device TV) = T1-W1 / T1-W2 in the matrix
                logLine(json)
            }
            @JavascriptInterface fun done() {
                done.complete(Unit)
            }
        }, "JY051Bridge")
        root.addView(web, 0, FrameLayout.LayoutParams(MATCH, MATCH))
        val q = Uri.Builder().scheme("https").authority("appassets.androidplatform.net").path("/assets/study.html")
            .appendQueryParameter("auto", "1").appendQueryParameter("device", "TV")
            .appendQueryParameter("network", network).appendQueryParameter("engines", "W1,W2")
            .appendQueryParameter("runs", runs.toString()).appendQueryParameter("hold", (holdMs / 1000.0).toString())
            .appendQueryParameter("rows", items.joinToString(",") { it.n.toString() })
            .appendQueryParameter("look", look.joinToString(",")).appendQueryParameter("jf", base).build()
        web.loadUrl(q.toString())
        val ok = withTimeoutOrNull(25 * 60_000L) { done.await() }
        if (ok == null) emit(JSONObject().put("kind", "done").put("engine", "T1").put("aborted", "T1 timed out"))
        root.removeView(web)
        web.destroy()
    }

    /** One ExoPlayer run: start to first rendered frame, then hold; the record never carries a URL. */
    private suspend fun playOnce(
        jf: Jellyfin, engine: String, item: TestItem, facts: Pair<String, List<StreamFact>>, k: Int, holdMs: Long,
        askVerdict: Boolean, mimes: Set<String>,
    ): JSONObject {
        val (msid, streams) = facts
        val rec = record(engine, item, k)
        say("Row ${item.n} - $engine - run $k")
        val t0 = SystemClock.elapsedRealtime()
        var playSession: String? = null
        val mi = MediaItem.Builder()
        try {
            if (engine == "T2H") {
                val t1 = SystemClock.elapsedRealtime()
                val profile = Jellyfin.hlsProfile(Study.videoCodecs(mimes), Study.audioCodecs(mimes, ffmpeg = true))
                val pi = withContext(Dispatchers.IO) {
                    jf.post("/Items/${item.id}/PlaybackInfo?UserId=$userId", Jellyfin.hlsBody(userId, profile, item, msid))
                }
                rec.put("ms_pi", SystemClock.elapsedRealtime() - t1)
                val ms = pi.optJSONArray("MediaSources")?.optJSONObject(0)
                val turl = ms?.optString("TranscodingUrl", "") ?: ""
                playSession = pi.optString("PlaySessionId", "").ifEmpty { null }
                val (method, reasons) = Study.method(ms?.optBoolean("SupportsDirectPlay") == true,
                    ms?.optBoolean("SupportsDirectStream") == true, turl.ifEmpty { null })
                rec.put("method", method).put("reasons", JSONArray(reasons))
                rec.put("sub", Study.query(turl)["subtitlemethod"]?.let { "method $it" } ?: "")
                if (turl.isEmpty()) throw IllegalStateException("no HLS offered ($method)")
                mi.setUri(jf.url(turl)).setMimeType(MimeTypes.APPLICATION_M3U8)
                if (item.sub != null && Study.query(turl)["subtitlemethod"] == "External") {
                    val sub = (0 until (ms?.optJSONArray("MediaStreams")?.length() ?: 0))
                        .map { ms!!.getJSONArray("MediaStreams").getJSONObject(it) }
                        .firstOrNull { it.optInt("Index", -1) == item.sub }
                    val du = sub?.optString("DeliveryUrl", "") ?: ""
                    if (du.isNotEmpty()) mi.setSubtitleConfigurations(listOf(subtitle(if (du.startsWith("http")) du else jf.url(du))))
                }
            } else {
                rec.put("method", "Direct (as is)")
                mi.setUri(jf.url("/Videos/${item.id}/stream?static=true&MediaSourceId=$msid&DeviceId=$deviceId"))
                if (item.sub != null && Study.isExternal(streams, item.sub)) {
                    mi.setSubtitleConfigurations(listOf(subtitle(jf.url("/Videos/${item.id}/$msid/Subtitles/${item.sub}/0/Stream.srt"))))
                    rec.put("sub", "external srt sideloaded")
                }
            }
        } catch (e: Exception) {
            return rec.put("ok", false).put("err", Study.scrub(e.message ?: e.javaClass.simpleName, token))
        }

        val http = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(mapOf("Authorization" to jf.auth))
            .setConnectTimeoutMs(15_000).setReadTimeoutMs(30_000)
        val rf = DefaultRenderersFactory(this).setExtensionRendererMode(
            if (engine == "T2") DefaultRenderersFactory.EXTENSION_RENDERER_MODE_OFF
            else DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON,
        )
        val player = ExoPlayer.Builder(this, rf).setMediaSourceFactory(DefaultMediaSourceFactory(http)).build()
        playerView.player = player
        val first = CompletableDeferred<Unit>()
        var err: String? = null
        var tFrame = -1L
        var tPlaying = -1L
        var vdec = ""
        var adec = ""
        var amime = ""
        var dropped = 0
        var overridden = false
        player.addListener(object : Player.Listener {
            override fun onRenderedFirstFrame() {
                if (tFrame < 0) tFrame = SystemClock.elapsedRealtime() - t0
                first.complete(Unit)
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying && tPlaying < 0) tPlaying = SystemClock.elapsedRealtime() - t0
            }
            override fun onPlayerError(error: PlaybackException) {
                if (err == null) err = error.errorCodeName
                first.complete(Unit)
            }
            override fun onTracksChanged(tracks: Tracks) {
                if (overridden || tracks.groups.isEmpty()) return
                overridden = true
                select(player, tracks, streams, item)
            }
        })
        player.addAnalyticsListener(object : AnalyticsListener {
            override fun onVideoDecoderInitialized(eventTime: AnalyticsListener.EventTime, decoderName: String,
                initializedTimestampMs: Long, initializationDurationMs: Long) { vdec = decoderName }
            override fun onAudioDecoderInitialized(eventTime: AnalyticsListener.EventTime, decoderName: String,
                initializedTimestampMs: Long, initializationDurationMs: Long) { adec = decoderName }
            override fun onAudioInputFormatChanged(eventTime: AnalyticsListener.EventTime, format: Format,
                decoderReuseEvaluation: DecoderReuseEvaluation?) { amime = format.sampleMimeType ?: "" }
            override fun onDroppedVideoFrames(eventTime: AnalyticsListener.EventTime, droppedFrames: Int, elapsedMs: Long) {
                dropped += droppedFrames
            }
        })
        player.setMediaItem(mi.build())
        player.playWhenReady = true
        player.prepare()
        if (withTimeoutOrNull(30_000) { first.await() } == null && err == null) err = "no first frame in 30 s"
        if (err == null) {
            if (askVerdict) {
                say("Row ${item.n} - $engine: picture, sound and subtitles right? OK = yes, Back = no")
                val d = CompletableDeferred<String>()
                verdict = d
                rec.put("verdict", withTimeoutOrNull(maxOf(holdMs, 12_000)) { d.await() } ?: "none")
                verdict = null
            } else {
                delay(holdMs)
            }
        }
        // what played: the selected audio / text track and whether the renderer supports it
        val tr = player.currentTracks
        rec.put("audio", describe(tr, C.TRACK_TYPE_AUDIO, wantAny = true))
        rec.put("text", describe(tr, C.TRACK_TYPE_TEXT, wantAny = item.sub != null))
        val vs = player.videoSize
        rec.put("w", vs.width).put("h", vs.height)
        rec.put("ok", err == null && tFrame >= 0).put("err", err ?: "")
        rec.put("ms_frame", if (tFrame >= 0) tFrame else JSONObject.NULL)
        rec.put("ms_playing", if (tPlaying >= 0) tPlaying else JSONObject.NULL)
        rec.put("vdec", vdec).put("adec", adec).put("amime", amime).put("dropped", dropped)
        player.release()
        playerView.player = null
        playSession?.let { ps ->
            // stop this run's transcode now (the J4125 must never hold two): a runtime job, not library data
            try { withContext(Dispatchers.IO) { jf.delete("/Videos/ActiveEncodings?DeviceId=$deviceId&PlaySessionId=$ps") } } catch (_: Exception) { }
        }
        return rec
    }

    private fun subtitle(url: String): MediaItem.SubtitleConfiguration {
        val mime = if (url.substringBefore('?').endsWith(".vtt")) MimeTypes.TEXT_VTT else MimeTypes.APPLICATION_SUBRIP
        return MediaItem.SubtitleConfiguration.Builder(Uri.parse(url)).setMimeType(mime).setId("jy051-ext")
            .setSelectionFlags(C.SELECTION_FLAG_DEFAULT).setLanguage("und").build()
    }

    /** Select the study's audio / subtitle track: the n-th own track of that type, or the sideloaded subtitle. */
    private fun select(player: ExoPlayer, tracks: Tracks, streams: List<StreamFact>, item: TestItem) {
        val p = player.trackSelectionParameters.buildUpon()
        item.audio?.let { a ->
            val pos = Study.internalPosition(streams, "Audio", a)
            tracks.groups.filter { it.type == C.TRACK_TYPE_AUDIO }.getOrNull(pos)?.let { p.setOverrideForType(TrackSelectionOverride(it.mediaTrackGroup, 0)) }
        }
        item.sub?.let { s ->
            val texts = tracks.groups.filter { it.type == C.TRACK_TYPE_TEXT }
            val g = if (Study.isExternal(streams, s)) {
                texts.firstOrNull { (it.getTrackFormat(0).id ?: "").contains("jy051-ext") } ?: texts.lastOrNull()
            } else {
                texts.getOrNull(Study.internalPosition(streams, "Subtitle", s))
            }
            if (g != null) {
                p.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                p.setOverrideForType(TrackSelectionOverride(g.mediaTrackGroup, 0))
            }
        }
        player.trackSelectionParameters = p.build()
    }

    private fun describe(tracks: Tracks, type: Int, wantAny: Boolean): String {
        val groups = tracks.groups.filter { it.type == type }
        if (groups.isEmpty()) return if (wantAny) "no track" else ""
        for (g in groups) for (i in 0 until g.length) {
            if (g.isTrackSelected(i)) {
                val mime = g.getTrackFormat(i).sampleMimeType ?: "?"
                return if (g.isTrackSupported(i)) "ok $mime" else "unsupported $mime"
            }
        }
        if (!wantAny) return ""
        val unsupported = groups.flatMap { g -> (0 until g.length).filter { !g.isTrackSupported(it) }
            .map { g.getTrackFormat(it).sampleMimeType ?: "?" } }.distinct()
        return if (unsupported.isEmpty()) "none selected" else "unsupported ${unsupported.joinToString("/")}"
    }

    // ------------------------------------------------------------------ resume (row 1, reports progress)
    private suspend fun runResume(jf: Jellyfin) {
        val item = Study.ITEMS.first()
        val (msid, _) = try { withContext(Dispatchers.IO) { jf.facts(item.id) } } catch (e: Exception) {
            emit(JSONObject().put("kind", "resume_error").put("err", e.message ?: "facts")); return
        }
        val ps = UUID.randomUUID().toString().replace("-", "")
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(mapOf("Authorization" to jf.auth))
        val player = ExoPlayer.Builder(this).setMediaSourceFactory(DefaultMediaSourceFactory(http)).build()
        playerView.useController = true
        playerView.player = player
        (playerView.findViewById<android.view.View>(androidx.media3.ui.R.id.exo_progress) as? DefaultTimeBar)?.setKeyTimeIncrement(30_000)
        player.setMediaItem(MediaItem.fromUri(jf.url("/Videos/${item.id}/stream?static=true&MediaSourceId=$msid&DeviceId=$deviceId")))
        player.playWhenReady = true
        player.prepare()
        playerView.requestFocus()
        say("Resume test: skip to about 5:00 (right on the progress bar = 30 s), then press Back.")
        fun body(): JSONObject = JSONObject().put("ItemId", item.id).put("MediaSourceId", msid).put("PlaySessionId", ps)
            .put("PositionTicks", player.currentPosition * 10_000).put("IsPaused", !player.isPlaying).put("CanSeek", true)
            .put("PlayMethod", "DirectPlay")
        suspend fun report(path: String, b: JSONObject) {
            try { withContext(Dispatchers.IO) { jf.post(path, b) } } catch (e: Exception) { Log.w(TAG, "report failed: ${e.message}") }
        }
        report("/Sessions/Playing", body())
        val stop = CompletableDeferred<Unit>()
        stopResume = stop
        while (scope.isActive && withTimeoutOrNull(10_000) { stop.await() } == null) {
            report("/Sessions/Playing/Progress", body().put("EventName", "timeupdate"))
        }
        stopResume = null
        val pos = player.currentPosition
        player.pause()
        report("/Sessions/Playing/Stopped", body())
        player.release()
        playerView.player = null
        playerView.useController = false
        emit(JSONObject().put("kind", "resume_stop").put("device", "TV").put("n", item.n).put("id", item.id)
            .put("position_s", pos / 1000))
        say("Stopped at ${pos / 60_000}:${"%02d".format((pos / 1000) % 60)}. Now open row 1 on the phone.")
    }

    // ------------------------------------------------------------------ keys, output
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val v = verdict
        if (event.action == KeyEvent.ACTION_DOWN) {
            when (event.keyCode) {
                KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> {
                    if (v != null) { v.complete("yes"); return true }
                    choice?.let { it.complete(true); return true }
                }
                KeyEvent.KEYCODE_BACK -> {
                    if (token.isEmpty() && v == null && choice == null) return super.dispatchKeyEvent(event)   // sign-in screen: exit
                    when {
                        v != null -> v.complete("no")
                        choice != null -> choice?.complete(false)
                        stopResume != null -> stopResume?.complete(Unit)
                        else -> { aborted = true; say("Stopping after this run...") }
                    }
                    return true
                }
            }
        } else if (event.keyCode == KeyEvent.KEYCODE_BACK && token.isNotEmpty()) {
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    private fun decoderMimes(): Set<String> = MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos
        .filter { !it.isEncoder }.flatMap { it.supportedTypes.toList() }.map { it.lowercase() }.toSet()

    @Suppress("DEPRECATION")
    private fun emitSession(mimes: Set<String>) {
        val hdr = try { windowManager.defaultDisplay.hdrCapabilities?.supportedHdrTypes?.toList() ?: emptyList() } catch (_: Exception) { emptyList() }
        val wv = WebView.getCurrentWebViewPackage()
        emit(JSONObject().put("kind", "session").put("device", "TV").put("network", network)
            .put("model", Build.MODEL).put("sdk", Build.VERSION.SDK_INT)
            .put("webview", wv?.let { "${it.packageName} ${it.versionName}" } ?: "")
            .put("video", JSONArray(Study.videoCodecs(mimes))).put("audio", JSONArray(Study.audioCodecs(mimes, false)))
            .put("audio_ffmpeg", JSONArray(Study.audioCodecs(mimes, true))).put("hdr_types", JSONArray(hdr))
            .put("app", "0.1.0"))
    }

    private fun emit(o: JSONObject) = logLine(o.toString())

    private fun logLine(json: String) {
        val line = Study.scrub(json, token)
        Log.i(TAG, if (line.length <= 3800) line else JSONObject().put("kind", "oversize").put("len", line.length).toString())
    }

    private fun say(text: String) = runOnUiThread { overlay.text = text }

    companion object {
        private const val TAG = "JY051"
        private const val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        private const val DEFAULT_JF = "https://jellyfin.joeyhome.net:8443"
    }
}
