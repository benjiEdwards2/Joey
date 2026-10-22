package net.joeyhome.media.policy

/** TV-mode user agent (D-P8): the WebView default plus ` JoeyTV/<semver> (<versionCode>)`; the server matches `JoeyTV/`. */
object UserAgent {
    private val TOKEN = Regex(" ?JoeyTV/\\S+ \\(\\d+\\)")

    fun build(defaultUserAgent: String, versionName: String, versionCode: Int): String =
        "${defaultUserAgent.replace(TOKEN, "").trimEnd()} JoeyTV/$versionName ($versionCode)"
}
