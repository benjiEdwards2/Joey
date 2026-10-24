package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Test

/** JY-191 (V2): the Offline screen's wording follows a fresh /healthz probe, not the failed page. */
class OfflinePolicyTest {

    @Test
    fun joeyUpMeansThePageFailed() {
        assertEquals(OfflineKind.PAGE, OfflinePolicy.kind(serverReachable = true))
    }

    @Test
    fun joeyDownMeansTheNetworkOrServer() {
        assertEquals(OfflineKind.NETWORK, OfflinePolicy.kind(serverReachable = false))
    }
}
