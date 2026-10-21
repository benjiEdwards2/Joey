package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HandOffTest {

    /** Until WP-B7 step 7 lands the WP-B6 route, every hand-off falls back to route 3 (app home). */
    @Test
    fun pendingRouteHasNoItemIntent() {
        assertNull(PendingPlaybackRoute.itemIntent("0123456789abcdef0123456789abcdef"))
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
