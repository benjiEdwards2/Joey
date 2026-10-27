package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Test

/** JY-057: a Jellyfin link carrying the hub's `player=joey` mark opens the shell's own player; anything else is unchanged. */
class UrlPolicyPlayTest {
    private val policy = UrlPolicy(HostConfig.DEFAULT)
    private val jf = "https://jellyfin.joeyhome.net:8443"
    private val id = "0123456789abcdef0123456789abcdef"

    @Test
    fun theMarkWithAWellFormedIdPlaysInTheShell() {
        assertEquals(UrlDecision.Play(id), policy.decide("$jf/web/#/details?id=$id&serverId=s&player=joey"))
        assertEquals(UrlDecision.Play(id), policy.decide("$jf/web/#/details?player=joey&id=$id"))
    }

    @Test
    fun aDashedIdPlaysToo() {
        val dashed = "01234567-89ab-cdef-0123-456789abcdef"
        assertEquals(UrlDecision.Play(dashed), policy.decide("$jf/web/#/details?id=$dashed&player=joey"))
    }

    @Test
    fun withoutTheMarkItIsTodaysHandOff() {
        assertEquals(UrlDecision.HandOff(id), policy.decide("$jf/web/#/details?id=$id&serverId=s"))
    }

    @Test
    fun anotherMarkValueOrAMalformedIdIsTheHandOff() {
        assertEquals(UrlDecision.HandOff(id), policy.decide("$jf/web/#/details?id=$id&player=jellyfin"))
        assertEquals(UrlDecision.HandOff(id), policy.decide("$jf/web/#/details?id=$id&xplayer=joey"))
        assertEquals(UrlDecision.HandOff("abc"), policy.decide("$jf/web/#/details?id=abc&player=joey"))
        assertEquals(UrlDecision.HandOff(null), policy.decide("$jf/web/#/home?player=joey"))
    }

    @Test
    fun theMarkInTheQueryNotTheFragmentDoesNothing() {
        assertEquals(UrlDecision.HandOff(id), policy.decide("$jf/web/?player=joey#/details?id=$id"))
    }

    @Test
    fun theMarkOffTheJellyfinOriginNeverPlays() {
        assertEquals(UrlDecision.Block, policy.decide("https://jellyfin.joeyhome.net/web/#/details?id=$id&player=joey"))
        assertEquals(UrlDecision.Load, policy.decide("https://media.joeyhome.net/x#/details?id=$id&player=joey"))
        assertEquals(UrlDecision.Block, policy.decide("https://evil.example/web/#/details?id=$id&player=joey"))
    }
}
