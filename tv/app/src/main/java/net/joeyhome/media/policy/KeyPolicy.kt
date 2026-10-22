package net.joeyhome.media.policy

import android.view.KeyEvent

/**
 * The shell handles D-pad, Back and Home only; media keys belong to the Jellyfin app (DECISIONS D).
 * KeyEvent constants are compile-time ints, so this stays testable on the plain JVM.
 */
object KeyPolicy {

    /** MainActivity.dispatchKeyEvent intercepts exactly these. */
    fun intercepts(keyCode: Int): Boolean = keyCode == KeyEvent.KEYCODE_BACK

    /** MainActivity.dispatchKeyEvent returns false for these without dispatching them. */
    fun isMediaKey(keyCode: Int): Boolean = keyCode in MEDIA_KEYS

    val MEDIA_KEYS: Set<Int> = setOf(
        KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
        KeyEvent.KEYCODE_MEDIA_STOP,
        KeyEvent.KEYCODE_MEDIA_NEXT,
        KeyEvent.KEYCODE_MEDIA_PREVIOUS,
        KeyEvent.KEYCODE_MEDIA_REWIND,
        KeyEvent.KEYCODE_MEDIA_FAST_FORWARD,
        KeyEvent.KEYCODE_MEDIA_PLAY,
        KeyEvent.KEYCODE_MEDIA_PAUSE,
        KeyEvent.KEYCODE_MEDIA_CLOSE,
        KeyEvent.KEYCODE_MEDIA_EJECT,
        KeyEvent.KEYCODE_MEDIA_RECORD,
        KeyEvent.KEYCODE_MEDIA_AUDIO_TRACK,
        KeyEvent.KEYCODE_MEDIA_TOP_MENU,
        KeyEvent.KEYCODE_MEDIA_SKIP_FORWARD,
        KeyEvent.KEYCODE_MEDIA_SKIP_BACKWARD,
        KeyEvent.KEYCODE_MEDIA_STEP_FORWARD,
        KeyEvent.KEYCODE_MEDIA_STEP_BACKWARD,
    )
}

/** Hold OK for 2 s on Splash or Offline → the hidden settings screen (DECISIONS D). */
object SettingsGesture {
    const val HOLD_MS = 2_000L

    fun isOkKey(keyCode: Int): Boolean = keyCode == KeyEvent.KEYCODE_DPAD_CENTER ||
        keyCode == KeyEvent.KEYCODE_ENTER || keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER

    fun reached(downTimeMs: Long, eventTimeMs: Long): Boolean = eventTimeMs - downTimeMs >= HOLD_MS
}
