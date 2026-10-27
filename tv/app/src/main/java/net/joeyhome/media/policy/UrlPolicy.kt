package net.joeyhome.media.policy

import java.net.URLDecoder

/** What the WebView does with a main-frame navigation (Q41). */
sealed interface UrlDecision {
    /** Same origin as the Joey Media UI: load it in the WebView. */
    data object Load : UrlDecision

    /** The Jellyfin origin: hand off to the Jellyfin app; [itemId] null = open the app home. */
    data class HandOff(val itemId: String?) : UrlDecision

    /** JY-057: a Jellyfin item link the hub marked `player=joey` (household, flag on): the shell's own player. */
    data class Play(val itemId: String) : UrlDecision

    /** YouTube: ACTION_VIEW (the YouTube app), toast if nothing handles it. */
    data class External(val url: String) : UrlDecision

    /** Anything else: blocked with a "Not available on TV" toast. */
    data object Block : UrlDecision
}

class UrlPolicy(private val hosts: HostConfig) {

    fun decide(url: String): UrlDecision {
        val origin = Origin.of(url) ?: return UrlDecision.Block
        return when {
            origin == hosts.ui -> UrlDecision.Load
            origin == hosts.jellyfin -> jellyfin(url)
            origin.host in YOUTUBE_HOSTS -> UrlDecision.External(url)
            else -> UrlDecision.Block
        }
    }

    /** The hub's mark plus a well-formed id = the shell's player; anything else = today's hand-off (WP-B6 route 1b). */
    private fun jellyfin(url: String): UrlDecision {
        val id = itemIdFromFragment(url)
        if (id != null && fragmentParam(url, PLAYER_PARAM) == PLAYER_VALUE && JellyfinItemRoute.isItemId(id)) {
            return UrlDecision.Play(id)
        }
        return UrlDecision.HandOff(id)
    }

    companion object {
        /** JY-057: the mark hub/media_front.py adds (TV_PLAYER_MARK) to Play links for the shell's own player. */
        const val PLAYER_PARAM = "player"
        const val PLAYER_VALUE = "joey"

        val YOUTUBE_HOSTS = setOf("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")

        /** `id=` inside the fragment's query, e.g. `/web/#/details?id=abc&serverId=s` → `abc`. */
        fun itemIdFromFragment(url: String): String? = fragmentParam(url, "id")

        /** One parameter of the fragment's query (`#/details?id=abc&player=joey`), decoded; null when absent or blank. */
        fun fragmentParam(url: String, name: String): String? {
            val fragment = Origin.parse(url)?.rawFragment ?: return null
            val query = fragment.substringAfter('?', "")
            if (query.isEmpty()) return null
            return query.split('&')
                .firstOrNull { it.startsWith("$name=") }
                ?.substringAfter("$name=")
                ?.let { URLDecoder.decode(it, "UTF-8") }
                ?.takeIf { it.isNotBlank() }
        }
    }
}
