package net.joeyhome.media.update

/**
 * `<ui>/app/version.json` as the release job writes it (deploy/tv_version.py, D-P9): `min_version` is an INTEGER
 * versionCode and `url` is RELATIVE (a bare `joey-media-<semver>-<versionCode>.apk` name), so a LAN host override also
 * redirects the download. Anything that breaks the contract parses to null and is treated as "no update".
 */
data class RemoteVersion(
    val versionName: String,
    val versionCode: Long,
    val minVersion: Long,
    val url: String,
    val sha256: String,
    val notes: String,
    val size: Long,
) {
    companion object {
        val APK_NAME = Regex("^joey-media-\\d+\\.\\d+\\.\\d+-\\d{10}\\.apk$")
        private val CODE = Regex("^20\\d{6}(0[1-9]|[1-9]\\d)$")
        private val SHA256 = Regex("^[0-9a-f]{64}$")
        private const val MAX_BODY = 64 * 1024

        fun parse(body: String?): RemoteVersion? {
            if (body == null || body.length > MAX_BODY) return null
            val name = FlatJson.string(body, "version") ?: return null
            val code = FlatJson.long(body, "versionCode") ?: return null
            val min = FlatJson.long(body, "min_version") ?: return null
            val url = FlatJson.string(body, "url") ?: return null
            val sha = FlatJson.string(body, "sha256") ?: return null
            val size = FlatJson.long(body, "size") ?: return null
            if (!CODE.matches(code.toString()) || !CODE.matches(min.toString()) || min > code) return null
            if (!APK_NAME.matches(url) || !url.endsWith("-$code.apk")) return null
            if (!SHA256.matches(sha) || size <= 0) return null
            return RemoteVersion(name, code, min, url, sha, FlatJson.string(body, "notes").orEmpty(), size)
        }
    }
}

/**
 * Reads one top-level string or integer field from a small flat JSON object (version.json, /healthz) without a JSON
 * library, so the policy stays pure-JVM testable. Integers must be bare digits: `"min_version": "2026102101"` (a
 * string) is not an integer and fails.
 */
internal object FlatJson {
    private fun key(name: String) = "\"" + Regex.escape(name) + "\"\\s*:\\s*"

    fun string(body: String, name: String): String? {
        val match = Regex(key(name) + "\"((?:[^\"\\\\]|\\\\.)*)\"").find(body) ?: return null
        return unescape(match.groupValues[1])
    }

    fun long(body: String, name: String): Long? {
        val match = Regex(key(name) + "(-?\\d{1,18})(?![\\d.eE])").find(body) ?: return null
        return match.groupValues[1].toLongOrNull()
    }

    fun unescape(raw: String): String {
        val out = StringBuilder(raw.length)
        var i = 0
        while (i < raw.length) {
            val c = raw[i]
            if (c != '\\' || i + 1 >= raw.length) {
                out.append(c)
                i++
                continue
            }
            when (val e = raw[i + 1]) {
                'n' -> out.append('\n')
                't' -> out.append('\t')
                'r' -> out.append('\r')
                'b' -> out.append('\b')
                'f' -> out.append('\u000C')
                'u' -> {
                    val hex = raw.substring(i + 2, minOf(i + 6, raw.length))
                    val code = if (hex.length == 4) hex.toIntOrNull(16) else null
                    if (code == null) {
                        out.append("\\u")
                    } else {
                        out.append(code.toChar())
                        i += 4
                    }
                }
                else -> out.append(e) // \" \\ \/
            }
            i += 2
        }
        return out.toString()
    }
}
