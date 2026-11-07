package net.joeyhome.study

import java.net.URLDecoder

/** One test file. [audio]/[sub] are Jellyfin MediaStream.Index values (null = server default / none). */
data class TestItem(val n: Int, val id: String, val audio: Int?, val sub: Int?)

/** One Jellyfin MediaStream, reduced to what the study needs. */
data class StreamFact(val index: Int, val type: String, val codec: String, val external: Boolean)

/** Pure study logic (JVM-tested in src/test). Same set as TEST_ITEMS in scripts/player_study.py (a pytest compares). */
object Study {
    val ITEMS: List<TestItem> = listOf(
        TestItem(1, "dcd12e5bf6856e60c225472186cd6cb6", null, null),
        TestItem(2, "d64f611c17a8d1e628dc0baf8625c536", null, 2),
        TestItem(3, "ff2240b0477c0f0e53772543e772988d", null, 2),
        TestItem(4, "8e272a6eab2388ea32b247333da9794a", null, 2),
        TestItem(5, "91c55b10825a46ea01cdf50ea760a6ea", null, null),
        TestItem(6, "2da3a189e2c7f9d7166cb63aeb849b23", null, 3),
        TestItem(7, "0fc19ee50e310c68987dd14714e824da", null, 5),
        TestItem(8, "fdbb56885c9e44e039ca5c0aa056d2d4", null, 0),
        TestItem(9, "910c6153145342b775e9fbaa911d11aa", null, 3),
        TestItem(10, "75bd8094149b87b7ea659542df28341f", 2, null),
        TestItem(11, "51a2003ebcbce12e58ae829bf58d7e58", null, null),
        TestItem(12, "b171da2503dbcb65d7e9aeffee75b9f0", null, 7),
    )

    val CONTAINER_ONLY = setOf("ContainerNotSupported", "DirectPlayError", "ContainerBitrateExceedsLimit_static")
    val AUDIO_REASONS = setOf(
        "AudioCodecNotSupported", "AudioChannelsNotSupported", "AudioProfileNotSupported",
        "AudioSampleRateNotSupported", "AudioBitDepthNotSupported", "AudioBitrateNotSupported", "AudioIsExternal",
        "SecondaryAudioNotSupported", "UnknownAudioStreamInfo",
    )

    /**
     * Position of stream [index] among the file's own (not external) streams of [type], in Jellyfin index order.
     * ExoPlayer lists a file's track groups in container order, so this is the group to select. -1 = not found
     * or external.
     */
    fun internalPosition(streams: List<StreamFact>, type: String, index: Int): Int {
        val own = streams.filter { it.type == type && !it.external }.sortedBy { it.index }
        return own.indexOfFirst { it.index == index }
    }

    fun isExternal(streams: List<StreamFact>, index: Int): Boolean =
        streams.any { it.index == index && it.type == "Subtitle" && it.external }

    /** Query values of a TranscodingUrl, lower-cased keys. The URL itself carries the token: never log it. */
    fun query(url: String): Map<String, String> {
        val q = url.substringAfter('?', "")
        val out = LinkedHashMap<String, String>()
        for (kv in q.split('&')) {
            if (kv.isEmpty()) continue
            val k = URLDecoder.decode(kv.substringBefore('='), "UTF-8").lowercase()
            val v = URLDecoder.decode(kv.substringAfter('=', ""), "UTF-8")
            out.putIfAbsent(k, v)
        }
        return out
    }

    /** Play method from a TranscodingUrl's TranscodeReasons; mirrors scripts/player_study.py decision(). */
    fun method(directPlay: Boolean, directStream: Boolean, transcodingUrl: String?): Pair<String, List<String>> {
        val reasons = transcodingUrl?.let { query(it)["transcodereasons"] }?.split(',')?.filter { it.isNotEmpty() }
            ?: emptyList()
        val rs = reasons.toSet()
        val m = when {
            directPlay -> "DirectPlay"
            directStream && transcodingUrl.isNullOrEmpty() -> "DirectStream"
            !transcodingUrl.isNullOrEmpty() -> when {
                rs.isNotEmpty() && CONTAINER_ONLY.containsAll(rs) -> "Remux"
                rs.isNotEmpty() && (CONTAINER_ONLY + AUDIO_REASONS).containsAll(rs) -> "Remux+Audio"
                else -> "Transcode"
            }
            else -> "None"
        }
        return m to reasons
    }

    /** Jellyfin codec names for the device's decoders (MediaCodec mime types); [ffmpeg] adds the extension's audio. */
    fun audioCodecs(mimes: Set<String>, ffmpeg: Boolean): List<String> {
        val map = linkedMapOf(
            "aac" to "audio/mp4a-latm", "mp3" to "audio/mpeg", "opus" to "audio/opus", "flac" to "audio/flac",
            "ac3" to "audio/ac3", "eac3" to "audio/eac3", "dts" to "audio/vnd.dts", "truehd" to "audio/true-hd",
        )
        val have = map.filter { (_, mime) -> mime in mimes }.keys.toMutableSet()
        if ("audio/vnd.dts.hd" in mimes) have += "dts"
        if (ffmpeg) have += listOf("mp3", "opus", "flac", "ac3", "eac3", "dts", "truehd")
        return map.keys.filter { it in have }
    }

    fun videoCodecs(mimes: Set<String>): List<String> {
        val map = linkedMapOf("h264" to "video/avc", "hevc" to "video/hevc", "av1" to "video/av01", "vp9" to "video/x-vnd.on2.vp9")
        return map.filter { (_, mime) -> mime in mimes }.keys.toList()
    }

    fun median(xs: List<Long>): Double? {
        if (xs.isEmpty()) return null
        val s = xs.sorted()
        val m = s.size / 2
        return if (s.size % 2 == 1) s[m].toDouble() else (s[m - 1] + s[m]) / 2.0
    }

    /** Text for logcat: the token and any URL removed, one line. */
    fun scrub(text: String, token: String): String {
        var t = if (token.isNotEmpty()) text.replace(token, "<token>") else text
        t = t.replace(Regex("https?://\\S+"), "<url>")
        return t.replace('\n', ' ')
    }
}
