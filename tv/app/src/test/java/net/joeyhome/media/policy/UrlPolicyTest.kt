package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Test

/** WP-B7 step 4 named cases (Q41), with `<jf>` = https://jellyfin.joeyhome.net:8443. */
class UrlPolicyTest {
    private val policy = UrlPolicy(HostConfig.DEFAULT)
    private val jf = "https://jellyfin.joeyhome.net:8443"

    @Test
    fun jellyfinDetailsHandsOffWithItsId() {
        assertEquals(UrlDecision.HandOff("abc"), policy.decide("$jf/web/#/details?id=abc&serverId=s"))
    }

    @Test
    fun jellyfinHomeHandsOffWithNoId() {
        assertEquals(UrlDecision.HandOff(null), policy.decide("$jf/web/#/home"))
    }

    @Test
    fun portlessJellyfinIsNotTheJellyfinHostAndIsBlocked() {
        assertEquals(UrlDecision.Block, policy.decide("https://jellyfin.joeyhome.net/web/#/details?id=abc"))
    }

    @Test
    fun mediaUiLoads() {
        assertEquals(UrlDecision.Load, policy.decide("https://media.joeyhome.net/media/movies"))
    }

    @Test
    fun privateJoeyIsBlocked() {
        assertEquals(UrlDecision.Block, policy.decide("https://joeyhome.net/money"))
    }

    @Test
    fun youtubeIsExternal() {
        val url = "https://www.youtube.com/watch?v=x"
        assertEquals(UrlDecision.External(url), policy.decide(url))
    }

    @Test
    fun youtuBeShortLinkIsExternal() {
        val url = "https://youtu.be/x"
        assertEquals(UrlDecision.External(url), policy.decide(url))
    }

    @Test
    fun httpVersionOfTheUiIsADifferentOriginAndIsBlocked() {
        assertEquals(UrlDecision.Block, policy.decide("http://media.joeyhome.net/media/movies"))
    }

    @Test
    fun nonWebSchemesAreBlocked() {
        assertEquals(UrlDecision.Block, policy.decide("javascript:alert(1)"))
        assertEquals(UrlDecision.Block, policy.decide("intent://x#Intent;end"))
        assertEquals(UrlDecision.Block, policy.decide("not a url"))
    }

    @Test
    fun laptopOverrideLoadsItsOwnOrigin() {
        val laptop = UrlPolicy(HostConfig.from(HostConfig.LAPTOP_UI, null, debugBuild = true))
        assertEquals(UrlDecision.Load, laptop.decide("http://127.0.0.1:8850/a/media"))
        assertEquals(UrlDecision.Block, laptop.decide("https://media.joeyhome.net/a/media"))
    }

    @Test
    fun encodedItemIdIsDecoded() {
        assertEquals(UrlDecision.HandOff("a b"), policy.decide("$jf/web/#/details?serverId=s&id=a%20b"))
    }
}
