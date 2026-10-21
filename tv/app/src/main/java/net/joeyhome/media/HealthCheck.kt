package net.joeyhome.media

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import net.joeyhome.media.policy.HomePath
import net.joeyhome.media.policy.Origin

/**
 * Splash probe: GET `<ui>/healthz` (5 s timeouts). Reachable = HTTP 200. The `home` field feeds BackPolicy; without
 * it the `Location` of the `/` 303 is used. Blocking: call it off the main thread.
 */
object HealthCheck {
    private const val TIMEOUT_MS = 5_000
    private const val MAX_BODY = 64 * 1024

    data class Result(val reachable: Boolean, val homePath: String?)

    fun probe(ui: Origin, userAgent: String): Result {
        val base = ui.toString()
        val body = request("$base/healthz", userAgent) { conn ->
            if (conn.responseCode == 200) conn.inputStream.bufferedReader().use { it.readText().take(MAX_BODY) } else null
        } ?: return Result(reachable = false, homePath = null)
        val home = HomePath.fromHealthz(body) ?: HomePath.fromLocation(
            request("$base/", userAgent) { conn ->
                if (conn.responseCode in 300..399) conn.getHeaderField("Location") else null
            },
            ui,
        )
        return Result(reachable = true, homePath = home)
    }

    private fun <T> request(url: String, userAgent: String, read: (HttpURLConnection) -> T?): T? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                instanceFollowRedirects = false
                useCaches = false
                setRequestProperty("User-Agent", userAgent)
            }
            read(conn)
        } catch (e: IOException) {
            null
        } finally {
            conn?.disconnect()
        }
    }
}
