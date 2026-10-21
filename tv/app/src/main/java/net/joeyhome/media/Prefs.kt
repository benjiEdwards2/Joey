package net.joeyhome.media

import android.content.Context

/** Small persistent state: host overrides (hidden settings), the last UI URL, and the "returning from playback" mark. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("joeytv", Context.MODE_PRIVATE)

    var uiOverride: String?
        get() = sp.getString(KEY_UI, null)
        set(value) = sp.edit().putString(KEY_UI, value?.trim()?.ifEmpty { null }).apply()

    var jellyfinOverride: String?
        get() = sp.getString(KEY_JF, null)
        set(value) = sp.edit().putString(KEY_JF, value?.trim()?.ifEmpty { null }).apply()

    var lastUrl: String?
        get() = sp.getString(KEY_LAST_URL, null)
        set(value) = sp.edit().putString(KEY_LAST_URL, value).apply()

    var returningFromPlayback: Boolean
        get() = sp.getBoolean(KEY_RETURNING, false)
        set(value) = sp.edit().putBoolean(KEY_RETURNING, value).apply()

    /** When the last update check got a valid version.json (epoch ms), or null: the 24 h throttle (WP-B8). */
    var lastUpdateCheck: Long?
        get() = if (sp.contains(KEY_UPDATE_CHECK)) sp.getLong(KEY_UPDATE_CHECK, 0L) else null
        set(value) = sp.edit().apply { if (value == null) remove(KEY_UPDATE_CHECK) else putLong(KEY_UPDATE_CHECK, value) }.apply()

    /** Reads and clears the mark in one go. */
    fun consumeReturningFromPlayback(): Boolean = returningFromPlayback.also { if (it) returningFromPlayback = false }

    fun clearHosts() {
        sp.edit().remove(KEY_UI).remove(KEY_JF).apply()
    }

    private companion object {
        const val KEY_UI = "ui_host"
        const val KEY_JF = "jellyfin_host"
        const val KEY_LAST_URL = "last_url"
        const val KEY_RETURNING = "returning_from_playback"
        const val KEY_UPDATE_CHECK = "last_update_check"
    }
}
