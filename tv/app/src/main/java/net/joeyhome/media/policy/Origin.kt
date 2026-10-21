package net.joeyhome.media.policy

import java.net.URI

/**
 * scheme + host + effective port. Two URLs share an origin only when all three match, so
 * `https://jellyfin.joeyhome.net` (port 443, dead at the Deco) is NOT the Jellyfin origin `https://jellyfin.joeyhome.net:8443`.
 */
data class Origin(val scheme: String, val host: String, val port: Int) {

    override fun toString(): String =
        if (port == defaultPort(scheme)) "$scheme://$host" else "$scheme://$host:$port"

    companion object {
        fun defaultPort(scheme: String): Int = when (scheme) {
            "https" -> 443
            "http" -> 80
            else -> -1
        }

        /** The origin of an http(s) URL, or null for anything else (javascript:, intent:, garbage). */
        fun of(url: String?): Origin? {
            val uri = parse(url) ?: return null
            val scheme = uri.scheme?.lowercase() ?: return null
            if (scheme != "http" && scheme != "https") return null
            val host = uri.host?.lowercase()?.trimEnd('.')?.takeIf { it.isNotEmpty() } ?: return null
            val port = if (uri.port == -1) defaultPort(scheme) else uri.port
            return Origin(scheme, host, port)
        }

        internal fun parse(url: String?): URI? {
            if (url.isNullOrBlank()) return null
            return try {
                URI(url.trim())
            } catch (e: Exception) {
                null
            }
        }
    }
}
