package net.joeyhome.media.policy

import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/** WP-B7 step 4: BackPolicy with an INJECTED homePath, parameterised over two homes so no literal can sneak in. */
@RunWith(Parameterized::class)
class BackPolicyTest(private val homePath: String) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "homePath={0}")
        fun homes(): List<Array<Any>> = listOf(arrayOf("/a/media"), arrayOf("/a/films"))
    }

    private val ui = HostConfig.DEFAULT.ui

    private fun afterPage(currentPath: String?, canGoBack: Boolean, home: String? = homePath) =
        BackPolicy.decide(overlayOpen = false, pageHandled = false, canGoBack = canGoBack, currentPath = currentPath, homePath = home)

    @Test
    fun backAtHomeWithNoHistoryExits() {
        assertEquals(BackAction.EXIT, afterPage(homePath, canGoBack = false))
    }

    @Test
    fun backOffHomeWithNoHistoryGoesToHome() {
        assertEquals(BackAction.LOAD_HOME, afterPage("/media/movies", canGoBack = false))
    }

    @Test
    fun healthzWithoutHomeUsesTheRootRedirectLocation() {
        val resolved = HomePath.resolve("""{"status":"ok","front":"media"}""", homePath, ui)
        assertEquals(homePath, resolved)
        assertEquals(BackAction.EXIT, afterPage(homePath, canGoBack = false, home = resolved))
        assertEquals(BackAction.LOAD_HOME, afterPage("/media/movies", canGoBack = false, home = resolved))
    }

    @Test
    fun healthzHomeFieldWinsOverTheRedirect() {
        assertEquals(homePath, HomePath.resolve("""{"status":"ok","front":"media","home":"$homePath"}""", "/elsewhere", ui))
    }

    @Test
    fun nullHomeFieldFallsBackToAnAbsoluteLocationOnTheUiOrigin() {
        val resolved = HomePath.resolve("""{"home": null}""", "https://media.joeyhome.net$homePath", ui)
        assertEquals(homePath, resolved)
    }

    @Test
    fun offOriginLocationIsIgnored() {
        assertEquals(null, HomePath.resolve("{}", "https://joeyhome.net$homePath", ui))
    }

    @Test
    fun nativeOverlayClosesFirst() {
        assertEquals(BackAction.CLOSE_OVERLAY, BackPolicy.decide(true, null, true, homePath, homePath))
    }

    @Test
    fun pageIsAskedBeforeHistory() {
        assertEquals(BackAction.ASK_PAGE, BackPolicy.decide(false, null, true, "/media/movies", homePath))
        assertEquals(BackAction.DONE, BackPolicy.decide(false, true, true, "/media/movies", homePath))
    }

    @Test
    fun historyGoesBackOffHome() {
        assertEquals(BackAction.GO_BACK, afterPage("/media/movies", canGoBack = true))
    }

    @Test
    fun homeExitsEvenWithHistory() {
        assertEquals(BackAction.EXIT, afterPage(homePath, canGoBack = true))
    }

    @Test
    fun trailingSlashAtHomeStillExits() {
        assertEquals(BackAction.EXIT, afterPage("$homePath/", canGoBack = false))
    }

    // JY-191 (B4): Back on the sign-in page exits instead of going back to a page that 303s to a NEW code.
    @Test
    fun signInExitsEvenWithHistory() {
        assertEquals(BackAction.EXIT, afterPage("/signin", canGoBack = true))
        assertEquals(BackAction.EXIT, afterPage("/signin", canGoBack = false))
    }

    @Test
    fun signInWithQueryOrTrailingSlashExits() {
        assertEquals(BackAction.EXIT, afterPage("/signin?next=%2Fa%2Fmedia", canGoBack = true))
        assertEquals(BackAction.EXIT, afterPage("/signin/", canGoBack = true))
    }

    @Test
    fun signInExitsWhenHomeIsUnknown() {
        assertEquals(BackAction.EXIT, afterPage("/signin", canGoBack = true, home = null))
    }

    @Test
    fun signInStillClosesOverlayAndAsksThePageFirst() {
        assertEquals(BackAction.CLOSE_OVERLAY, BackPolicy.decide(true, null, true, "/signin", homePath))
        assertEquals(BackAction.ASK_PAGE, BackPolicy.decide(false, null, true, "/signin", homePath))
        assertEquals(BackAction.DONE, BackPolicy.decide(false, true, true, "/signin", homePath))
    }

    @Test
    fun pathsThatOnlyStartWithSignInAreNotSignIn() {
        assertEquals(BackAction.GO_BACK, afterPage("/signinx", canGoBack = true))
        assertEquals(BackAction.GO_BACK, afterPage("/signin-help", canGoBack = true))
        assertEquals(BackAction.LOAD_HOME, afterPage("/signinx", canGoBack = false))
    }

    @Test
    fun unknownHomeWithNoHistoryExits() {
        assertEquals(BackAction.EXIT, afterPage("/media/movies", canGoBack = false, home = null))
    }
}
