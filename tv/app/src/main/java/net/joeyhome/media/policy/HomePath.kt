package net.joeyhome.media.policy

/**
 * The guest home path BackPolicy compares against, injected at runtime, never a literal: the `home` field of the
 * Splash call's `/healthz` (WP-B1 contract), else the `Location` of the `/` 303. Cached for the session.
 */
object HomePath {
    private val HOME_FIELD = Regex("\"home\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")

    fun resolve(healthzBody: String?, rootRedirectLocation: String?, ui: Origin): String? =
        fromHealthz(healthzBody) ?: fromLocation(rootRedirectLocation, ui)

    /** `"home": "/a/media"` → `/a/media`; a missing or null `home` → null. */
    fun fromHealthz(body: String?): String? {
        val raw = body?.let { HOME_FIELD.find(it)?.groupValues?.get(1) } ?: return null
        return normalise(raw.replace("\\/", "/"))
    }

    /** A relative `Location` path, or an absolute one on the UI origin; anything off-origin → null. */
    fun fromLocation(location: String?, ui: Origin): String? {
        val text = location?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        if (text.startsWith("/") && !text.startsWith("//")) return normalise(text)
        if (Origin.of(text) != ui) return null
        return normalise(Origin.parse(text)?.rawPath)
    }

    /** Path only, leading slash, no trailing slash (except root), no query or fragment. */
    fun normalise(path: String?): String? {
        if (path.isNullOrBlank()) return null
        var p = path.trim().substringBefore('#').substringBefore('?')
        if (!p.startsWith("/") || p.startsWith("//")) return null
        while (p.length > 1 && p.endsWith("/")) p = p.dropLast(1)
        return p
    }
}
