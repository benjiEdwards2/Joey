package net.joeyhome.media.policy

/**
 * Playback hand-off to the official Jellyfin Android TV app (DECISIONS E; spike/HANDOFF_RESEARCH_2026-10-19.md).
 *
 * Pure description of an explicit intent, so the WP-B7 step 7 JVM test can assert the exact component, extras and
 * flags without an Android runtime. JellyfinLauncher turns it into a real Intent.
 */
data class IntentSpec(
    val packageName: String,
    val className: String,
    val action: String? = null,
    val extras: Map<String, Any> = emptyMap(),
    val flags: Int = 0,
)

/** Builds the "open this item" intent for one hand-off route; null = no item route, use route 3 (app home). */
fun interface PlaybackRoute {
    fun itemIntent(itemId: String): IntentSpec?
}

/**
 * TODO(WP-B7 step 7): replace with the route recorded on the WP-B6 decision line in DECISIONS.md (route, component,
 * action, extras, flags) and add its JVM test (exact component, extras and flags). Research prediction, NOT yet
 * confirmed on the TV: route 1b = component `org.jellyfin.androidtv/.ui.startup.StartupActivity`, no action,
 * String extra `ItemId` = the 32-hex id, flags FLAG_ACTIVITY_NEW_TASK. Until then every hand-off opens the Jellyfin
 * app home (route 3), which is always the fallback anyway.
 */
object PendingPlaybackRoute : PlaybackRoute {
    override fun itemIntent(itemId: String): IntentSpec? = null
}

object Jellyfin {
    const val PACKAGE = "org.jellyfin.androidtv"
    const val AMAZON_ASIN = "B07TX7Z725"

    /** Store links for the "Jellyfin app missing" card, tried in order (research F5). Fire TV is unproven (no device). */
    fun storeLinks(fireTv: Boolean): List<String> = if (fireTv) {
        listOf("amzn://apps/android?p=$PACKAGE", "https://www.amazon.com/gp/aw/d/$AMAZON_ASIN")
    } else {
        listOf("market://details?id=$PACKAGE", "https://play.google.com/store/apps/details?id=$PACKAGE")
    }
}
