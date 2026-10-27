package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Test

/** JY-057 look A: Back in the player closes the pop-up, then hides the controls, then returns to Joey. */
class BackPolicyPlayerTest {

    @Test
    fun popUpClosesFirst() {
        assertEquals(PlayerBack.CLOSE_POPUP, BackPolicy.player(PlayerOverlay.POPUP))
    }

    @Test
    fun controlsHideBeforeLeaving() {
        assertEquals(PlayerBack.HIDE_CONTROLS, BackPolicy.player(PlayerOverlay.CONTROLS))
    }

    @Test
    fun nothingUpReturnsToJoey() {
        assertEquals(PlayerBack.RETURN_TO_JOEY, BackPolicy.player(PlayerOverlay.NONE))
    }

    @Test
    fun theUpNextCardReturnsToJoey() {
        assertEquals(PlayerBack.RETURN_TO_JOEY, BackPolicy.player(PlayerOverlay.UP_NEXT))
    }

    @Test
    fun backTwiceFromTheControlsIsJoey() {
        val now = 1_000L
        val shown = PlayerUi.initial(now, hasNext = false)
        assertEquals(PlayerOverlay.CONTROLS, shown.overlay)
        val once = PlayerUi.onBack(shown, now)
        assertEquals(PlayerOverlay.NONE, once.state.overlay)
        assertEquals(PlayerAction.None, once.action)
        assertEquals(PlayerAction.ReturnToJoey, PlayerUi.onBack(once.state, now).action)
    }

    @Test
    fun theWebViewOrderIsUnchanged() {
        assertEquals(BackAction.CLOSE_OVERLAY, BackPolicy.decide(true, null, true, "/a/media", "/a/media"))
        assertEquals(BackAction.EXIT, BackPolicy.decide(false, false, false, "/a/media", "/a/media"))
    }
}
