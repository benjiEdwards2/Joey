package net.joeyhome.media.update

import net.joeyhome.media.policy.Origin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** WP-B8 step 7: what is offered, when the check is due, and where the relative APK url points. */
class UpdatePolicyTest {
    private fun remote(code: Long, min: Long = 2026102101) = RemoteVersion(
        versionName = "1.4.0", versionCode = code, minVersion = min, url = "joey-media-1.4.0-$code.apk",
        sha256 = "a".repeat(64), notes = "n", size = 10,
    )

    @Test
    fun newerIsAnOptionalOffer() {
        val decision = UpdatePolicy.decide(2026102101, remote(2026110302))
        assertEquals(UpdateDecision.Offer(remote(2026110302), forced = false), decision)
    }

    @Test
    fun belowMinVersionIsForced() {
        val decision = UpdatePolicy.decide(2026102101, remote(2026110302, min = 2026110301))
        assertEquals(UpdateDecision.Offer(remote(2026110302, min = 2026110301), forced = true), decision)
    }

    @Test
    fun equalIsNone() {
        assertEquals(UpdateDecision.None, UpdatePolicy.decide(2026110302, remote(2026110302)))
    }

    @Test
    fun olderRemoteIsNone() {
        assertEquals(UpdateDecision.None, UpdatePolicy.decide(2026120101, remote(2026110302)))
    }

    @Test
    fun noRemoteIsNone() {
        assertEquals(UpdateDecision.None, UpdatePolicy.decide(2026102101, null))
    }

    @Test
    fun dueOncePerDay() {
        val day = UpdatePolicy.CHECK_INTERVAL_MS
        assertTrue(UpdatePolicy.due(1_000, null))
        assertFalse(UpdatePolicy.due(1_000 + day - 1, 1_000))
        assertTrue(UpdatePolicy.due(1_000 + day, 1_000))
        assertTrue(UpdatePolicy.due(500, 1_000)) // the clock went backwards
    }

    @Test
    fun relativeUrlResolvesAgainstThePublicHost() {
        val versionUrl = UpdatePolicy.versionUrl(Origin.of("https://media.joeyhome.net")!!)
        assertEquals("https://media.joeyhome.net/app/version.json", versionUrl)
        assertEquals(
            "https://media.joeyhome.net/app/joey-media-1.4.0-2026110302.apk",
            UpdatePolicy.apkUrl(versionUrl, "joey-media-1.4.0-2026110302.apk"),
        )
    }

    @Test
    fun relativeUrlResolvesAgainstTheAdbReverseOverride() {
        val versionUrl = UpdatePolicy.versionUrl(Origin.of("http://127.0.0.1:8850")!!)
        assertEquals("http://127.0.0.1:8850/app/version.json", versionUrl)
        assertEquals(
            "http://127.0.0.1:8850/app/joey-media-1.4.0-2026110302.apk",
            UpdatePolicy.apkUrl(versionUrl, "joey-media-1.4.0-2026110302.apk"),
        )
    }

    @Test
    fun onlyABareApkNameIsResolved() {
        val versionUrl = "https://media.joeyhome.net/app/version.json"
        assertNull(UpdatePolicy.apkUrl(versionUrl, "https://evil.example/joey-media-1.4.0-2026110302.apk"))
        assertNull(UpdatePolicy.apkUrl(versionUrl, "../joey-media-1.4.0-2026110302.apk"))
        assertNull(UpdatePolicy.apkUrl(versionUrl, "//evil.example/x.apk"))
    }
}
