package net.joeyhome.media.policy

/**
 * The two hostnames the shell talks to. Baked in (DECISIONS D; rule 14: names, never IPs); the hidden settings screen
 * may override them for LAN testing. Release builds accept https overrides only; debug builds also accept http
 * (the "laptop via adb reverse" preset).
 */
data class HostConfig(val ui: Origin, val jellyfin: Origin) {

    companion object {
        const val DEFAULT_UI = "https://media.joeyhome.net"

        /** Public port 8443 (DECISIONS 2026-10-19): a non-default port is part of the baked origin. */
        const val DEFAULT_JELLYFIN = "https://jellyfin.joeyhome.net:8443"

        /** Debug preset: the laptop's dev server through `adb reverse tcp:8850 tcp:8850`. */
        const val LAPTOP_UI = "http://127.0.0.1:8850"

        val DEFAULT = HostConfig(Origin.of(DEFAULT_UI)!!, Origin.of(DEFAULT_JELLYFIN)!!)

        /** Checks one override typed on the settings screen. Only a bare origin is accepted (no path, query or user). */
        fun check(raw: String, debugBuild: Boolean): HostCheck {
            val text = raw.trim()
            val uri = Origin.parse(text) ?: return HostCheck.Rejected("Not a valid address")
            val scheme = uri.scheme?.lowercase() ?: return HostCheck.Rejected("Start with https://")
            when (scheme) {
                "https" -> Unit
                "http" -> if (!debugBuild) return HostCheck.Rejected("Release builds need https://")
                else -> return HostCheck.Rejected("Start with https://")
            }
            if (uri.rawUserInfo != null) return HostCheck.Rejected("No user name in the address")
            val path = uri.rawPath.orEmpty()
            if (path.isNotEmpty() && path != "/") return HostCheck.Rejected("Address only, no path")
            if (uri.rawQuery != null || uri.rawFragment != null) return HostCheck.Rejected("Address only, no ? or #")
            val origin = Origin.of(text) ?: return HostCheck.Rejected("Not a valid address")
            return HostCheck.Ok(origin)
        }

        /** Effective config: each override that passes [check] replaces its default; anything else falls back. */
        fun from(uiOverride: String?, jellyfinOverride: String?, debugBuild: Boolean): HostConfig = HostConfig(
            ui = resolve(uiOverride, debugBuild) ?: DEFAULT.ui,
            jellyfin = resolve(jellyfinOverride, debugBuild) ?: DEFAULT.jellyfin,
        )

        private fun resolve(raw: String?, debugBuild: Boolean): Origin? {
            if (raw.isNullOrBlank()) return null
            return (check(raw, debugBuild) as? HostCheck.Ok)?.origin
        }
    }
}

sealed interface HostCheck {
    data class Ok(val origin: Origin) : HostCheck
    data class Rejected(val reason: String) : HostCheck
}
