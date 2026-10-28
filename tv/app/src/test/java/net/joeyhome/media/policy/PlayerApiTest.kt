package net.joeyhome.media.policy

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** JY-057: the shell's side of docs/playback-contract.md (JY-053), parsed without trusting the answer. */
class PlayerApiTest {
    private val jf = HostConfig.DEFAULT.jellyfin
    private val item = "dcd12e5bf6856e60c225472186cd6cb6"
    private val next = "e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3"
    private val sid = "Q2xhdWRlIHdhcyBoZXJl"

    private val start = """
        {"session_id": "$sid", "item_id": "$item", "play_method": "direct", "media_source_id": "src1",
         "container": "mkv", "runtime_ticks": 26400000000, "start_ticks": 14210000000, "audio_index": 1,
         "subtitle_index": -1, "heartbeat_s": 10, "stream": "/api/play/sessions/$sid/stream", "resumed": true,
         "tracks": {"audio": [{"index": 1, "language": "eng", "title": "English AAC 2.0", "codec": "aac", "default": true, "channels": 2},
                              {"index": 2, "language": "ita", "title": null, "codec": "eac3", "default": false, "channels": 6}],
                    "subtitles": [{"index": 3, "language": "eng", "title": "English SRT", "codec": "subrip", "default": false,
                                   "forced": false, "external": true, "text": true, "delivery": "external",
                                   "url": "https://jellyfin.joeyhome.net:8443/Videos/x/src1/Subtitles/3/0/Stream.vtt"},
                                  {"index": 4, "language": "eng", "title": "English PGS", "codec": "pgssub", "default": false,
                                   "forced": true, "external": false, "text": false, "delivery": "embed"}],
                    "default_audio_index": 1, "default_subtitle_index": -1},
         "chapters": [{"name": "Opening", "start_ticks": 0}, {"name": "The Breakwater", "start_ticks": 6000000000}],
         "up_next": {"item_id": "$next", "label": "S2 · E3 · The Breakwater", "runtime": "48m"}}
    """.trimIndent()

    @Test
    fun aStartAnswerParses() {
        val a = PlayerApi.parseStart(start)!!
        assertEquals(sid, a.sessionId)
        assertEquals(item, a.itemId)
        assertEquals("direct", a.playMethod)
        assertEquals(2_640_000L, a.runtimeMs)
        assertEquals(1_421_000L, a.startMs)
        assertEquals(1, a.audioIndex)
        assertEquals(-1, a.subtitleIndex)
        assertEquals(10, a.heartbeatS)
        assertTrue(a.resumed)
        assertEquals(listOf(1, 2), a.audio.map { it.index })
        assertEquals(listOf(3, 4), a.subtitles.map { it.index })
        assertNull(a.audio[1].title)
        assertTrue(a.subtitles[0].external && a.subtitles[0].text)
        assertFalse(a.subtitles[1].text)
        assertEquals("embed", a.subtitles[1].delivery)
        assertEquals(listOf(Chapter("Opening", 0L), Chapter("The Breakwater", 600_000L)), a.chapters)
        assertEquals(UpNext(next, "S2 · E3 · The Breakwater", "48m"), a.upNext)
    }

    @Test
    fun aMinimalAnswerHasSafeDefaults() {
        val a = PlayerApi.parseStart("""{"session_id": "$sid", "item_id": "$item", "play_method": "remux"}""")!!
        assertEquals(0L, a.startMs)
        assertNull(a.runtimeMs)
        assertNull(a.audioIndex)
        assertEquals(-1, a.subtitleIndex)
        assertEquals(10, a.heartbeatS)
        assertFalse(a.resumed)
        assertTrue(a.chapters.isEmpty() && a.audio.isEmpty() && a.subtitles.isEmpty())
        assertNull(a.upNext)
    }

    @Test
    fun aBrokenStartAnswerIsNull() {
        for (bad in listOf("", "not json", "[]", """{"item_id": "$item", "play_method": "direct"}""",
            """{"session_id": "$sid", "item_id": "nope", "play_method": "direct"}""",
            """{"session_id": "$sid", "item_id": "$item", "play_method": "teleport"}""",
            """{"session_id": "../../x", "item_id": "$item", "play_method": "direct"}""")) {
            assertNull(bad, PlayerApi.parseStart(bad))
        }
    }

    @Test
    fun aBadUpNextIsDroppedNotFatal() {
        val a = PlayerApi.parseStart("""{"session_id": "$sid", "item_id": "$item", "play_method": "direct",
            "up_next": {"item_id": "junk", "label": "x"}}""")!!
        assertNull(a.upNext)
    }

    @Test
    fun theHeartbeatIsKeptInARange() {
        fun hb(s: Int) = PlayerApi.parseStart("""{"session_id": "$sid", "item_id": "$item", "play_method": "direct", "heartbeat_s": $s}""")!!.heartbeatS
        assertEquals(5, hb(0))
        assertEquals(60, hb(3600))
        assertEquals(15, hb(15))
    }

    private val auth = "MediaBrowser Client=\"Joey\", Device=\"Joey player tv\", DeviceId=\"d\", Version=\"0.1.0\", Token=\"t0k\""

    private fun stream(url: String, protocol: String = "file", authorization: String = auth) =
        JSONObject().put("url", url).put("protocol", protocol).put("play_method", "direct")
            .put("headers", JSONObject().put("Authorization", authorization)).toString()

    @Test
    fun aStreamOnTheJellyfinOriginParses() {
        val s = PlayerApi.parseStream(stream("https://jellyfin.joeyhome.net:8443/Videos/$item/stream?static=true&mediaSourceId=src1"), jf)!!
        assertFalse(s.hls)
        assertEquals(auth, s.authorization)
        assertTrue(PlayerApi.parseStream(stream("https://jellyfin.joeyhome.net:8443/videos/$item/master.m3u8?x=1", "hls"), jf)!!.hls)
    }

    @Test
    fun aStreamOffTheJellyfinOriginOrWithAKeyIsRefused() {
        for (url in listOf("https://jellyfin.joeyhome.net/Videos/x/stream", "https://media.joeyhome.net/Videos/x/stream",
            "http://jellyfin.joeyhome.net:8443/Videos/x/stream", "https://evil.example:8443/Videos/x/stream",
            "https://jellyfin.joeyhome.net:8443/Videos/x/stream?api_key=leak",
            "https://jellyfin.joeyhome.net:8443/Videos/x/stream?ApiKey=leak", "/Videos/x/stream", "")) {
            assertNull(url, PlayerApi.parseStream(stream(url), jf))
        }
    }

    @Test
    fun aStreamWithoutTheMediaBrowserHeaderIsRefused() {
        val url = "https://jellyfin.joeyhome.net:8443/Videos/x/stream"
        assertNull(PlayerApi.parseStream(stream(url, authorization = "Bearer t0k"), jf))
        assertNull(PlayerApi.parseStream(stream(url, authorization = "MediaBrowser Client=\"Joey\""), jf))
        assertNull(PlayerApi.parseStream(stream(url, authorization = "$auth\r\nX-Evil: 1"), jf))
        assertNull(PlayerApi.parseStream("""{"url": "$url", "protocol": "file"}""", jf))
        assertNull(PlayerApi.parseStream("nope", jf))
    }

    @Test
    fun theStreamAnswerNeverPrintsTheHeader() {
        val s = PlayerApi.parseStream(stream("https://jellyfin.joeyhome.net:8443/Videos/x/stream"), jf)!!
        assertFalse(s.toString().contains("t0k"))
    }

    @Test
    fun errorsParseTheContractShape() {
        assertEquals(ApiError(504, "upstream_timeout", true),
            PlayerApi.parseError(504, """{"error": {"code": "upstream_timeout", "message": "x", "retry": true}}"""))
        assertEquals(ApiError(404, "session_unknown", false),
            PlayerApi.parseError(404, """{"error": {"code": "session_unknown", "message": "x"}}"""))
        assertEquals(ApiError(404, null, false), PlayerApi.parseError(404, "<html>Joey 404 page</html>"))
        assertEquals(ApiError(303, null, false), PlayerApi.parseError(303, null))
    }

    @Test
    fun requestBodiesFollowTheContract() {
        val profile = JSONObject().put("Name", "Joey TV")
        val body = JSONObject(PlayerApi.startBody(item, profile, startMs = null, audioIndex = null, subtitleIndex = null, resume = true))
        assertEquals(item, body.getString("item_id"))
        assertEquals("tv", body.getJSONObject("device").getString("kind"))
        assertEquals("Joey TV", body.getJSONObject("device").getJSONObject("profile").getString("Name"))
        assertTrue(body.getBoolean("resume"))
        assertFalse(body.has("start_ticks") || body.has("audio_index") || body.has("subtitle_index"))
        val restart = JSONObject(PlayerApi.startBody(item, profile, startMs = 61_500, audioIndex = 2, subtitleIndex = -1, resume = false))
        assertEquals(615_000_000L, restart.getLong("start_ticks"))
        assertEquals(2, restart.getInt("audio_index"))
        assertEquals(-1, restart.getInt("subtitle_index"))
        assertFalse(restart.getBoolean("resume"))
        val progress = JSONObject(PlayerApi.progressBody(1_500, paused = true))
        assertEquals(15_000_000L, progress.getLong("position_ticks"))
        assertTrue(progress.getBoolean("paused"))
        assertEquals(20_000_000L, JSONObject(PlayerApi.stopBody(2_000)).getLong("position_ticks"))
        assertEquals(0L, JSONObject(PlayerApi.stopBody(-5)).getLong("position_ticks"))
    }

    @Test
    fun sessionPathsOnlyTakeTheServersOwnIds() {
        assertEquals("/api/play/sessions/$sid/stream", PlayerApi.sessionPath(sid, "stream"))
        assertNull(PlayerApi.sessionPath("../x", "stream"))
        assertNull(PlayerApi.sessionPath(sid, "delete"))
        assertNotNull(PlayerApi.sessionPath(sid, "progress"))
        assertNotNull(PlayerApi.sessionPath(sid, "stop"))
    }

    @Test
    fun ticksAreTenThousandPerMillisecond() {
        assertEquals(1_000L, Ticks.toMs(10_000_000L))
        assertEquals(10_000_000L, Ticks.fromMs(1_000L))
    }
}
