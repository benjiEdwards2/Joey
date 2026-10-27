package net.joeyhome.media

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.MediaCodecList
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.WebSettings
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import net.joeyhome.media.policy.ApiError
import net.joeyhome.media.policy.DeviceProfile
import net.joeyhome.media.policy.FocusRow
import net.joeyhome.media.policy.HostConfig
import net.joeyhome.media.policy.JellyfinItemRoute
import net.joeyhome.media.policy.KeyPolicy
import net.joeyhome.media.policy.Origin
import net.joeyhome.media.policy.PlayTrack
import net.joeyhome.media.policy.PlayerAction
import net.joeyhome.media.policy.PlayerApi
import net.joeyhome.media.policy.PlayerButton
import net.joeyhome.media.policy.PlayerFallback
import net.joeyhome.media.policy.PlayerOverlay
import net.joeyhome.media.policy.PlayerStep
import net.joeyhome.media.policy.PlayerText
import net.joeyhome.media.policy.PlayerUi
import net.joeyhome.media.policy.PlayerUiState
import net.joeyhome.media.policy.PopupColumn
import net.joeyhome.media.policy.ProgressStep
import net.joeyhome.media.policy.StartAnswer
import net.joeyhome.media.policy.StartStep
import net.joeyhome.media.policy.StreamAnswer
import net.joeyhome.media.policy.SwitchWay
import net.joeyhome.media.policy.TextPick
import net.joeyhome.media.policy.TrackPlan
import net.joeyhome.media.policy.TrackSelection
import net.joeyhome.media.policy.UpNextChoice
import net.joeyhome.media.policy.UserAgent
import org.json.JSONObject

/**
 * JY-057: Joey's own player in the TV shell (Media3 ExoPlayer), look A "Classic overlay". Started by MainActivity for a
 * Play link the hub marked `player=joey` (household, PLAYER_API on). It asks the hub for a playback session on the
 * Joey Media front (docs/playback-contract.md, kind `tv`), plays the stream from the Jellyfin edge with the member's
 * header (memory only, sent to the Jellyfin origin only), reports progress, and returns to Joey on Back. Any start
 * failure hands the item to the Jellyfin app (JY-050 Q7 A). The overlay's state and keys are PlayerUi (pure, JVM-tested).
 */
@OptIn(UnstableApi::class)
class PlayerActivity : Activity() {

    private val main = Handler(Looper.getMainLooper())
    private val io: ExecutorService = Executors.newSingleThreadExecutor()

    private lateinit var prefs: Prefs
    private lateinit var hosts: HostConfig
    private lateinit var api: PlayApiClient
    private lateinit var userAgent: String
    private lateinit var profile: JSONObject
    private lateinit var playerView: PlayerView
    private lateinit var bar: PlayerBar

    private var player: ExoPlayer? = null
    private var ui = PlayerUiState()
    private var itemId = ""
    private var pageTitle: String? = null
    private var session: StartAnswer? = null
    private var stream: StreamAnswer? = null
    private var audioIndex: Int? = null
    private var subtitleIndex = -1
    private var generation = 0
    private var progressSent = false
    private var stopped = true
    private var selectionApplied = false
    private var pressedAt = 0L
    private var firstFrameMs: Long? = null
    private var resumedUntil = 0L
    private var leaving = false
    private var loading = true
    private var lastBackAt = 0L
    private var backCallback: Any? = null

    private val tick = object : Runnable {
        override fun run() {
            onTick()
            main.postDelayed(this, TICK_MS)
        }
    }

    private val heartbeat = object : Runnable {
        override fun run() {
            report()
            main.postDelayed(this, (session?.heartbeatS ?: 10) * 1_000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val id = intent.getStringExtra(EXTRA_ITEM)?.trim().orEmpty()
        if (!JellyfinItemRoute.isItemId(id)) {
            finish()
            return
        }
        itemId = id.replace("-", "").lowercase()
        pageTitle = intent.getStringExtra(EXTRA_TITLE)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_player)
        playerView = findViewById(R.id.player_view)
        playerView.useController = false
        playerView.isFocusable = false
        bar = findViewById(R.id.player_bar)
        prefs = Prefs(this)
        hosts = HostConfig.from(prefs.uiOverride, prefs.jellyfinOverride, BuildConfig.DEBUG)
        userAgent = UserAgent.build(WebSettings.getDefaultUserAgent(this), BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)
        api = PlayApiClient(hosts.ui, userAgent)
        val mimes = decoderMimes()
        profile = DeviceProfile.build(DeviceProfile.videoCodecs(mimes), DeviceProfile.audioCodecs(mimes))
        registerBackCallback()
        pressedAt = SystemClock.elapsedRealtime()
        ui = PlayerUi.initial(SystemClock.uptimeMillis(), hasNext = false)
        begin(itemId, startMs = null, audio = null, subtitle = null, resume = true, attempt = 0)
        render()
    }

    override fun onStart() {
        super.onStart()
        main.post(tick)
    }

    /** The TV left the player (Home, another app): stop the session and close, so Joey is what comes back. */
    override fun onStop() {
        main.removeCallbacks(tick)
        if (!isFinishing) returnToJoey()
        super.onStop()
    }

    override fun onDestroy() {
        unregisterBackCallback()
        main.removeCallbacksAndMessages(null)
        releasePlayer()
        stream = null
        io.shutdown()   // a queued stop still goes out
        super.onDestroy()
    }

    // ---- the session ------------------------------------------------------------------------------------------

    private fun begin(item: String, startMs: Long?, audio: Int?, subtitle: Int?, resume: Boolean, attempt: Int) {
        val gen = ++generation
        loading = true
        val body = PlayerApi.startBody(item, profile, startMs, audio, subtitle, resume)
        val jellyfin = hosts.jellyfin
        io.execute {
            val result = startOnce(body, jellyfin)
            main.post {
                if (gen != generation || isFinishing || isDestroyed) return@post
                when (result) {
                    is Started.Ok -> onStarted(result.answer, result.stream)
                    is Started.Failed -> onStartFailed(result.error, attempt) {
                        begin(item, startMs, audio, subtitle, resume, attempt + 1)
                    }
                }
            }
        }
    }

    private sealed interface Started {
        class Ok(val answer: StartAnswer, val stream: StreamAnswer) : Started
        /** [error] null = no answer at all (a network error). */
        class Failed(val error: ApiError?) : Started
    }

    /** Contract endpoints 1 and 2, on the io thread. Any answer that is not the contract's is a failure. */
    private fun startOnce(body: String, jellyfin: Origin): Started {
        val started = api.post(PlayerApi.START_PATH, body)
        if (started.status == 0) return Started.Failed(null)
        if (started.status != 201) return Started.Failed(PlayerApi.parseError(started.status, started.body))
        val answer = PlayerApi.parseStart(started.body) ?: return Started.Failed(ApiError(started.status, null, false))
        val path = PlayerApi.sessionPath(answer.sessionId, "stream") ?: return Started.Failed(ApiError(started.status, null, false))
        val s = api.post(path, null)
        if (s.status == 0) return Started.Failed(null)
        if (s.status != 200) return Started.Failed(PlayerApi.parseError(s.status, s.body))
        val handOut = PlayerApi.parseStream(s.body, jellyfin) ?: return Started.Failed(ApiError(s.status, null, false))
        return Started.Ok(answer, handOut)
    }

    private fun onStartFailed(error: ApiError?, attempt: Int, retry: () -> Unit) {
        when (PlayerFallback.afterStartFailure(error, attempt)) {
            StartStep.RETRY -> main.postDelayed({ retry() }, RETRY_MS)
            StartStep.HAND_OFF -> handOff()
        }
    }

    private fun onStarted(answer: StartAnswer, handOut: StreamAnswer) {
        session = answer
        stream = handOut
        stopped = false
        progressSent = false
        selectionApplied = false
        audioIndex = answer.audioIndex
        subtitleIndex = answer.subtitleIndex
        val keep = ui
        ui = PlayerUi.withTracks(
            PlayerUi.initial(SystemClock.uptimeMillis(), hasNext = answer.upNext != null)
                .copy(overlay = if (keep.overlay == PlayerOverlay.NONE) PlayerOverlay.NONE else PlayerOverlay.CONTROLS),
            answer.audio.map { it.index }, answer.subtitles.map { it.index }, audioIndex, subtitleIndex,
        )
        if (answer.resumed) resumedUntil = SystemClock.uptimeMillis() + RESUMED_SHOW_MS
        play(answer, handOut)
        render()
    }

    private fun play(answer: StartAnswer, handOut: StreamAnswer) {
        releasePlayer()
        val jellyfin = hosts.jellyfin
        val auth = handOut.authorization
        val http = DefaultHttpDataSource.Factory()
            .setUserAgent(userAgent)
            .setConnectTimeoutMs(HTTP_CONNECT_MS)
            .setReadTimeoutMs(HTTP_READ_MS)
            .setAllowCrossProtocolRedirects(false)
        // The member's header goes to the Jellyfin origin only (contract: never the hub, never a URL)
        val withAuth = ResolvingDataSource.Factory(http) { spec ->
            if (Origin.of(spec.uri.toString()) == jellyfin) spec.withAdditionalHeaders(mapOf("Authorization" to auth)) else spec
        }
        val p = ExoPlayer.Builder(this).setMediaSourceFactory(DefaultMediaSourceFactory(withAuth)).build()
        val subtitles = TrackPlan.sideloads(answer.subtitles, jellyfin).mapNotNull { t ->
            val url = t.url ?: return@mapNotNull null
            MediaItem.SubtitleConfiguration.Builder(Uri.parse(url))
                .setMimeType(TrackPlan.subtitleMime(url))
                .setId(TrackPlan.externalId(t.index))
                .setLanguage(t.language)
                .setLabel(PlayerText.track(t))
                .build()
        }
        val item = MediaItem.Builder().setUri(handOut.url).setSubtitleConfigurations(subtitles)
        if (handOut.hls) item.setMimeType(MimeTypes.APPLICATION_M3U8)
        p.trackSelectionParameters = p.trackSelectionParameters.buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, subtitleIndex < 0).build()
        p.addListener(listener)
        playerView.player = p
        player = p
        p.setMediaItem(item.build(), answer.startMs)
        p.playWhenReady = true
        p.prepare()
    }

    private val listener = object : Player.Listener {
        override fun onRenderedFirstFrame() {
            if (firstFrameMs == null) firstFrameMs = SystemClock.elapsedRealtime() - pressedAt
            loading = false
            if (!progressSent) {
                main.removeCallbacks(heartbeat)
                main.post(heartbeat)   // the first report is Jellyfin's "playing"; then every heartbeat_s
            }
            render()
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (progressSent) report()
            render()
        }

        override fun onPositionDiscontinuity(oldPosition: Player.PositionInfo, newPosition: Player.PositionInfo, reason: Int) {
            if (reason == Player.DISCONTINUITY_REASON_SEEK && progressSent) report()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (playbackState == Player.STATE_ENDED) {
                sendStop()
                apply(PlayerUi.onEnded(ui, SystemClock.uptimeMillis()))
            }
        }

        override fun onTracksChanged(tracks: Tracks) {
            if (!selectionApplied && !tracks.groups.isEmpty()) {
                selectionApplied = true
                applySelection(tracks)
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            handOff()
        }
    }

    private fun releasePlayer() {
        main.removeCallbacks(heartbeat)
        player?.let {
            it.removeListener(listener)
            it.release()
        }
        player = null
        if (::playerView.isInitialized) playerView.player = null
    }

    private fun position(): Long = player?.currentPosition ?: session?.startMs ?: 0L

    /** Contract endpoint 3: progress now (the heartbeat, play / pause, a seek). */
    private fun report() {
        val s = session ?: return
        val p = player ?: return
        if (stopped) return
        val path = PlayerApi.sessionPath(s.sessionId, "progress") ?: return
        val body = PlayerApi.progressBody(p.currentPosition, paused = !p.isPlaying)
        val gen = generation
        progressSent = true
        io.execute {
            val a = api.post(path, body)
            if (a.status == 204) return@execute
            val error = if (a.status == 0) null else PlayerApi.parseError(a.status, a.body)
            main.post {
                if (gen != generation || isFinishing) return@post
                if (PlayerFallback.afterProgressFailure(error) == ProgressStep.RESTART) {
                    // the hub forgot the session (restart, 30 min idle): a new one at the position, same tracks
                    stopped = true
                    begin(itemId, position(), audioIndex, subtitleIndex, resume = false, attempt = 0)
                }
            }
        }
    }

    /** Contract endpoint 4, once per session; only after Jellyfin has heard it play (a stop alone could move resume). */
    private fun sendStop() {
        val s = session ?: return
        if (stopped) return
        stopped = true
        main.removeCallbacks(heartbeat)
        if (!progressSent) return
        val path = PlayerApi.sessionPath(s.sessionId, "stop") ?: return
        val body = PlayerApi.stopBody(position())
        io.execute { api.post(path, body) }
    }

    private fun returnToJoey() {
        if (leaving) return
        leaving = true
        sendStop()
        releasePlayer()
        stream = null
        prefs.returningFromPlayback = true   // MainActivity reloads the page: fresh progress
        finish()
    }

    /** JY-050 Q7 A: the Jellyfin app plays it instead (route 1b), for this release. */
    private fun handOff() {
        if (leaving) return
        leaving = true
        sendStop()
        releasePlayer()
        stream = null
        generation++
        Toast.makeText(this, R.string.player_in_jellyfin, Toast.LENGTH_SHORT).show()
        JellyfinLauncher(
            activity = this,
            onMissing = { Toast.makeText(this, R.string.player_no_jellyfin, Toast.LENGTH_LONG).show() },
            onLaunched = { prefs.returningFromPlayback = true },
        ).open(itemId)
        finish()
    }

    private fun playNext() {
        val next = session?.upNext ?: return
        sendStop()
        releasePlayer()
        stream = null
        session = null
        itemId = next.itemId
        pageTitle = next.label
        firstFrameMs = null
        pressedAt = SystemClock.elapsedRealtime()
        ui = PlayerUi.initial(SystemClock.uptimeMillis(), hasNext = false)
        begin(itemId, startMs = null, audio = null, subtitle = null, resume = true, attempt = 0)
        render()
    }

    // ---- tracks -----------------------------------------------------------------------------------------------

    private fun pickTracks(audio: Int?, subtitle: Int) {
        val s = session ?: return
        audioIndex = audio
        subtitleIndex = subtitle
        ui = PlayerUi.withTracks(ui, ui.audio, ui.subtitles, audioIndex, subtitleIndex)
        when (TrackPlan.way(s.playMethod)) {
            SwitchWay.IN_PLAYER -> player?.let { applySelection(it.currentTracks) }
            SwitchWay.RESTART -> {
                val at = position()
                sendStop()
                releasePlayer()
                begin(itemId, at, audioIndex, subtitleIndex, resume = false, attempt = 0)
            }
        }
    }

    private fun applySelection(tracks: Tracks) {
        val s = session ?: return
        val p = player ?: return
        val sel: TrackSelection = TrackPlan.selection(s.playMethod, s.audio, s.subtitles, audioIndex, subtitleIndex)
        val params = p.trackSelectionParameters.buildUpon()
        sel.audioOrdinal?.let { n ->
            tracks.groups.filter { it.type == C.TRACK_TYPE_AUDIO }.getOrNull(n)?.let {
                params.setOverrideForType(TrackSelectionOverride(it.mediaTrackGroup, 0))
            }
        }
        val texts = tracks.groups.filter { it.type == C.TRACK_TYPE_TEXT }
        fun sideloaded(g: Tracks.Group) = (g.getTrackFormat(0).id ?: "").contains("joey-sub-")
        val group = when (val t = sel.text) {
            TextPick.Off -> null
            is TextPick.Embedded -> texts.filterNot { sideloaded(it) }.getOrNull(t.ordinal)
            is TextPick.External -> texts.firstOrNull { (it.getTrackFormat(0).id ?: "").contains(t.id) }
            TextPick.InStream -> texts.firstOrNull { !sideloaded(it) }
        }
        if (group == null) {
            params.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
        } else {
            params.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
            params.setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, 0))
        }
        p.trackSelectionParameters = params.build()
    }

    // ---- keys -------------------------------------------------------------------------------------------------

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val code = event.keyCode
        if (!PlayerUi.handles(code)) return super.dispatchKeyEvent(event)
        if (KeyPolicy.intercepts(code)) {   // Back: also OnBackInvokedCallback on API 33+, de-duplicated
            if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) handleBack()
            return true
        }
        if (event.action != KeyEvent.ACTION_DOWN) return true
        if (event.repeatCount > 0 && code !in REPEATABLE) return true   // held Left / Right keep seeking; OK does not
        apply(PlayerUi.onKey(ui, code, SystemClock.uptimeMillis()))
        return true
    }

    private fun handleBack() {
        val now = SystemClock.uptimeMillis()
        if (now - lastBackAt < BACK_DEDUPE_MS) return
        lastBackAt = now
        apply(PlayerUi.onBack(ui, now))
    }

    private fun registerBackCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val callback = android.window.OnBackInvokedCallback { handleBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
            backCallback = callback
        }
    }

    private fun unregisterBackCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            (backCallback as? android.window.OnBackInvokedCallback)?.let { onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it) }
        }
        backCallback = null
    }

    private fun apply(step: PlayerStep) {
        ui = step.state
        val p = player
        when (val a = step.action) {
            PlayerAction.None -> Unit
            is PlayerAction.SeekBy -> p?.let { it.seekTo(PlayerUi.seekTarget(it.currentPosition, a.ms, duration(it))) }
            PlayerAction.TogglePlay -> p?.let { if (it.isPlaying) it.pause() else it.play() }
            PlayerAction.Play -> p?.play()
            PlayerAction.Pause -> p?.pause()
            is PlayerAction.PickAudio -> pickTracks(a.index, subtitleIndex)
            is PlayerAction.PickSubtitle -> pickTracks(audioIndex, a.index)
            PlayerAction.PlayNext -> playNext()
            PlayerAction.ReturnToJoey -> returnToJoey()
        }
        render()
    }

    private fun duration(p: Player): Long = p.duration.takeIf { it != C.TIME_UNSET && it > 0 } ?: (session?.runtimeMs ?: -1L)

    private fun onTick() {
        if (leaving) return
        val p = player
        if (p != null && session != null && !stopped) {
            val step = PlayerUi.onTick(ui, SystemClock.uptimeMillis(), p.isPlaying, p.currentPosition, duration(p))
            if (step.state != ui || step.action != PlayerAction.None) {
                apply(step)
                return
            }
        } else if (ui.countdownFromMs != null) {
            val step = PlayerUi.onTick(ui, SystemClock.uptimeMillis(), false, 0, 0)
            if (step.action != PlayerAction.None || step.state != ui) {
                apply(step)
                return
            }
        }
        render()
    }

    // ---- drawing ----------------------------------------------------------------------------------------------

    private fun render() {
        if (!::bar.isInitialized) return
        val now = SystemClock.uptimeMillis()
        val s = session
        val p = player
        val controls = ui.overlay == PlayerOverlay.CONTROLS || ui.overlay == PlayerOverlay.POPUP
        view<TextView>(R.id.player_loading).visibility = vis(loading && !leaving)
        view<View>(R.id.player_top).visibility = vis(controls)
        view<View>(R.id.player_bottom).visibility = vis(controls)
        view<TextView>(R.id.player_title).text = PlayerText.pageTitle(pageTitle)
        view<TextView>(R.id.player_meta).text = listOfNotNull(
            s?.let { PlayerText.method(it.playMethod) }, firstFrameMs?.let { PlayerText.firstFrame(it) },
        ).joinToString(" · ")
        view<TextView>(R.id.player_resumed).apply {
            visibility = vis(now < resumedUntil && s != null)
            text = s?.let { PlayerText.resumed(it.startMs) }.orEmpty()
        }
        val dur = p?.let { duration(it) } ?: -1L
        val pos = position()
        view<TextView>(R.id.player_time).text = PlayerText.progress(pos, dur)
        view<TextView>(R.id.player_chapter).text = s?.let { PlayerText.chapter(it.chapters, pos) }.orEmpty()
        bar.isActivated = ui.overlay == PlayerOverlay.CONTROLS && ui.row == FocusRow.BAR
        bar.update(dur.coerceAtLeast(0L), pos, p?.bufferedPosition ?: 0L, s?.chapters?.map { it.startMs } ?: emptyList())
        val buttons = mapOf(
            PlayerButton.PLAY_PAUSE to R.id.player_btn_play, PlayerButton.BACK_10 to R.id.player_btn_back,
            PlayerButton.FORWARD_30 to R.id.player_btn_forward, PlayerButton.TRACKS to R.id.player_btn_tracks,
            PlayerButton.NEXT to R.id.player_btn_next,
        )
        for ((b, id) in buttons) {
            view<TextView>(id).isActivated = ui.overlay == PlayerOverlay.CONTROLS && ui.row == FocusRow.BUTTONS && ui.button == b
        }
        view<View>(R.id.player_btn_next).visibility = vis(ui.hasNext)
        view<TextView>(R.id.player_btn_play).setText(if (p?.playWhenReady == false) R.string.player_play else R.string.player_pause)
        renderPopup(s)
        renderUpNext(s, now)
    }

    private fun renderPopup(s: StartAnswer?) {
        val open = ui.overlay == PlayerOverlay.POPUP && s != null
        view<View>(R.id.player_popup).visibility = vis(open)
        if (!open || s == null) return
        val byIndex = (s.audio + s.subtitles).associateBy { it.index }
        fillColumn(R.id.player_audio_list, R.id.player_audio_scroll, ui.audio.map { byIndex[it] },
            ui.column == PopupColumn.AUDIO, ui.audioCursor, audioIndex)
        fillColumn(R.id.player_subs_list, R.id.player_subs_scroll, ui.subtitles.map { if (it == PlayerUi.OFF) null else byIndex[it] },
            ui.column == PopupColumn.SUBTITLES, ui.subtitleCursor, subtitleIndex)
    }

    /** One pop-up column; a null track is "Off". The playing track is ticked, the cursor ringed in the active column. */
    private fun fillColumn(listId: Int, scrollId: Int, tracks: List<PlayTrack?>, active: Boolean, cursor: Int, playing: Int?) {
        val list = view<LinearLayout>(listId)
        while (list.childCount < tracks.size) {
            list.addView(TextView(this, null, 0, R.style.JoeyPlayerRow).apply { isFocusable = false },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, rowHeight()))
        }
        while (list.childCount > tracks.size) list.removeViewAt(list.childCount - 1)
        tracks.forEachIndexed { i, t ->
            val row = list.getChildAt(i) as TextView
            val label = t?.let { PlayerText.track(it) } ?: PlayerText.subtitleOff()
            val isPlaying = (t?.index ?: PlayerUi.OFF) == playing
            row.text = if (isPlaying) getString(R.string.player_playing_mark, label) else label
            row.isActivated = active && i == cursor
        }
        val scroll = view<ScrollView>(scrollId)
        val height = if (tracks.size > MAX_ROWS) MAX_ROWS * rowHeight() else ViewGroup.LayoutParams.WRAP_CONTENT
        if (scroll.layoutParams.height != height) scroll.layoutParams = scroll.layoutParams.apply { this.height = height }
        val target = list.getChildAt(cursor)
        if (active && target != null && scroll.tag != cursor) {
            scroll.tag = cursor
            scroll.post { scroll.smoothScrollTo(0, (target.top - rowHeight()).coerceAtLeast(0)) }
        }
    }

    private fun renderUpNext(s: StartAnswer?, now: Long) {
        val next = s?.upNext
        val open = ui.overlay == PlayerOverlay.UP_NEXT && next != null
        view<View>(R.id.player_upnext).visibility = vis(open)
        if (!open || next == null) return
        view<TextView>(R.id.player_upnext_label).text = next.label
        view<TextView>(R.id.player_upnext_meta).text =
            PlayerUi.countdownLeftS(ui, now)?.let { PlayerText.countdown(it) } ?: next.runtime.orEmpty()
        view<View>(R.id.player_upnext_play).isActivated = ui.upNextChoice == UpNextChoice.PLAY_NOW
        view<View>(R.id.player_upnext_credits).isActivated = ui.upNextChoice == UpNextChoice.WATCH_CREDITS
    }

    private fun rowHeight(): Int = (56 * resources.displayMetrics.density).toInt()

    private fun vis(shown: Boolean) = if (shown) View.VISIBLE else View.GONE

    private fun <T : View> view(id: Int): T = findViewById(id)

    private fun decoderMimes(): Set<String> = try {
        MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos
            .filter { !it.isEncoder }
            .flatMap { it.supportedTypes.toList() }
            .map { it.lowercase() }
            .toSet()
    } catch (e: RuntimeException) {
        emptySet()
    }

    companion object {
        const val EXTRA_ITEM = "net.joeyhome.media.player.ITEM"
        const val EXTRA_TITLE = "net.joeyhome.media.player.TITLE"
        private const val TICK_MS = 250L
        private const val RETRY_MS = 1_000L
        private const val RESUMED_SHOW_MS = 4_000L
        private const val BACK_DEDUPE_MS = 250L
        private const val HTTP_CONNECT_MS = 15_000
        private const val HTTP_READ_MS = 30_000
        private const val MAX_ROWS = 6
        private val REPEATABLE = setOf(
            KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN,
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, KeyEvent.KEYCODE_MEDIA_REWIND,
        )

        /** The only extras: the item id and the page's title (words to show). Never a token or a URL. */
        fun intent(context: Context, itemId: String, pageTitle: String?): Intent =
            Intent(context, PlayerActivity::class.java)
                .putExtra(EXTRA_ITEM, itemId)
                .putExtra(EXTRA_TITLE, pageTitle)
    }
}
