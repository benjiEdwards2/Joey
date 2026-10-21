package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** WP-B7 step 7: the WP-B6 decision line (route 1b) and the fallback order, asserted exactly. */
class HandOffTest {
    private val id = "0123456789abcdef0123456789abcdef"

    @Test
    fun itemIntentIsRoute1bExactly() {
        val spec = JellyfinItemRoute.itemIntent(id)!!
        assertEquals("org.jellyfin.androidtv", spec.packageName)
        assertEquals("org.jellyfin.androidtv.ui.startup.StartupActivity", spec.className)
        assertNull(spec.action) // no action: VIEW / MAIN are not needed and implicit forms don't resolve
        assertEquals(mapOf("ItemId" to id), spec.extras)
        assertEquals(0x10000000, spec.flags) // FLAG_ACTIVITY_NEW_TASK only
    }

    @Test
    fun dashedUuidIsAccepted() {
        val dashed = "01234567-89ab-cdef-0123-456789abcdef"
        assertEquals(mapOf("ItemId" to dashed), JellyfinItemRoute.itemIntent(dashed)!!.extras)
    }

    @Test
    fun malformedIdsGetNoItemIntent() {
        for (bad in listOf("abc", "not-an-id", "", "0123456789abcdef0123456789abcdeg", "${id}0")) {
            assertNull(bad, JellyfinItemRoute.itemIntent(bad))
        }
    }

    @Test
    fun missingAppGoesStraightToTheCard() {
        assertEquals(listOf(HandOffStep.MissingCard), HandOff.plan(jellyfinInstalled = false, itemId = id))
    }

    @Test
    fun fallbackOrderIsItemThenAppHomeThenCard() {
        val spec = JellyfinItemRoute.itemIntent(id)!!
        assertEquals(
            listOf(HandOffStep.Item(spec), HandOffStep.AppHome, HandOffStep.MissingCard),
            HandOff.plan(jellyfinInstalled = true, itemId = id),
        )
    }

    @Test
    fun noOrMalformedIdStartsAtAppHome() {
        val expected = listOf(HandOffStep.AppHome, HandOffStep.MissingCard)
        assertEquals(expected, HandOff.plan(jellyfinInstalled = true, itemId = null))
        assertEquals(expected, HandOff.plan(jellyfinInstalled = true, itemId = "  "))
        assertEquals(expected, HandOff.plan(jellyfinInstalled = true, itemId = "abc"))
    }

    @Test
    fun itemStartFailureFallsBackToAppHome() {
        val tried = mutableListOf<HandOffStep>()
        val ran = HandOff.run(HandOff.plan(true, id)) { step ->
            tried += step
            step == HandOffStep.AppHome // the item start threw ActivityNotFound / SecurityException
        }
        assertEquals(HandOffStep.AppHome, ran)
        assertEquals(2, tried.size)
    }

    @Test
    fun appHomeFailureEndsOnTheCard() {
        val ran = HandOff.run(HandOff.plan(true, id)) { step -> step == HandOffStep.MissingCard }
        assertEquals(HandOffStep.MissingCard, ran)
    }

    @Test
    fun successfulItemStartStopsTheChain() {
        val tried = mutableListOf<HandOffStep>()
        val ran = HandOff.run(HandOff.plan(true, id)) { step -> tried += step; true }
        assertEquals(HandOffStep.Item(JellyfinItemRoute.itemIntent(id)!!), ran)
        assertEquals(1, tried.size)
    }

    @Test
    fun storeLinksPerDevice() {
        assertEquals(
            listOf(
                "market://details?id=org.jellyfin.androidtv",
                "https://play.google.com/store/apps/details?id=org.jellyfin.androidtv",
            ),
            Jellyfin.storeLinks(fireTv = false),
        )
        assertEquals("amzn://apps/android?p=org.jellyfin.androidtv", Jellyfin.storeLinks(fireTv = true).first())
    }
}
