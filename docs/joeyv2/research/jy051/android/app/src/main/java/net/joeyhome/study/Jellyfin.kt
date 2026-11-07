package net.joeyhome.study

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Minimal Jellyfin client acting as joeytest (signed in on the TV by B.). Reads (GET /Items, POST PlaybackInfo) plus
 * joeytest's own sign-in / sign-out, playback reports (resume mode) and stopping its own transcode job. Blocking: call off the
 * main thread. Never logs a URL or the token.
 */
class Jellyfin(private val base: String, private val token: String, private val deviceId: String) {
    val auth: String
        get() = "MediaBrowser Client=\"Joey Study\", Device=\"TV\", DeviceId=\"$deviceId\", Version=\"0.1.0\"" +
            (if (token.isEmpty()) "" else ", Token=\"$token\"")

    fun get(path: String): JSONObject = call("GET", path, null)
    fun post(path: String, body: JSONObject): JSONObject = call("POST", path, body)
    fun delete(path: String) {
        call("DELETE", path, null)
    }

    fun url(path: String): String = base + path

    private fun call(method: String, path: String, body: JSONObject?): JSONObject {
        val c = URL(base + path).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = 15_000
            c.readTimeout = 60_000
            c.setRequestProperty("Authorization", auth)
            c.setRequestProperty("Accept", "application/json")
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            if (code !in 200..299) throw IOException("HTTP $code")
            val text = c.inputStream.bufferedReader().use { it.readText() }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            c.disconnect()
        }
    }

    /** First MediaSource of an item: id and streams. Throws if the item has no probed audio + video (a probe writes). */
    fun facts(itemId: String): Pair<String, List<StreamFact>> {
        val res = get("/Items?Ids=$itemId&Fields=MediaSources,MediaStreams&EnableImages=false&EnableUserData=false")
        val item = res.optJSONArray("Items")?.optJSONObject(0) ?: throw IOException("item not found")
        val src = item.optJSONArray("MediaSources")?.optJSONObject(0) ?: throw IOException("no media source")
        val arr = src.optJSONArray("MediaStreams") ?: JSONArray()
        val streams = (0 until arr.length()).map { i ->
            val s = arr.getJSONObject(i)
            StreamFact(s.optInt("Index", -1), s.optString("Type"), s.optString("Codec").lowercase(), s.optBoolean("IsExternal"))
        }
        if (streams.none { it.type == "Video" } || streams.none { it.type == "Audio" }) {
            throw IOException("no probed streams (skipped, a probe would write)")
        }
        return src.optString("Id", itemId) to streams
    }

    companion object {
        /**
         * Jellyfin AuthenticateByName with what B. typed: (session token, user id). Nothing is stored or logged; the
         * caller keeps the token in memory and signs out (POST /Sessions/Logout) at the end.
         */
        fun authenticate(base: String, deviceId: String, user: String, password: String): Pair<String, String> {
            val anon = Jellyfin(base, "", deviceId)
            val res = anon.post("/Users/AuthenticateByName", JSONObject().put("Username", user).put("Pw", password))
            val tok = res.optString("AccessToken", "")
            val uid = res.optJSONObject("User")?.optString("Id", "") ?: ""
            if (tok.isEmpty() || uid.isEmpty()) throw IOException("no session in the answer")
            return tok to uid
        }

        /** DeviceProfile for T2H: ExoPlayer on Jellyfin HLS (fMP4), the device's decoders plus the FFmpeg audio. */
        fun hlsProfile(videoCodecs: List<String>, audioCodecs: List<String>): JSONObject {
            val v = videoCodecs.filter { it == "hevc" || it == "h264" }.ifEmpty { listOf("h264") }.joinToString(",")
            val a = (listOf("aac") + audioCodecs.filter { it == "ac3" || it == "eac3" }).distinct().joinToString(",")
            val transcoding = JSONArray().put(
                JSONObject().put("Container", "mp4").put("Type", "Video").put("VideoCodec", v).put("AudioCodec", a)
                    .put("Context", "Streaming").put("Protocol", "hls").put("MaxAudioChannels", "6")
                    .put("MinSegments", "1").put("BreakOnNonKeyFrames", true),
            )
            val subs = JSONArray()
            for (f in listOf("srt", "subrip")) subs.put(JSONObject().put("Format", f).put("Method", "External"))
            val codecProfiles = JSONArray().put(
                JSONObject().put("Type", "VideoAudio").put("Conditions", JSONArray().put(
                    JSONObject().put("Condition", "LessThanEqual").put("Property", "AudioChannels").put("Value", "6")
                        .put("IsRequired", false),
                )),
            )
            return JSONObject().put("Name", "JY-051 study: TV ExoPlayer HLS")
                .put("MaxStreamingBitrate", 120_000_000).put("MaxStaticBitrate", 100_000_000)
                .put("DirectPlayProfiles", JSONArray()).put("TranscodingProfiles", transcoding)
                .put("ContainerProfiles", JSONArray()).put("CodecProfiles", codecProfiles)
                .put("SubtitleProfiles", subs).put("ResponseProfiles", JSONArray())
        }

        fun hlsBody(userId: String, profile: JSONObject, item: TestItem, msid: String): JSONObject {
            val b = JSONObject().put("UserId", userId).put("DeviceProfile", profile)
                .put("MaxStreamingBitrate", 120_000_000).put("StartTimeTicks", 0).put("MediaSourceId", msid)
                .put("EnableDirectPlay", false).put("EnableDirectStream", false).put("EnableTranscoding", true)
                .put("AllowVideoStreamCopy", true).put("AllowAudioStreamCopy", true).put("AutoOpenLiveStream", false)
            item.audio?.let { b.put("AudioStreamIndex", it) }
            item.sub?.let { b.put("SubtitleStreamIndex", it) }
            return b
        }
    }
}
