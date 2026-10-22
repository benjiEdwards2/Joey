package net.joeyhome.media.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The version.json contract (deploy/tv_version.py writes it): integer min_version, relative url. */
class RemoteVersionTest {
    private val sha = "0123456789abcdef".repeat(4)
    private fun body(
        url: String = "joey-media-1.4.0-2026110302.apk",
        min: String = "2026102101",
        code: String = "2026110302",
        notes: String = "Faster start-up.\\nFixes \\\"Back\\\" on Overview \\u2013 thanks.",
    ) = """{
  "version": "1.4.0",
  "versionCode": $code,
  "min_version": $min,
  "url": "$url",
  "sha256": "$sha",
  "notes": "$notes",
  "size": 5242880,
  "published": "2026-11-03T01:02:03Z"
}"""

    @Test
    fun parsesTheGeneratedFile() {
        val parsed = RemoteVersion.parse(body())!!
        assertEquals("1.4.0", parsed.versionName)
        assertEquals(2026110302L, parsed.versionCode)
        assertEquals(2026102101L, parsed.minVersion)
        assertEquals("joey-media-1.4.0-2026110302.apk", parsed.url)
        assertEquals(sha, parsed.sha256)
        assertEquals(5242880L, parsed.size)
        assertEquals("Faster start-up.\nFixes \"Back\" on Overview – thanks.", parsed.notes)
    }

    @Test
    fun aStringMinVersionIsRejected() {
        assertNull(RemoteVersion.parse(body(min = "\"2026102101\"")))
    }

    @Test
    fun anAbsoluteOrForeignUrlIsRejected() {
        assertNull(RemoteVersion.parse(body(url = "https://media.joeyhome.net/app/joey-media-1.4.0-2026110302.apk")))
        assertNull(RemoteVersion.parse(body(url = "joey-media-1.4.0-2026110399.apk"))) // not its versionCode
    }

    @Test
    fun minAboveCodeOrABadCodeIsRejected() {
        assertNull(RemoteVersion.parse(body(min = "2026110303")))
        assertNull(RemoteVersion.parse(body(code = "2026110300", url = "joey-media-1.4.0-2026110300.apk")))
    }

    @Test
    fun garbageIsNull() {
        assertNull(RemoteVersion.parse(null))
        assertNull(RemoteVersion.parse("<html>502 Bad Gateway</html>"))
        assertNull(RemoteVersion.parse("{}"))
    }
}
