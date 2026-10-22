package net.joeyhome.media.policy

import android.content.Intent

/**
 * Playback hand-off to the official Jellyfin Android TV app (DECISIONS E). The route is the WP-B6 decision
 * (`JoeyTV\spike\SPIKE_RESULTS.md`, 2026-10-21: route 1, variant 1b, 12/12 cells PASS on a TCL, Android 14,
 * Jellyfin app 0.19.10).
 *
 * Pure description of an explicit intent, so JVM tests assert the exact component, extras and flags without an
 * Android runtime. JellyfinLauncher turns it into a real Intent.
 */
data class IntentSpec(
    val packageName: String,
    val className: String,
    val action: String? = null,
    val extras: Map<String, Any> = emptyMap(),
    val flags: Int = 0,
)

/** Builds the "open this item" intent for one hand-off route; null = no item intent, use route 3 (app home). */
fun interface PlaybackRoute {
    fun itemIntent(itemId: String): IntentSpec?
}

/**
 * Route 1b (WP-B6 decision line): explicit component `org.jellyfin.androidtv/.ui.startup.StartupActivity`, NO action,
 * String extra `ItemId`, NO flags. Opens the item's details page (one OK plays or resumes).
 *
 * No FLAG_ACTIVITY_NEW_TASK (W5, 2026-10-22): with it Jellyfin opened as its own task, so Back after watching left
 * the viewer on the TV's home screen; started from our Activity without it, Jellyfin's details/player stack on top of
 * Joey Media's task and Back returns to the Joey Media page the viewer came from. JellyfinLauncher starts it with
 * the Activity context, so no flag is required.
 *
 * Only well-formed ids (32 hex, or the dashed UUID form) get an item intent; anything else goes to route 3. The ids
 * come from the page's Jellyfin links, which the server builds from Jellyfin API ids: a valid-looking id Jellyfin does
 * not know would open an EMPTY details page (spike), so never synthesise one.
 *
 * Not used, by the spike's findings: the implicit VIEW / `-p` launcher intents (no DEFAULT category, they don't
 * resolve) and the `.startup.StartupActivity` alias (not exported).
 */
object JellyfinItemRoute : PlaybackRoute {
    const val CLASS_NAME = "org.jellyfin.androidtv.ui.startup.StartupActivity"
    const val EXTRA_ITEM_ID = "ItemId"

    private val ITEM_ID = Regex("^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    fun isItemId(id: String): Boolean = ITEM_ID.matches(id)

    override fun itemIntent(itemId: String): IntentSpec? {
        val id = itemId.trim()
        if (!isItemId(id)) return null
        return IntentSpec(
            packageName = Jellyfin.PACKAGE,
            className = CLASS_NAME,
            action = null,
            extras = mapOf(EXTRA_ITEM_ID to id),
            flags = 0,
        )
    }
}

/** One attempt in the hand-off fallback chain. */
sealed interface HandOffStep {
    /** Route 1b: the item's details page. */
    data class Item(val spec: IntentSpec) : HandOffStep

    /** Route 3: the Jellyfin app home via `getLeanbackLaunchIntentForPackage` (explicit component, NEW_TASK). */
    data object AppHome : HandOffStep

    /** The "Jellyfin isn't on this TV yet" card (store intent `market://details?id=org.jellyfin.androidtv`). */
    data object MissingCard : HandOffStep
}

/**
 * Fallback order: package missing → the card only; else the item intent (if the id is well formed), then route 3
 * (on ActivityNotFoundException / SecurityException or no item intent), then the card if route 3 also fails.
 */
object HandOff {

    fun plan(jellyfinInstalled: Boolean, itemId: String?, route: PlaybackRoute = JellyfinItemRoute): List<HandOffStep> {
        if (!jellyfinInstalled) return listOf(HandOffStep.MissingCard)
        val item = itemId?.trim()?.takeIf { it.isNotEmpty() }?.let { route.itemIntent(it) }
        return listOfNotNull(item?.let { HandOffStep.Item(it) }, HandOffStep.AppHome, HandOffStep.MissingCard)
    }

    /** Runs the steps in order until one succeeds; [attempt] returns false when a start threw. Returns the step that ran. */
    fun run(steps: List<HandOffStep>, attempt: (HandOffStep) -> Boolean): HandOffStep =
        steps.firstOrNull { attempt(it) } ?: HandOffStep.MissingCard
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
