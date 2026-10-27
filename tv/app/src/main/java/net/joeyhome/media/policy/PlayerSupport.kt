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
 * HLS (fMP4, as the JY-051 study's T2H) for the rest. No FFmpeg extension (JY-057 Question 1): DTS and TrueHD are
 * listed only when an output takes them as passthrough, else Jellyfin transcodes the audio.
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

    /** The codecs a listed decoder is not trusted for: only an output that takes the bitstream (passthrough) counts. */
    private val PASSTHROUGH_ONLY = setOf("dts", "truehd")

    /** android.media.AudioFormat encodings an output may report (AudioDeviceInfo.getEncodings) -> Jellyfin codec. */
    private val ENCODINGS = mapOf(5 to "ac3", 6 to "eac3", 18 to "eac3", 7 to "dts", 8 to "dts", 14 to "truehd")

    /**
     * Jellyfin audio codec names this TV can really play (JY-057 TV session, 2026-10-27: the TCL lists a DTS decoder but
     * stalls on DTS). AAC, MP3, Opus, FLAC and Vorbis come from the decoders; AC-3 and E-AC-3 from a decoder or an
     * output that takes them as passthrough; DTS and TrueHD only from passthrough, whatever the decoder list says.
     * Anything left out is converted by Jellyfin (remux with the audio transcoded). aac when nothing is known.
     */
    fun audioCodecs(decoderMimes: Set<String>, passthroughEncodings: Set<Int> = emptySet()): List<String> {
        val passthrough = passthroughEncodings.mapNotNull { ENCODINGS[it] }.toSet()
        return AUDIO.filter { (name, list) ->
            name in passthrough || (name !in PASSTHROUGH_ONLY && list.any { it in decoderMimes })
        }.keys.toList().ifEmpty { listOf("aac") }
    }

    fun build(video: List<String>, audio: List<String>): JSONObject {
        val hlsVideo = listOf("hevc", "h264").filter { it in video }.ifEmpty { listOf("h264") }
        val hlsAudio = (listOf("aac") + listOf("ac3", "eac3").filter { it in audio }).distinct()
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
            .put("TranscodingProfiles", JSONArray().put(JSONObject()
                .put("Container", "mp4").put("Type", "Video").put("VideoCodec", hlsVideo.joinToString(","))
                .put("AudioCodec", hlsAudio.joinToString(",")).put("Context", "Streaming").put("Protocol", "hls")
                .put("MaxAudioChannels", "6").put("MinSegments", "1").put("BreakOnNonKeyFrames", true)))
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
