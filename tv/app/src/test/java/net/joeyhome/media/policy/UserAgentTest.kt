package net.joeyhome.media.policy

import net.joeyhome.media.BuildConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-P8 token, built from the real tv/VERSION values (BuildConfig). */
class UserAgentTest {
    private val base = "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
    private val pattern = Regex(".* JoeyTV/\\d+\\.\\d+\\.\\d+ \\(20\\d{8}\\)$")

    @Test
    fun userAgentCarriesTheJoeyTvToken() {
        val ua = UserAgent.build(base, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)
        assertTrue(ua, pattern.matches(ua))
        assertTrue(ua.startsWith(base))
    }

    @Test
    fun buildingTwiceKeepsOneToken() {
        val once = UserAgent.build(base, "0.1.0", 2026102101)
        assertEquals(once, UserAgent.build(once, "0.1.0", 2026102101))
        assertEquals("$base JoeyTV/0.2.0 (2026110101)", UserAgent.build(once, "0.2.0", 2026110101))
    }
}
