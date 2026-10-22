package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The shell intercepts KEYCODE_BACK only and never consumes a media key (DECISIONS D; WP-B7 step 5 check). */
class KeyPolicyTest {

    @Test
    fun onlyBackIsIntercepted() {
        val intercepted = (0..400).filter { KeyPolicy.intercepts(it) }
        assertEquals(listOf(4), intercepted) // KeyEvent.KEYCODE_BACK
    }

    @Test
    fun everyMediaKeyIsLeftAlone() {
        assertEquals(17, KeyPolicy.MEDIA_KEYS.size)
        for (code in KeyPolicy.MEDIA_KEYS) {
            assertTrue("$code", KeyPolicy.isMediaKey(code))
            assertFalse("$code", KeyPolicy.intercepts(code))
        }
        assertFalse(KeyPolicy.isMediaKey(23)) // DPAD_CENTER is not a media key
    }

    @Test
    fun settingsGestureNeedsTwoSecondsOfOk() {
        assertTrue(SettingsGesture.isOkKey(23)) // DPAD_CENTER
        assertTrue(SettingsGesture.isOkKey(66)) // ENTER
        assertFalse(SettingsGesture.isOkKey(4))
        assertFalse(SettingsGesture.reached(1_000, 2_999))
        assertTrue(SettingsGesture.reached(1_000, 3_000))
    }
}
