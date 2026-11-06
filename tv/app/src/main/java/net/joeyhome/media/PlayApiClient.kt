package net.joeyhome.media

import android.webkit.CookieManager
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import net.joeyhome.media.policy.Origin

/**
 * JY-057: the shell's calls to the hub's playback API (docs/playback-contract.md) on the Joey Media front. Each call
 * carries the WebView's own cookies for the UI host (read from CookieManager per call, never kept), the UI origin as
 * `Origin` (the hub's same-origin guard) and the shell's user agent. Blocking: call it off the main thread. Nothing is
 * logged: no URL, cookie or body.
 */
class PlayApiClient(private val ui: Origin, private val userAgent: String) {

    /** [status] 0 = no answer (a network error); [body] is at most [MAX_BODY] characters. */
    class Answer(val status: Int, val body: String?)

    fun post(path: String, json: String?): Answer = request("POST", path, json)

    /**
     * JY-307 P5: one image from the hub's /img proxy (the up-next still), same cookies and no redirects; the bytes on a
     * 200 image answer of at most [MAX_IMAGE] bytes, else null. Blocking: call it off the main thread.
     */
    fun image(path: String): ByteArray? {
        val base = ui.toString()
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
                connectTimeout = CONNECT_MS
                readTimeout = IMAGE_READ_MS
                instanceFollowRedirects = false
                setRequestProperty("User-Agent", userAgent)
                setRequestProperty("Accept", "image/*")
                CookieManager.getInstance().getCookie(base)?.takeIf { it.isNotBlank() }?.let { setRequestProperty("Cookie", it) }
            }
            if (conn.responseCode != 200 || conn.contentType?.startsWith("image/") != true) return null
            conn.inputStream.use { input ->
                val out = java.io.ByteArrayOutputStream()
                val buf = ByteArray(16 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    if (out.size() > MAX_IMAGE) return null
                }
                out.toByteArray()
            }
        } catch (e: IOException) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun request(method: String, path: String, json: String?): Answer {
        val base = ui.toString()
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = CONNECT_MS
                readTimeout = READ_MS
                instanceFollowRedirects = false   // a sign-in redirect is a refusal, never followed
                useCaches = false
                setRequestProperty("User-Agent", userAgent)
                setRequestProperty("Origin", base)
                setRequestProperty("Accept", "application/json")
                CookieManager.getInstance().getCookie(base)?.takeIf { it.isNotBlank() }?.let { setRequestProperty("Cookie", it) }
                if (json != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
            }
            if (json != null) conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { r ->
                val buf = CharArray(MAX_BODY)
                var n = 0
                while (n < MAX_BODY) {
                    val read = r.read(buf, n, MAX_BODY - n)
                    if (read < 0) break
                    n += read
                }
                String(buf, 0, n)
            }
            Answer(status, body)
        } catch (e: IOException) {
            Answer(0, null)
        } finally {
            conn?.disconnect()
        }
    }

    private companion object {
        const val CONNECT_MS = 5_000
        const val READ_MS = 15_000     // a start may wait on Jellyfin twice (the resume read, PlaybackInfo): ~10 s worst case
        const val MAX_BODY = 256 * 1024
        const val IMAGE_READ_MS = 5_000
        const val MAX_IMAGE = 2 * 1024 * 1024
    }
}
