package net.joeyhome.media.policy

import android.view.KeyEvent

/** What sits over the picture (JY-057, look A "Classic overlay"). */
enum class PlayerOverlay { NONE, CONTROLS, POPUP, UP_NEXT }

/** The two focus rows of look A on TV: the seek bar, then the buttons. */
enum class FocusRow { BAR, BUTTONS }

enum class PlayerButton { PLAY_PAUSE, BACK_10, FORWARD_30, TRACKS, NEXT }

/** The Audio & subtitles pop-up's two columns. */
enum class PopupColumn { AUDIO, SUBTITLES }

enum class UpNextChoice { PLAY_NOW, WATCH_CREDITS }

/** What PlayerActivity does after a key or a tick. */
sealed interface PlayerAction {
    data object None : PlayerAction
    data class SeekBy(val ms: Long) : PlayerAction
    data object TogglePlay : PlayerAction
    data object Play : PlayerAction
    data object Pause : PlayerAction
    data class PickAudio(val index: Int) : PlayerAction
    data class PickSubtitle(val index: Int) : PlayerAction
    data object PlayNext : PlayerAction
    data object ReturnToJoey : PlayerAction
}

/**
 * The player overlay's whole state, pure (JVM-tested). [audio] and [subtitles] are Jellyfin MediaStream indexes in the
 * pop-up's order; [subtitles] always starts with [PlayerUi.OFF].
 */
data class PlayerUiState(
    val overlay: PlayerOverlay = PlayerOverlay.CONTROLS,
    val row: FocusRow = FocusRow.BUTTONS,
    val button: PlayerButton = PlayerButton.PLAY_PAUSE,
    val column: PopupColumn = PopupColumn.AUDIO,
    val audio: List<Int> = emptyList(),
    val subtitles: List<Int> = listOf(PlayerUi.OFF),
    val audioCursor: Int = 0,
    val subtitleCursor: Int = 0,
    val hasNext: Boolean = false,
    val upNextChoice: UpNextChoice = UpNextChoice.PLAY_NOW,
    val upNextDismissed: Boolean = false,
    val countdownFromMs: Long? = null,
    val lastInputMs: Long = 0L,
)

data class PlayerStep(val state: PlayerUiState, val action: PlayerAction = PlayerAction.None)

/**
 * Look A's keys on a remote (JY-052 TV frames): any key shows the controls; Left / Right seek −10 s / +30 s (hidden, or
 * on the bar); Down drops to the buttons, Up climbs back; the pop-up walks with Up / Down and swaps columns with
 * Left / Right; Back closes the pop-up, then hides the controls, then returns to Joey (BackPolicy.player). The controls
 * hide after [HIDE_AFTER_MS] of playing; the up-next card shows in the last [UP_NEXT_LEAD_MS] while they are hidden,
 * and at the end counts down [COUNTDOWN_MS] before the next episode.
 */
object PlayerUi {
    const val OFF = -1
    const val SEEK_BACK_MS = 10_000L
    const val SEEK_FORWARD_MS = 30_000L
    const val HIDE_AFTER_MS = 5_000L
    const val UP_NEXT_LEAD_MS = 60_000L
    const val COUNTDOWN_MS = 8_000L

    private val OK_KEYS = setOf(KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER)
    private val MEDIA_KEYS = setOf(
        KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_MEDIA_PLAY, KeyEvent.KEYCODE_MEDIA_PAUSE,
        KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, KeyEvent.KEYCODE_MEDIA_REWIND, KeyEvent.KEYCODE_MEDIA_NEXT,
        KeyEvent.KEYCODE_MEDIA_STOP,
    )
    private val HANDLED = OK_KEYS + MEDIA_KEYS + setOf(
        KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN,
        KeyEvent.KEYCODE_BACK,
    )

    fun initial(nowMs: Long, hasNext: Boolean) = PlayerUiState(hasNext = hasNext, lastInputMs = nowMs)

    /** The keys the player consumes; everything else (volume, Home, power) goes to the system. */
    fun handles(keyCode: Int): Boolean = keyCode in HANDLED

    fun buttons(state: PlayerUiState): List<PlayerButton> =
        PlayerButton.entries.filter { it != PlayerButton.NEXT || state.hasNext }

    /** The pop-up's lists, with the cursors on the tracks playing now ([subtitleIndex] -1 = Off). */
    fun withTracks(state: PlayerUiState, audio: List<Int>, subtitles: List<Int>, audioIndex: Int?, subtitleIndex: Int): PlayerUiState {
        val subs = listOf(OFF) + subtitles.filter { it != OFF }
        return state.copy(
            audio = audio,
            subtitles = subs,
            audioCursor = (audioIndex?.let { audio.indexOf(it) } ?: 0).coerceAtLeast(0),
            subtitleCursor = subs.indexOf(subtitleIndex).coerceAtLeast(0),
        )
    }

    fun seekTarget(positionMs: Long, deltaMs: Long, durationMs: Long): Long {
        val target = (positionMs + deltaMs).coerceAtLeast(0L)
        return if (durationMs > 0) target.coerceAtMost((durationMs - 1_000L).coerceAtLeast(0L)) else target
    }

    fun onKey(state: PlayerUiState, keyCode: Int, nowMs: Long): PlayerStep {
        val s = state.copy(lastInputMs = nowMs)
        if (keyCode == KeyEvent.KEYCODE_BACK) return onBack(s, nowMs)
        if (keyCode in MEDIA_KEYS) return media(s, keyCode)
        return when (s.overlay) {
            PlayerOverlay.NONE -> hidden(s, keyCode)
            PlayerOverlay.CONTROLS -> if (s.row == FocusRow.BAR) bar(s, keyCode) else buttonsRow(s, keyCode)
            PlayerOverlay.POPUP -> popup(s, keyCode)
            PlayerOverlay.UP_NEXT -> upNext(s, keyCode)
        }
    }

    fun onBack(state: PlayerUiState, nowMs: Long): PlayerStep {
        val s = state.copy(lastInputMs = nowMs)
        return when (BackPolicy.player(s.overlay)) {
            PlayerBack.CLOSE_POPUP -> PlayerStep(s.copy(overlay = PlayerOverlay.CONTROLS, row = FocusRow.BUTTONS, button = PlayerButton.TRACKS))
            PlayerBack.HIDE_CONTROLS -> PlayerStep(s.copy(overlay = PlayerOverlay.NONE))
            PlayerBack.RETURN_TO_JOEY -> PlayerStep(s, PlayerAction.ReturnToJoey)
        }
    }

    /** Every few hundred ms: auto-hide, the up-next card in the last minute, the end countdown. */
    fun onTick(state: PlayerUiState, nowMs: Long, playing: Boolean, positionMs: Long, durationMs: Long): PlayerStep {
        state.countdownFromMs?.let { from ->
            if (nowMs - from >= COUNTDOWN_MS) return PlayerStep(state.copy(countdownFromMs = null), PlayerAction.PlayNext)
            return PlayerStep(state)
        }
        var s = state
        if (s.overlay == PlayerOverlay.CONTROLS && playing && nowMs - s.lastInputMs >= HIDE_AFTER_MS) {
            s = s.copy(overlay = PlayerOverlay.NONE)
        }
        val inLastMinute = durationMs > 0 && durationMs - positionMs <= UP_NEXT_LEAD_MS
        if (s.overlay == PlayerOverlay.NONE && inLastMinute && s.hasNext && !s.upNextDismissed) {
            s = s.copy(overlay = PlayerOverlay.UP_NEXT, upNextChoice = UpNextChoice.PLAY_NOW)
        } else if (s.overlay == PlayerOverlay.UP_NEXT && !inLastMinute) {
            s = s.copy(overlay = PlayerOverlay.NONE)
        }
        return PlayerStep(s)
    }

    /** The file ended: the card and its countdown when there is a next episode, else back to Joey. */
    fun onEnded(state: PlayerUiState, nowMs: Long): PlayerStep {
        if (!state.hasNext) return PlayerStep(state, PlayerAction.ReturnToJoey)
        return PlayerStep(state.copy(overlay = PlayerOverlay.UP_NEXT, upNextChoice = UpNextChoice.PLAY_NOW,
            upNextDismissed = false, countdownFromMs = nowMs))
    }

    /** Whole seconds left on the end countdown (rounded up), or null when none runs. */
    fun countdownLeftS(state: PlayerUiState, nowMs: Long): Int? {
        val from = state.countdownFromMs ?: return null
        val left = (COUNTDOWN_MS - (nowMs - from)).coerceAtLeast(0L)
        return ((left + 999L) / 1_000L).toInt()
    }

    // ---- per overlay ----

    private fun shown(s: PlayerUiState, row: FocusRow, button: PlayerButton = s.button) =
        s.copy(overlay = PlayerOverlay.CONTROLS, row = row, button = button)

    private fun hidden(s: PlayerUiState, keyCode: Int): PlayerStep = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_LEFT -> PlayerStep(shown(s, FocusRow.BAR), PlayerAction.SeekBy(-SEEK_BACK_MS))
        KeyEvent.KEYCODE_DPAD_RIGHT -> PlayerStep(shown(s, FocusRow.BAR), PlayerAction.SeekBy(SEEK_FORWARD_MS))
        in OK_KEYS -> PlayerStep(shown(s, FocusRow.BUTTONS, PlayerButton.PLAY_PAUSE))
        else -> PlayerStep(shown(s, FocusRow.BAR))
    }

    private fun bar(s: PlayerUiState, keyCode: Int): PlayerStep = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_LEFT -> PlayerStep(s, PlayerAction.SeekBy(-SEEK_BACK_MS))
        KeyEvent.KEYCODE_DPAD_RIGHT -> PlayerStep(s, PlayerAction.SeekBy(SEEK_FORWARD_MS))
        KeyEvent.KEYCODE_DPAD_DOWN -> PlayerStep(s.copy(row = FocusRow.BUTTONS))
        in OK_KEYS -> PlayerStep(s, PlayerAction.TogglePlay)
        else -> PlayerStep(s)
    }

    private fun buttonsRow(s: PlayerUiState, keyCode: Int): PlayerStep {
        val list = buttons(s)
        val at = list.indexOf(s.button).coerceAtLeast(0)
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT -> PlayerStep(s.copy(button = list[(at - 1).coerceAtLeast(0)]))
            KeyEvent.KEYCODE_DPAD_RIGHT -> PlayerStep(s.copy(button = list[(at + 1).coerceAtMost(list.size - 1)]))
            KeyEvent.KEYCODE_DPAD_UP -> PlayerStep(s.copy(row = FocusRow.BAR))
            in OK_KEYS -> press(s.copy(button = list[at]))
            else -> PlayerStep(s)
        }
    }

    private fun press(s: PlayerUiState): PlayerStep = when (s.button) {
        PlayerButton.PLAY_PAUSE -> PlayerStep(s, PlayerAction.TogglePlay)
        PlayerButton.BACK_10 -> PlayerStep(s, PlayerAction.SeekBy(-SEEK_BACK_MS))
        PlayerButton.FORWARD_30 -> PlayerStep(s, PlayerAction.SeekBy(SEEK_FORWARD_MS))
        PlayerButton.TRACKS -> PlayerStep(s.copy(overlay = PlayerOverlay.POPUP, column = PopupColumn.AUDIO))
        PlayerButton.NEXT -> PlayerStep(s, PlayerAction.PlayNext)
    }

    private fun popup(s: PlayerUiState, keyCode: Int): PlayerStep {
        val audioCol = s.column == PopupColumn.AUDIO
        val size = if (audioCol) s.audio.size else s.subtitles.size
        val cursor = if (audioCol) s.audioCursor else s.subtitleCursor
        fun moved(to: Int): PlayerUiState {
            val c = to.coerceIn(0, (size - 1).coerceAtLeast(0))
            return if (audioCol) s.copy(audioCursor = c) else s.copy(subtitleCursor = c)
        }
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_UP -> PlayerStep(moved(cursor - 1))
            KeyEvent.KEYCODE_DPAD_DOWN -> PlayerStep(moved(cursor + 1))
            KeyEvent.KEYCODE_DPAD_LEFT -> PlayerStep(s.copy(column = PopupColumn.AUDIO))
            KeyEvent.KEYCODE_DPAD_RIGHT -> PlayerStep(s.copy(column = PopupColumn.SUBTITLES))
            in OK_KEYS -> {
                val closed = s.copy(overlay = PlayerOverlay.CONTROLS, row = FocusRow.BUTTONS, button = PlayerButton.TRACKS)
                val action = if (audioCol) {
                    s.audio.getOrNull(cursor)?.let { PlayerAction.PickAudio(it) }
                } else {
                    s.subtitles.getOrNull(cursor)?.let { PlayerAction.PickSubtitle(it) }
                }
                PlayerStep(closed, action ?: PlayerAction.None)
            }
            else -> PlayerStep(s)
        }
    }

    private fun upNext(s: PlayerUiState, keyCode: Int): PlayerStep = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_LEFT -> PlayerStep(s.copy(upNextChoice = UpNextChoice.PLAY_NOW))
        KeyEvent.KEYCODE_DPAD_RIGHT -> PlayerStep(s.copy(upNextChoice = UpNextChoice.WATCH_CREDITS))
        in OK_KEYS -> if (s.upNextChoice == UpNextChoice.PLAY_NOW) {
            PlayerStep(s.copy(countdownFromMs = null), PlayerAction.PlayNext)
        } else {
            PlayerStep(s.copy(overlay = PlayerOverlay.NONE, upNextDismissed = true, countdownFromMs = null))
        }
        else -> PlayerStep(shown(s, FocusRow.BAR))
    }

    private fun media(s: PlayerUiState, keyCode: Int): PlayerStep {
        val action = when (keyCode) {
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> PlayerAction.TogglePlay
            KeyEvent.KEYCODE_MEDIA_PLAY -> PlayerAction.Play
            KeyEvent.KEYCODE_MEDIA_PAUSE -> PlayerAction.Pause
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> PlayerAction.SeekBy(SEEK_FORWARD_MS)
            KeyEvent.KEYCODE_MEDIA_REWIND -> PlayerAction.SeekBy(-SEEK_BACK_MS)
            KeyEvent.KEYCODE_MEDIA_NEXT -> if (s.hasNext) PlayerAction.PlayNext else PlayerAction.None
            KeyEvent.KEYCODE_MEDIA_STOP -> return PlayerStep(s, PlayerAction.ReturnToJoey)
            else -> PlayerAction.None
        }
        val seeking = action is PlayerAction.SeekBy
        val next = if (s.overlay == PlayerOverlay.NONE) shown(s, if (seeking) FocusRow.BAR else s.row) else s
        return PlayerStep(next, action)
    }
}
