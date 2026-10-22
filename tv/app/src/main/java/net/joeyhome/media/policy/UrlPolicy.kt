package net.joeyhome.media.policy

import java.net.URLDecoder

/** What the WebView does with a main-frame navigation (Q41). */
sealed interface UrlDecision {
    /** Same origin as the Joey Media UI: load it in the WebView. */
    data object Load : UrlDecision

    /** The Jellyfin origin: hand off to the Jellyfin app; [itemId] null = open the app home. */
    data class HandOff(val itemId: String?) : UrlDecision

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
            origin == hosts.jellyfin -> UrlDecision.HandOff(itemIdFromFragment(url))
            origin.host in YOUTUBE_HOSTS -> UrlDecision.External(url)
            else -> UrlDecision.Block
        }
    }

    companion object {
        val YOUTUBE_HOSTS = setOf("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")

        /** `id=` inside the fragment's query, e.g. `/web/#/details?id=abc&serverId=s` → `abc`. */
        fun itemIdFromFragment(url: String): String? {
            val fragment = Origin.parse(url)?.rawFragment ?: return null
            val query = fragment.substringAfter('?', "")
            if (query.isEmpty()) return null
            return query.split('&')
                .firstOrNull { it.startsWith("id=") }
                ?.substringAfter("id=")
                ?.let { URLDecoder.decode(it, "UTF-8") }
                ?.takeIf { it.isNotBlank() }
        }
    }
}
