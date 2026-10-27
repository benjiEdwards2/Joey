package net.joeyhome.media.policy

import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/** JY-057 review: the Jellyfin token reaches the Jellyfin origin only, redirects included (two real local servers). */
class PlayerHttpTest {
    private val auth = "MediaBrowser Client=\"Joey\", Device=\"Joey player tv\", DeviceId=\"d\", Version=\"0.1.0\", Token=\"t0k\""
    private lateinit var jellyfin: MockWebServer
    private lateinit var other: MockWebServer

    @Before
    fun up() {
        jellyfin = MockWebServer().apply { start() }
        other = MockWebServer().apply { start() }
    }

    @After
    fun down() {
        jellyfin.shutdown()
        other.shutdown()
    }

    private fun origin(server: MockWebServer) = Origin.of(server.url("/").toString())!!
    private fun client() = PlayerHttp.client(origin(jellyfin), auth, 2_000, 2_000)

    @Test
    fun theJellyfinOriginGetsTheHeader() {
        jellyfin.enqueue(MockResponse().setBody("ok"))
        client().newCall(Request.Builder().url(jellyfin.url("/Videos/x/stream")).build()).execute().use {
            assertEquals(200, it.code)
        }
        assertEquals(auth, jellyfin.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
    }

    @Test
    fun aRedirectToAnotherHostIsNeverFollowed() {
        jellyfin.enqueue(MockResponse().setResponseCode(302).setHeader("Location", other.url("/steal").toString()))
        other.enqueue(MockResponse().setBody("x"))
        client().newCall(Request.Builder().url(jellyfin.url("/Videos/x/stream")).build()).execute().use {
            assertEquals(302, it.code)
        }
        assertEquals(1, jellyfin.requestCount)
        assertEquals(0, other.requestCount)
        assertNull(other.takeRequest(300, TimeUnit.MILLISECONDS))
    }

    // 2026-10-28 TV re-check: replaces aSameHostRedirectIsNotFollowedEither; a redirect inside the Jellyfin origin is
    // followed (header kept), so a playlist or segment that bounces inside Jellyfin still loads
    @Test
    fun aRedirectInsideTheJellyfinOriginIsFollowedWithTheHeader() {
        jellyfin.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "/videos/x/main.m3u8?a=1"))
        jellyfin.enqueue(MockResponse().setBody("#EXTM3U"))
        client().newCall(Request.Builder().url(jellyfin.url("/videos/x/master.m3u8")).build()).execute().use {
            assertEquals(200, it.code)
            assertEquals("#EXTM3U", it.body!!.string())
        }
        assertEquals(auth, jellyfin.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        val second = jellyfin.takeRequest(2, TimeUnit.SECONDS)!!
        assertEquals("/videos/x/main.m3u8?a=1", second.path)
        assertEquals(auth, second.getHeader("Authorization"))
    }

    @Test
    fun redirectsStopAfterFiveHops() {
        repeat(7) { jellyfin.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "/loop")) }
        client().newCall(Request.Builder().url(jellyfin.url("/loop")).build()).execute().use { assertEquals(302, it.code) }
        assertEquals(1 + PlayerHttp.MAX_HOPS, jellyfin.requestCount)
    }

    @Test
    fun aJellyfinHlsTranscodeChainLoadsEveryPlaylistAndSegmentWithTheHeader() {
        // The shapes Jellyfin 10.x emits: the hub's /videos/{id}/master.m3u8?..., a relative main.m3u8?..., relative
        // hls1/main/N.ts?... segments (and an fMP4 init map). Every one is on the Jellyfin origin and gets the header.
        val id = "dcd12e5bf6856e60c225472186cd6cb6"
        val q = "DeviceId=d&MediaSourceId=src1&PlaySessionId=ps1&VideoCodec=h264&AudioCodec=aac&TranscodeReasons=AudioCodecNotSupported"
        jellyfin.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
            override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest): MockResponse {
                val path = request.path.orEmpty()
                return when {
                    path.startsWith("/videos/$id/master.m3u8") -> MockResponse().setBody(
                        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000,CODECS=\"avc1.640028,mp4a.40.2\"\nmain.m3u8?$q\n")
                    path.startsWith("/videos/$id/main.m3u8") -> MockResponse().setBody(
                        "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:6\n" +
                            "#EXT-X-MAP:URI=\"hls1/main/-1.mp4?$q\"\n" +
                            "#EXTINF:6.0,\nhls1/main/0.ts?$q&runtimeTicks=0&actualSegmentLengthTicks=60000000\n" +
                            "#EXTINF:6.0,\nhls1/main/1.ts?$q&runtimeTicks=60000000&actualSegmentLengthTicks=60000000\n" +
                            "#EXT-X-ENDLIST\n")
                    path.startsWith("/videos/$id/hls1/main/") -> MockResponse().setBody("segment")
                    else -> MockResponse().setResponseCode(404)
                }
            }
        }
        val c = client()
        fun get(url: okhttp3.HttpUrl): String = c.newCall(Request.Builder().url(url).build()).execute().use {
            assertEquals("$url", 200, it.code)
            it.body!!.string()
        }
        val master = jellyfin.url("/videos/$id/master.m3u8?$q")
        val variant = master.resolve(get(master).lines().first { it.startsWith("main.m3u8") })!!
        val media = get(variant).lines()
        val uris = media.filter { it.startsWith("hls1/") } +
            media.filter { it.startsWith("#EXT-X-MAP") }.map { it.substringAfter("URI=\"").substringBefore('"') }
        assertEquals(3, uris.size)
        for (u in uris) assertEquals("segment", get(variant.resolve(u)!!))
        repeat(5) {
            val r = jellyfin.takeRequest(2, TimeUnit.SECONDS)!!
            assertEquals(r.path, auth, r.getHeader("Authorization"))
        }
    }

    @Test
    fun anotherOriginNeverGetsTheHeaderEvenIfACallerSetsIt() {
        other.enqueue(MockResponse().setBody("x"))
        other.enqueue(MockResponse().setBody("x"))
        val c = client()
        c.newCall(Request.Builder().url(other.url("/sub.vtt")).build()).execute().close()
        c.newCall(Request.Builder().url(other.url("/sub.vtt")).header("Authorization", auth).build()).execute().close()
        assertNull(other.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        assertNull(other.takeRequest(2, TimeUnit.SECONDS)!!.getHeader("Authorization"))
    }

    @Test
    fun redirectsAreOffInTheClient() {
        val c = client()
        assertFalse(c.followRedirects)
        assertFalse(c.followSslRedirects)
    }
}
