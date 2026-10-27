package net.joeyhome.media.policy

import org.json.JSONArray
import org.json.JSONObject

/** One audio or subtitle track as the start answer lists it (contract endpoint 5's shape). */
data class PlayTrack(
    val index: Int,
    val audio: Boolean,
    val title: String?,
    val language: String?,
    val codec: String?,
    val isDefault: Boolean,
    val forced: Boolean,
    val external: Boolean,
    val text: Boolean,
    val delivery: String?,
    val url: String?,
)

data class Chapter(val name: String, val startMs: Long)

/** JY-057's additive `up_next`: the next aired episode, from the hub's cache. */
data class UpNext(val itemId: String, val label: String, val runtime: String?)

data class StartAnswer(
    val sessionId: String,
    val itemId: String,
    val playMethod: String,
    val runtimeMs: Long?,
    val startMs: Long,
    val audioIndex: Int?,
    val subtitleIndex: Int,
    val audio: List<PlayTrack>,
    val subtitles: List<PlayTrack>,
    val heartbeatS: Int,
    val resumed: Boolean,
    val chapters: List<Chapter>,
    val upNext: UpNext?,
)

/** The stream hand-out. [authorization] is the member's full Jellyfin token: memory only, never printed. */
class StreamAnswer(val url: String, val hls: Boolean, val playMethod: String, val authorization: String) {
    override fun toString(): String = "StreamAnswer(hls=$hls, playMethod=$playMethod)"
}

/** A refusal in the contract's one error shape; [code] is null for anything else (the media front's 404 page, a 303). */
data class ApiError(val status: Int, val code: String?, val retry: Boolean)

object Ticks {
    private const val PER_MS = 10_000L
    fun toMs(ticks: Long): Long = ticks / PER_MS
    fun fromMs(ms: Long): Long = ms * PER_MS
}

/**
 * The shell's side of docs/playback-contract.md (JY-053), kind `tv`. Every answer is checked before use: a start answer
 * needs a server-made session id, a Jellyfin item id and a known play method; a stream answer's URL must be on the
 * Jellyfin origin the shell already trusts (the :8443 edge), carry no key, and come with a `MediaBrowser ... Token=`
 * header, else the player falls back to the Jellyfin app.
 */
object PlayerApi {
    const val START_PATH = "/api/play/sessions"
    val METHODS = setOf("direct", "remux", "transcode")
    private val SESSION_ID = Regex("^[A-Za-z0-9_-]{8,64}$")
    private val ITEM_ID = Regex("^[0-9a-f]{32}$")
    private val TAILS = setOf("stream", "progress", "stop")
    /** `ApiKey` / `api_key`, compared without underscores (so no key-shaped literal sits in the APK: tv_version.py scan). */
    private const val KEY_PARAM = "apikey"

    fun sessionPath(sessionId: String, tail: String): String? =
        if (SESSION_ID.matches(sessionId) && tail in TAILS) "$START_PATH/$sessionId/$tail" else null

    fun startBody(itemId: String, profile: JSONObject, startMs: Long?, audioIndex: Int?, subtitleIndex: Int?, resume: Boolean): String {
        val body = JSONObject()
            .put("item_id", itemId)
            .put("device", JSONObject().put("kind", "tv").put("profile", profile))
            .put("resume", resume)
        startMs?.let { body.put("start_ticks", Ticks.fromMs(it.coerceAtLeast(0L))) }
        audioIndex?.let { body.put("audio_index", it) }
        subtitleIndex?.let { body.put("subtitle_index", it) }
        return body.toString()
    }

    fun progressBody(positionMs: Long, paused: Boolean): String =
        JSONObject().put("position_ticks", Ticks.fromMs(positionMs.coerceAtLeast(0L))).put("paused", paused).toString()

    fun stopBody(positionMs: Long): String =
        JSONObject().put("position_ticks", Ticks.fromMs(positionMs.coerceAtLeast(0L))).toString()

    fun parseStart(body: String?): StartAnswer? {
        val o = obj(body) ?: return null
        val sid = str(o, "session_id")?.takeIf { SESSION_ID.matches(it) } ?: return null
        val item = str(o, "item_id")?.takeIf { ITEM_ID.matches(it) } ?: return null
        val method = str(o, "play_method")?.takeIf { it in METHODS } ?: return null
        val tracks = o.optJSONObject("tracks")
        return StartAnswer(
            sessionId = sid,
            itemId = item,
            playMethod = method,
            runtimeMs = long(o, "runtime_ticks")?.takeIf { it > 0 }?.let { Ticks.toMs(it) },
            startMs = Ticks.toMs((long(o, "start_ticks") ?: 0L).coerceAtLeast(0L)),
            audioIndex = int(o, "audio_index"),
            subtitleIndex = int(o, "subtitle_index") ?: -1,
            audio = tracks(tracks?.optJSONArray("audio"), audio = true),
            subtitles = tracks(tracks?.optJSONArray("subtitles"), audio = false),
            heartbeatS = (int(o, "heartbeat_s") ?: 10).coerceIn(5, 60),
            resumed = o.optBoolean("resumed", false),
            chapters = chapters(o.optJSONArray("chapters")),
            upNext = o.optJSONObject("up_next")?.let { u ->
                val id = str(u, "item_id")?.takeIf { ITEM_ID.matches(it) }
                val label = str(u, "label")
                if (id != null && label != null) UpNext(id, label, str(u, "runtime")) else null
            },
        )
    }

    fun parseStream(body: String?, jellyfin: Origin): StreamAnswer? {
        val o = obj(body) ?: return null
        val url = str(o, "url") ?: return null
        if (Origin.of(url) != jellyfin || !url.startsWith(jellyfin.toString() + "/")) return null
        val query = Origin.parse(url)?.rawQuery.orEmpty()
        if (query.split('&').any { it.substringBefore('=').lowercase().replace("_", "") == KEY_PARAM }) return null
        val auth = o.optJSONObject("headers")?.let { str(it, "Authorization") } ?: return null
        if (!auth.startsWith("MediaBrowser ") || !auth.contains("Token=\"") || auth.any { it == '\r' || it == '\n' }) return null
        val method = str(o, "play_method")?.takeIf { it in METHODS } ?: "direct"
        return StreamAnswer(url, hls = str(o, "protocol") == "hls", playMethod = method, authorization = auth)
    }

    fun parseError(status: Int, body: String?): ApiError {
        val e = obj(body)?.optJSONObject("error") ?: return ApiError(status, null, false)
        return ApiError(status, str(e, "code"), e.optBoolean("retry", false))
    }

    // ---- small readers: a JSON null or a blank string is null ----

    private fun obj(body: String?): JSONObject? = try {
        body?.trim()?.takeIf { it.startsWith("{") }?.let { JSONObject(it) }
    } catch (e: Exception) {
        null
    }

    private fun str(o: JSONObject, key: String): String? =
        if (!o.has(key) || o.isNull(key)) null else o.optString(key, "").takeIf { it.isNotBlank() }

    private fun long(o: JSONObject, key: String): Long? {
        if (!o.has(key) || o.isNull(key)) return null
        val v = o.opt(key)
        return when (v) {
            is Int -> v.toLong()
            is Long -> v
            else -> null   // a fraction, a string or a huge number is not a contract integer
        }
    }

    private fun int(o: JSONObject, key: String): Int? = long(o, key)?.toInt()

    private fun tracks(list: JSONArray?, audio: Boolean): List<PlayTrack> {
        if (list == null) return emptyList()
        return (0 until list.length()).mapNotNull { i ->
            val t = list.optJSONObject(i) ?: return@mapNotNull null
            val index = int(t, "index") ?: return@mapNotNull null
            PlayTrack(
                index = index,
                audio = audio,
                title = str(t, "title"),
                language = str(t, "language"),
                codec = str(t, "codec"),
                isDefault = t.optBoolean("default", false),
                forced = t.optBoolean("forced", false),
                external = t.optBoolean("external", false),
                text = t.optBoolean("text", true),
                delivery = str(t, "delivery"),
                url = str(t, "url"),
            )
        }
    }

    private fun chapters(list: JSONArray?): List<Chapter> {
        if (list == null) return emptyList()
        return (0 until list.length()).mapNotNull { i ->
            val c = list.optJSONObject(i) ?: return@mapNotNull null
            val start = long(c, "start_ticks")?.takeIf { it >= 0 } ?: return@mapNotNull null
            Chapter(str(c, "name").orEmpty(), Ticks.toMs(start))
        }.sortedBy { it.startMs }
    }
}
