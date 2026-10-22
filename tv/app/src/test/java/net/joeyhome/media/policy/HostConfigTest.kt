package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HostConfigTest {

    @Test
    fun releaseRejectsAnHttpLanOverride() {
        assertTrue(HostConfig.check("http://192.168.68.59:8850", debugBuild = false) is HostCheck.Rejected)
    }

    @Test
    fun debugAcceptsTheLaptopPreset() {
        val check = HostConfig.check(HostConfig.LAPTOP_UI, debugBuild = true)
        assertEquals(HostCheck.Ok(Origin("http", "127.0.0.1", 8850)), check)
    }

    @Test
    fun releaseAcceptsHttpsWithAPort() {
        val check = HostConfig.check("https://jellyfin.example.test:8443/", debugBuild = false)
        assertEquals(HostCheck.Ok(Origin("https", "jellyfin.example.test", 8443)), check)
    }

    @Test
    fun bakedDefaultsCarryThePublicJellyfinPort() {
        assertEquals("https://media.joeyhome.net", HostConfig.DEFAULT.ui.toString())
        assertEquals("https://jellyfin.joeyhome.net:8443", HostConfig.DEFAULT.jellyfin.toString())
    }

    @Test
    fun overridesMustBeABareOrigin() {
        for (bad in listOf(
            "https://media.example.test/a/media",
            "https://media.example.test/?x=1",
            "https://user@media.example.test",
            "ftp://media.example.test",
            "media.example.test",
            "",
        )) {
            assertTrue(bad, HostConfig.check(bad, debugBuild = true) is HostCheck.Rejected)
        }
    }

    @Test
    fun invalidStoredOverridesFallBackToTheDefaults() {
        val config = HostConfig.from("http://192.168.68.59:8850", "garbage", debugBuild = false)
        assertEquals(HostConfig.DEFAULT, config)
    }
}
