package net.joeyhome.media.policy

import java.util.Locale
import org.json.JSONArray
import org.json.JSONObject

enum class StartStep { RETRY, HAND_OFF }

enum class ProgressStep { IGNORE, RESTART }

/**
 * JY-050 Q7 A: the Jellyfin app stays the fallback for this release. A start that cannot reach a first frame hands the
 * same item to the Jellyfin app (WP-B6 route 1b), after one retry for a network error or a retryable 502 / 504.
 */
object PlayerFallback {
    private val RETRYABLE = setOf(502, 504)

    /** [error] null = no answer at all (a network error); [attempt] counts from 0. */
    fun afterStartFailure(error: ApiError?, attempt: Int): StartStep {
        if (attempt > 0) return StartStep.HAND_OFF
        if (error == null || (error.retry && error.status in RETRYABLE)) return StartStep.RETRY
        return StartStep.HAND_OFF
    }

    /** Contract endpoint 3: a failed heartbeat is not fatal; a forgotten session starts a new one at the position. */
    fun afterProgressFailure(error: ApiError?): ProgressStep =
        if (error?.status == 404 && error.code == "session_unknown") ProgressStep.RESTART else ProgressStep.IGNORE
}

enum class SwitchWay { IN_PLAYER, RESTART }

sealed interface TextPick {
    data object Off : TextPick
    /** The n-th subtitle the file itself carries (ExoPlayer lists them in container order). */
    data class Embedded(val ordinal: Int) : TextPick
    /** A side-loaded subtitle, matched by the id the player gave its SubtitleConfiguration. */
    data class External(val id: String) : TextPick
    /** A subtitle rendition inside Jellyfin's HLS stream. */
    data object InStream : TextPick
}

/** [audioOrdinal] null = leave audio as the stream has it. */
data class TrackSelection(val audioOrdinal: Int?, val text: TextPick)

/**
 * Tracks on the TV (contract endpoint 5). Direct play: the file holds every track, so a pick switches inside the player
 * (the n-th embedded track of that type, or a side-loaded external subtitle). Remux / transcode: Jellyfin bakes the
 * audio and subtitle into the stream, so a pick stops the session and starts a new one at the position (the contract's
 * way); then only the delivered subtitle is selected.
 */
object TrackPlan {
    fun externalId(index: Int) = "joey-sub-$index"

    fun way(playMethod: String): SwitchWay = if (playMethod == "direct") SwitchWay.IN_PLAYER else SwitchWay.RESTART

    fun selection(playMethod: String, audio: List<PlayTrack>, subtitles: List<PlayTrack>, audioIndex: Int?, subtitleIndex: Int): TrackSelection {
        val direct = playMethod == "direct"
        val audioOrdinal = if (direct && audioIndex != null) ordinal(audio, audioIndex) else null
        val sub = subtitles.firstOrNull { it.index == subtitleIndex }.takeIf { subtitleIndex >= 0 }
        val text = when {
            sub == null -> TextPick.Off
            sub.delivery == "external" && sub.url != null -> TextPick.External(externalId(sub.index))
            direct && !sub.external -> ordinal(subtitles, sub.index)?.let { TextPick.Embedded(it) } ?: TextPick.Off
            sub.delivery == "hls" -> TextPick.InStream
            else -> TextPick.Off   // burned in by Jellyfin ("encode"): nothing to select
        }
        return TrackSelection(audioOrdinal, text)
    }

    /** External subtitles the player side-loads: a URL on the Jellyfin origin only (the header goes nowhere else). */
    fun sideloads(subtitles: List<PlayTrack>, jellyfin: Origin): List<PlayTrack> =
        subtitles.filter { it.delivery == "external" && it.url != null && Origin.of(it.url) == jellyfin }

    fun subtitleMime(url: String): String = when (url.substringBefore('?').substringAfterLast('.').lowercase(Locale.ROOT)) {
        "srt" -> "application/x-subrip"
        "ass", "ssa" -> "text/x-ssa"
        else -> "text/vtt"
    }

    private fun ordinal(tracks: List<PlayTrack>, index: Int): Int? {
        val own = tracks.filter { !it.external }.sortedBy { it.index }
        return own.indexOfFirst { it.index == index }.takeIf { it >= 0 }
    }
}

/**
 * The Jellyfin DeviceProfile the TV sends with each start: direct play for what this TV's decoders take, Jellyfin's
 * HLS for the rest (MPEG-TS first, then fMP4, as Jellyfin's own ExoPlayer TV app asks). No FFmpeg extension (JY-057 Question 1): DTS and TrueHD are
 * never listed, so Jellyfin transcodes that audio.
 */
object DeviceProfile {
    private val VIDEO = linkedMapOf("h264" to "video/avc", "hevc" to "video/hevc", "av1" to "video/av01", "vp9" to "video/x-vnd.on2.vp9")
    private val AUDIO = linkedMapOf(
        "aac" to listOf("audio/mp4a-latm"), "mp3" to listOf("audio/mpeg"), "ac3" to listOf("audio/ac3"),
        "eac3" to listOf("audio/eac3", "audio/eac3-joc"), "opus" to listOf("audio/opus"), "flac" to listOf("audio/flac"),
        "vorbis" to listOf("audio/vorbis"), "dts" to listOf("audio/vnd.dts", "audio/vnd.dts.hd"),
        "truehd" to listOf("audio/true-hd"),
    )
    private const val CONTAINERS = "mkv,mp4,m4v,mov,webm,ts,m2ts"
    private val EMBED = listOf("srt", "subrip", "ass", "ssa", "vtt", "webvtt", "mov_text", "ttml", "pgssub", "dvdsub", "dvbsub")
    private val EXTERNAL = listOf("vtt", "srt")
    private const val MAX_BITRATE = 120_000_000

    /** Jellyfin video codec names for the TV's decoder MIME types; h264 when none is known. */
    fun videoCodecs(mimes: Set<String>): List<String> =
        VIDEO.filter { (_, mime) -> mime in mimes }.keys.toList().ifEmpty { listOf("h264") }

    /** Never declared, whatever a decoder list or an audio output claims (Jellyfin converts them server-side). */
    private val NEVER = setOf("dts", "truehd")

    /**
     * Jellyfin audio codec names this TV plays: those its decoders list, never DTS or TrueHD. TV sessions, 2026-10-27/28:
     * the TCL lists a DTS decoder and stalled on it, then reported an HDMI / ARC output claiming DTS and failed at once.
     * B.'s choice (ExoPlayer without FFmpeg, conversion on the server) makes the rule simple: Jellyfin converts DTS and
     * TrueHD audio, and the meta says Transcode. aac when nothing is known.
     */
    fun audioCodecs(decoderMimes: Set<String>): List<String> =
        AUDIO.filter { (name, list) -> name !in NEVER && list.any { it in decoderMimes } }.keys.toList().ifEmpty { listOf("aac") }

    fun build(video: List<String>, audio: List<String>): JSONObject {
        val hlsVideo = listOf("hevc", "h264").filter { it in video }.ifEmpty { listOf("h264") }
        val hlsAudio = (listOf("aac") + listOf("ac3", "eac3", "mp3").filter { it in audio }).distinct()
        // TV re-check 2026-10-28 (row 9): the fMP4 HLS this profile asked for (with BreakOnNonKeyFrames) failed in
        // Media3's HLS loader (UnexpectedLoaderException < IllegalStateException). Now the shape Jellyfin's own ExoPlayer
        // TV app sends (jellyfin-androidtv deviceProfile.kt): MPEG-TS HLS first, fMP4 second, CopyTimestamps off,
        // subtitles in the manifest, no BreakOnNonKeyFrames.
        fun hls(container: String) = JSONObject()
            .put("Container", container).put("Type", "Video").put("VideoCodec", hlsVideo.joinToString(","))
            .put("AudioCodec", hlsAudio.joinToString(",")).put("Context", "Streaming").put("Protocol", "hls")
            .put("MaxAudioChannels", "6").put("CopyTimestamps", false).put("EnableSubtitlesInManifest", true)
        val subs = JSONArray()
        EMBED.forEach { subs.put(JSONObject().put("Format", it).put("Method", "Embed")) }
        EXTERNAL.forEach { subs.put(JSONObject().put("Format", it).put("Method", "External")) }
        return JSONObject()
            .put("Name", "Joey TV")
            .put("MaxStreamingBitrate", MAX_BITRATE)
            .put("MaxStaticBitrate", MAX_BITRATE)
            .put("DirectPlayProfiles", JSONArray().put(JSONObject()
                .put("Container", CONTAINERS).put("Type", "Video")
                .put("VideoCodec", video.joinToString(",")).put("AudioCodec", audio.joinToString(","))))
            .put("TranscodingProfiles", JSONArray().put(hls("ts")).put(hls("mp4")))
            .put("ContainerProfiles", JSONArray())
            .put("CodecProfiles", JSONArray())
            .put("ResponseProfiles", JSONArray())
            .put("SubtitleProfiles", subs)
    }
}

/** The player's words (look A), in Joey's plain style. */
object PlayerText {
    fun time(ms: Long): String {
        val total = ms.coerceAtLeast(0L) / 1_000L
        val h = total / 3_600
        val m = (total % 3_600) / 60
        val s = total % 60
        return if (h > 0) String.format(Locale.ROOT, "%d:%02d:%02d", h, m, s) else String.format(Locale.ROOT, "%d:%02d", m, s)
    }

    fun progress(positionMs: Long, durationMs: Long): String =
        if (durationMs > 0) "${time(positionMs)} / ${time(durationMs)}" else time(positionMs)

    fun method(playMethod: String): String = when (playMethod) {
        "direct" -> "Direct play"
        "remux" -> "Remux"
        else -> "Transcode"
    }

    fun resumed(ms: Long) = "Resumed at ${time(ms)}"

    fun firstFrame(ms: Long) = String.format(Locale.ROOT, "First frame %.1f s after Play", ms.coerceAtLeast(0L) / 1_000.0)

    fun countdown(seconds: Int) = "Next episode in $seconds s"

    /** "Ch 4 of 6 · The Breakwater" for the chapter playing at [positionMs], or null without chapters. */
    fun chapter(chapters: List<Chapter>, positionMs: Long): String? {
        if (chapters.isEmpty()) return null
        val at = chapters.indexOfLast { it.startMs <= positionMs }.coerceAtLeast(0)
        val name = chapters[at].name.trim()
        val head = "Ch ${at + 1} of ${chapters.size}"
        return if (name.isEmpty()) head else "$head · $name"
    }

    fun track(t: PlayTrack): String =
        t.title?.trim()?.takeIf { it.isNotEmpty() }
            ?: t.language?.trim()?.takeIf { it.isNotEmpty() }?.uppercase(Locale.ROOT)
            ?: "Track ${t.index}"

    fun subtitleOff() = "Off"

    /** The title block's words: the Joey page's own title without its brand ("Library Film · Joey Media" → "Library Film"). */
    fun pageTitle(raw: String?): String {
        var text = raw?.trim().orEmpty()
        for (brand in listOf(" · Joey Media", " · Joey")) {
            if (text.endsWith(brand)) text = text.removeSuffix(brand).trim()
        }
        return if (text == "Joey Media" || text == "Joey" || text.startsWith("http")) "" else text
    }
}

/**
 * One log line saying why the player handed an item to the Jellyfin app (TV session 2026-10-28: the reason was not
 * visible). Words only: the stage, the HTTP status and the contract's error code, or the player's error name and cause
 * class names. Never a URL, a token or a title.
 */
object FallbackReason {
    private val SAFE = Regex("[^A-Za-z0-9_.]")

    private fun word(text: String?): String? = text?.replace(SAFE, "")?.take(48)?.takeIf { it.isNotEmpty() }

    fun start(stage: String, error: ApiError?, attempt: Int): String {
        val what = if (error == null) "no answer" else "HTTP ${error.status}" + (word(error.code)?.let { " $it" } ?: "")
        return "fallback: ${word(stage)} $what, attempt ${attempt + 1}"
    }

    fun player(errorName: String, httpStatus: Int?, causes: List<String>, playMethod: String?, hls: Boolean?): String {
        val parts = mutableListOf("fallback: player ${word(errorName) ?: "error"}")
        httpStatus?.let { parts += "HTTP $it" }
        causes.mapNotNull { word(it) }.take(3).takeIf { it.isNotEmpty() }?.let { parts += "cause ${it.joinToString(" < ")}" }
        word(playMethod)?.let { parts += "method $it" }
        hls?.let { parts += if (it) "hls" else "file" }
        return parts.joinToString(", ")
    }
}
