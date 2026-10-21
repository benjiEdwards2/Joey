package net.joeyhome.media.policy

enum class BackAction {
    /** A native screen is open: it handles Back (close, or exit for Splash / Offline / forced update). */
    CLOSE_OVERLAY,

    /** Ask the page first: `window.joeyTV && joeyTV.back && joeyTV.back()` (tv.js, WP-B3). */
    ASK_PAGE,

    /** The page handled it (closed a dialog, moved focus). */
    DONE,

    /** WebView history back. */
    GO_BACK,

    /** Leave the app (Back on Overview exits, DECISIONS D). */
    EXIT,

    /** Load the home path and clear history, so the next Back exits. */
    LOAD_HOME,
}

/**
 * Back key order. [homePath] is injected (see [HomePath]), never a literal.
 *
 * One deliberate difference from the plan's component table: "at home → exit" is checked BEFORE "canGoBack → back",
 * so Back on Overview always exits (DECISIONS D) even when history exists (Overview → Movies → Overview). The plan's
 * named cases (no history) behave the same either way.
 */
object BackPolicy {

    fun decide(
        overlayOpen: Boolean,
        pageHandled: Boolean?,
        canGoBack: Boolean,
        currentPath: String?,
        homePath: String?,
    ): BackAction {
        if (overlayOpen) return BackAction.CLOSE_OVERLAY
        if (pageHandled == null) return BackAction.ASK_PAGE
        if (pageHandled) return BackAction.DONE
        val home = HomePath.normalise(homePath)
        val here = HomePath.normalise(currentPath)
        if (home != null && here == home) return BackAction.EXIT
        if (canGoBack) return BackAction.GO_BACK
        if (home == null) return BackAction.EXIT
        return BackAction.LOAD_HOME
    }

    /** The script the WebView evaluates for [BackAction.ASK_PAGE]; the result string is "true" when the page handled it. */
    const val PAGE_BACK_JS =
        "(function(){try{return !!(window.joeyTV&&joeyTV.back&&joeyTV.back());}catch(e){return false;}})()"
}
