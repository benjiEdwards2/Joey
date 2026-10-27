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

    @Test
    fun aSameHostRedirectIsNotFollowedEither() {
        jellyfin.enqueue(MockResponse().setResponseCode(301).setHeader("Location", jellyfin.url("/elsewhere").toString()))
        client().newCall(Request.Builder().url(jellyfin.url("/a")).build()).execute().use { assertEquals(301, it.code) }
        assertEquals(1, jellyfin.requestCount)
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
