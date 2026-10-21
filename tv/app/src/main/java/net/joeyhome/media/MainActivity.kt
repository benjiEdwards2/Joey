package net.joeyhome.media

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.KeyEvent
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import net.joeyhome.media.policy.BackAction
import net.joeyhome.media.policy.BackPolicy
import net.joeyhome.media.policy.HomePath
import net.joeyhome.media.policy.HostCheck
import net.joeyhome.media.policy.HostConfig
import net.joeyhome.media.policy.Jellyfin
import net.joeyhome.media.policy.KeyPolicy
import net.joeyhome.media.policy.UrlDecision
import net.joeyhome.media.policy.UrlPolicy
import net.joeyhome.media.policy.UserAgent
import net.joeyhome.media.update.CheckResult
import net.joeyhome.media.update.DownloadResult
import net.joeyhome.media.update.UpdateDecision
import net.joeyhome.media.update.UpdateFlow

/**
 * The single Activity: a full-screen WebView over the Joey Media UI plus the native screens (Screens) above it.
 * Keys: D-pad goes to the focused view, Back is ours, Home never reaches apps, media keys are left to the system
 * (they belong to the Jellyfin app, DECISIONS D).
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var screens: Screens
    private lateinit var launcher: JellyfinLauncher
    private lateinit var root: FrameLayout
    private lateinit var hosts: HostConfig
    private lateinit var urlPolicy: UrlPolicy
    private var web: WebView? = null

    /** The guest home path for BackPolicy: /healthz `home`, else the `/` 303 Location, else the first UI page loaded. */
    private var homePath: String? = null
    private var clearHistoryOnNextPage = false
    private var learnHomeFromNextPage = false
    private var pendingUrl: String? = null
    private var splashGeneration = 0
    private var lastBackAt = 0L

    private val main = Handler(Looper.getMainLooper())
    private val io: ExecutorService = Executors.newSingleThreadExecutor()

    /** The sideload updater (WP-B8 step 7): its own thread, so a download never delays a Splash probe. */
    private val updateIo: ExecutorService = Executors.newSingleThreadExecutor()
    private var updates: UpdateFlow? = null
    private var activeUpdate: ActiveUpdate? = null
    private var updating = false

    private class ActiveUpdate(val offer: UpdateDecision.Offer, val versionUrl: String)
    private var backCallback: Any? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        root = findViewById(R.id.root)
        prefs = Prefs(this)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        screens = Screens(this, findViewById(R.id.overlay)) { open -> onOverlayChanged(open) }
        launcher = JellyfinLauncher(
            activity = this, // route 1b by default (WP-B6 decision line)
            onMissing = { showJellyfinMissing() },
            onLaunched = { prefs.returningFromPlayback = true },
        )
        applyHosts()
        createWebView()
        registerBackCallback()

        val restoreUrl = savedInstanceState?.getString(STATE_URL)
        if (restoreUrl != null && urlPolicy.decide(restoreUrl) == UrlDecision.Load) {
            homePath = savedInstanceState.getString(STATE_HOME)
            web?.loadUrl(restoreUrl)
        } else {
            startSplash()
        }
        if (BuildConfig.UPDATER) startUpdater()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web?.url?.let { outState.putString(STATE_URL, it) }
        homePath?.let { outState.putString(STATE_HOME, it) }
    }

    override fun onResume() {
        super.onResume()
        web?.onResume()
        if (!screens.isOpen && prefs.consumeReturningFromPlayback()) {
            // Back from the Jellyfin app: reload so the page shows fresh progress / Continue watching.
            val w = web ?: return
            val target = prefs.lastUrl?.takeIf { urlPolicy.decide(it) == UrlDecision.Load }
            if (target == null || target == w.url) w.reload() else w.loadUrl(target)
        }
    }

    override fun onPause() {
        web?.let { w ->
            w.url?.takeIf { urlPolicy.decide(it) == UrlDecision.Load }?.let { prefs.lastUrl = it }
            w.onPause()
        }
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onStop() {
        CookieManager.getInstance().flush()
        super.onStop()
    }

    override fun onDestroy() {
        unregisterBackCallback()
        main.removeCallbacksAndMessages(null)
        io.shutdownNow()
        updateIo.shutdownNow()
        web?.destroy()
        web = null
        super.onDestroy()
    }

    // ---- Keys -------------------------------------------------------------------------------------------------

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val keyCode = event.keyCode
        if (KeyPolicy.isMediaKey(keyCode)) return false // never consumed: the Jellyfin app / system owns media keys
        if (KeyPolicy.intercepts(keyCode)) { // KEYCODE_BACK only
            if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) handleBack()
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    /** API 33+ delivers Back through OnBackInvokedDispatcher (manifest opts in); older APIs through dispatchKeyEvent. */
    private fun registerBackCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val callback = android.window.OnBackInvokedCallback { handleBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                callback,
            )
            backCallback = callback
        }
    }

    private fun unregisterBackCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            (backCallback as? android.window.OnBackInvokedCallback)?.let {
                onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it)
            }
        }
        backCallback = null
    }

    /** One Back press, from either delivery path (de-duplicated). */
    private fun handleBack() {
        val now = SystemClock.uptimeMillis()
        if (now - lastBackAt < BACK_DEDUPE_MS) return
        lastBackAt = now
        decideBack(pageHandled = null)
    }

    private fun decideBack(pageHandled: Boolean?) {
        val w = web
        val action = BackPolicy.decide(
            overlayOpen = screens.isOpen,
            pageHandled = pageHandled ?: if (w == null) false else null,
            canGoBack = w?.canGoBack() == true,
            currentPath = w?.url?.takeIf { urlPolicy.decide(it) == UrlDecision.Load }?.let { Uri.parse(it).path },
            homePath = homePath,
        )
        when (action) {
            BackAction.CLOSE_OVERLAY -> screens.back()
            BackAction.ASK_PAGE -> w?.evaluateJavascript(BackPolicy.PAGE_BACK_JS) { result ->
                decideBack(pageHandled = result == "true")
            }
            BackAction.DONE -> Unit
            BackAction.GO_BACK -> w?.goBack()
            BackAction.EXIT -> finish()
            BackAction.LOAD_HOME -> homePath?.let {
                clearHistoryOnNextPage = true
                loadUi(it)
            }
        }
    }

    // ---- Hosts and splash ------------------------------------------------------------------------------------

    private fun applyHosts() {
        hosts = HostConfig.from(prefs.uiOverride, prefs.jellyfinOverride, BuildConfig.DEBUG)
        urlPolicy = UrlPolicy(hosts)
    }

    private fun userAgent(): String =
        UserAgent.build(WebSettings.getDefaultUserAgent(this), BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)

    private fun loadUi(path: String) {
        web?.loadUrl(hosts.ui.toString() + path)
    }

    /** Splash ≥ 1.5 s while GET <ui>/healthz runs; reachable → the WebView, else Offline. */
    private fun startSplash() {
        val generation = ++splashGeneration
        val started = SystemClock.uptimeMillis()
        screens.showSplash(onSettings = { openSettings() }, onBack = { finish() })
        val ui = hosts.ui
        val ua = userAgent()
        io.execute {
            val result = HealthCheck.probe(ui, ua)
            main.post { finishSplash(generation, started, result) }
        }
    }

    private fun finishSplash(generation: Int, started: Long, result: HealthCheck.Result) {
        if (isDestroyed || generation != splashGeneration || screens.top != Screens.Kind.SPLASH) return
        val remaining = SPLASH_MIN_MS - (SystemClock.uptimeMillis() - started)
        if (remaining > 0 || screens.okHeld) {
            main.postDelayed({ finishSplash(generation, started, result) }, maxOf(remaining, 100L))
            return
        }
        if (!result.reachable) {
            showOffline()
            return
        }
        homePath = result.homePath
        learnHomeFromNextPage = homePath == null
        screens.clear()
        val returning = prefs.consumeReturningFromPlayback()
        val target = (pendingUrl ?: prefs.lastUrl.takeIf { returning })
            ?.takeIf { urlPolicy.decide(it) == UrlDecision.Load }
        pendingUrl = null
        if (target != null) web?.loadUrl(target) else loadUi("/")
        showActiveUpdate() // an offer that arrived during the Splash
    }

    private fun showOffline() {
        splashGeneration++
        screens.showOffline(
            onRetry = { startSplash() },
            onOpenJellyfin = { launcher.open(null) }, // route 3
            onSettings = { openSettings() },
            onBack = { finish() },
        )
    }

    private fun showJellyfinMissing() {
        val fireTv = packageManager.hasSystemFeature(FIRE_TV_FEATURE)
        screens.showJellyfinMissing(fireTv, hosts.jellyfin.toString()) { openStore(fireTv) }
    }

    private fun openStore(fireTv: Boolean) {
        for (link in Jellyfin.storeLinks(fireTv)) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link)))
                return
            } catch (e: ActivityNotFoundException) {
                // try the next link
            }
        }
        toast(R.string.nojf_store_failed)
    }

    // ---- Updater (sideload flavor, WP-B8 step 7; DECISIONS F) ---------------------------------------------------

    private fun updatesDir() = File(cacheDir, "updates")

    /** On launch: clear last run's APK, then check (at most once a day) in parallel with the WebView load. */
    private fun startUpdater() {
        updates = UpdateFlow(AndroidUpdatePorts(this, userAgent()), BuildConfig.VERSION_CODE.toLong()) {
            System.currentTimeMillis()
        }
        val dir = updatesDir()
        updateIo.execute { UpdateFlow.clear(dir) }
        checkForUpdate(manual = false)
    }

    /** [manual] = Settings → "Check for update now": skips the 24 h throttle and reports every outcome. */
    private fun checkForUpdate(manual: Boolean) {
        val flow = updates ?: return
        val ui = hosts.ui
        val last = prefs.lastUpdateCheck
        updateIo.execute {
            val result = flow.check(ui, last, force = manual)
            main.post { onUpdateCheck(result, manual) }
        }
    }

    private fun onUpdateCheck(result: CheckResult, manual: Boolean) {
        if (isDestroyed) return
        when (result) {
            CheckResult.Skipped -> Unit
            CheckResult.Failed -> if (manual) toast(R.string.update_check_failed) // silent on launch
            is CheckResult.Done -> {
                prefs.lastUpdateCheck = result.checkedAt
                when (val decision = result.decision) {
                    UpdateDecision.None -> if (manual) toast(R.string.update_up_to_date)
                    is UpdateDecision.Offer -> {
                        activeUpdate = ActiveUpdate(decision, result.versionUrl)
                        showActiveUpdate()
                    }
                }
            }
        }
    }

    /** Shown above the page or Settings, never over Splash/Offline (they clear the overlay); re-shown after the next
     *  Splash until Later (optional) or forever (forced). */
    private fun showActiveUpdate() {
        val active = activeUpdate ?: return
        when (screens.top) {
            Screens.Kind.SPLASH, Screens.Kind.OFFLINE, Screens.Kind.UPDATE, Screens.Kind.MESSAGE -> return
            else -> Unit
        }
        val remote = active.offer.remote
        screens.showUpdate(
            UpdateOffer(remote.versionName, BuildConfig.VERSION_NAME, remote.notes, active.offer.forced),
            onUpdate = { startUpdate(active) },
            onLater = { activeUpdate = null },
            onExit = { finish() },
        )
    }

    private fun startUpdate(active: ActiveUpdate) {
        val flow = updates ?: return
        if (!InstallPermission.granted(this)) {
            // Per-app "Install unknown apps"; Fire OS has no such screen → the explainer. The prompt stays open, so
            // the user comes back and presses Update now again.
            if (!InstallPermission.openSettings(this)) {
                screens.showMessage(R.string.update_allow_title, getString(R.string.update_allow_body))
            }
            return
        }
        if (updating) return
        updating = true
        toast(R.string.update_downloading)
        val dir = updatesDir()
        updateIo.execute {
            val result = flow.downloadAndInstall(active.offer.remote, active.versionUrl, dir)
            main.post {
                updating = false
                if (result is DownloadResult.Failed && !isDestroyed) toast(R.string.update_failed)
            }
        }
    }

    // ---- Hidden settings -------------------------------------------------------------------------------------

    private fun openSettings() {
        splashGeneration++ // a pending splash result must not navigate away from Settings
        screens.showSettings(settingsModel(), object : SettingsActions {
            override fun save(ui: String, jellyfin: String) {
                val uiCheck = ui.takeIf { it.isNotBlank() }?.let { HostConfig.check(it, BuildConfig.DEBUG) }
                val jfCheck = jellyfin.takeIf { it.isNotBlank() }?.let { HostConfig.check(it, BuildConfig.DEBUG) }
                listOfNotNull(uiCheck, jfCheck).filterIsInstance<HostCheck.Rejected>().firstOrNull()?.let {
                    toast(it.reason)
                    return
                }
                prefs.uiOverride = (uiCheck as? HostCheck.Ok)?.origin?.toString()
                prefs.jellyfinOverride = (jfCheck as? HostCheck.Ok)?.origin?.toString()
                close()
            }

            override fun reset(): SettingsModel {
                prefs.clearHosts()
                applyHosts()
                return settingsModel()
            }

            override fun checkForUpdate() = checkForUpdate(manual = true)

            override fun clearSignIn() {
                CookieManager.getInstance().removeAllCookies(null)
                CookieManager.getInstance().flush()
                WebStorage.getInstance().deleteAllData()
                prefs.lastUrl = null
                toast(R.string.settings_signed_out)
            }

            override fun testHandOff(itemId: String) = launcher.open(itemId)

            override fun close() {
                applyHosts()
                startSplash() // re-probe with the (possibly new) hosts
            }
        })
    }

    private fun settingsModel(): SettingsModel {
        val webViewPackage = WebView.getCurrentWebViewPackage()
        val info = listOf(
            "Joey Media ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE}) ${BuildConfig.FLAVOR}/${BuildConfig.BUILD_TYPE}",
            "Android API ${Build.VERSION.SDK_INT} · ${Build.MANUFACTURER} ${Build.MODEL}",
            "WebView ${webViewPackage?.packageName ?: "?"} ${webViewPackage?.versionName ?: "?"}",
            "UI ${hosts.ui} · Jellyfin ${hosts.jellyfin}",
            "Jellyfin app ${if (launcher.isInstalled()) "installed" else "missing"}",
        ).joinToString("\n")
        return SettingsModel(
            uiOverride = prefs.uiOverride,
            jellyfinOverride = prefs.jellyfinOverride,
            uiDefault = HostConfig.DEFAULT_UI,
            jellyfinDefault = HostConfig.DEFAULT_JELLYFIN,
            laptopPreset = HostConfig.LAPTOP_UI,
            debugBuild = BuildConfig.DEBUG,
            updaterEnabled = BuildConfig.UPDATER,
            info = info,
        )
    }

    // ---- WebView ---------------------------------------------------------------------------------------------

    private fun onOverlayChanged(open: Boolean) {
        val w = web ?: return
        w.isFocusable = !open
        w.isFocusableInTouchMode = !open
        if (!open) w.requestFocus()
    }

    private fun createWebView() {
        val w = WebView(this)
        w.setBackgroundColor(getColor(R.color.joey_bg))
        w.isFocusable = !screens.isOpen
        w.isFocusableInTouchMode = !screens.isOpen
        with(w.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            textZoom = 100
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = UserAgent.build(userAgentString, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(w, false)
        }
        w.webViewClient = ShellClient()
        root.addView(w, 0, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        web = w
    }

    private inner class ShellClient : WebViewClient() {

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            if (!request.isForMainFrame) return false // sub-frames (e.g. an embedded trailer) are the page's business
            return when (val decision = urlPolicy.decide(request.url.toString())) {
                UrlDecision.Load -> false
                is UrlDecision.HandOff -> {
                    launcher.open(decision.itemId)
                    true
                }
                is UrlDecision.External -> {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(decision.url)))
                    } catch (e: ActivityNotFoundException) {
                        toast(R.string.toast_youtube_missing)
                    }
                    true
                }
                UrlDecision.Block -> {
                    toast(R.string.toast_not_on_tv)
                    true
                }
            }
        }

        override fun onPageFinished(view: WebView, url: String?) {
            if (clearHistoryOnNextPage) {
                clearHistoryOnNextPage = false
                view.clearHistory()
            }
            if (url != null && urlPolicy.decide(url) == UrlDecision.Load) {
                if (learnHomeFromNextPage) {
                    learnHomeFromNextPage = false
                    homePath = HomePath.normalise(Uri.parse(url).path)
                }
                CookieManager.getInstance().flush() // keeps a fresh sign-in across a power cut
            }
            if (!screens.isOpen) view.requestFocus()
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame) goOffline(view, request)
        }

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
            // A 5xx on the main frame = the tunnel or the guest container is down (e.g. mid-deploy): show Offline.
            if (request.isForMainFrame && response.statusCode >= 500) goOffline(view, request)
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            val url = view.url
            root.removeView(view)
            view.destroy()
            web = null
            createWebView()
            if (url != null && urlPolicy.decide(url) == UrlDecision.Load) web?.loadUrl(url) else startSplash()
            return true
        }

        private fun goOffline(view: WebView, request: WebResourceRequest) {
            pendingUrl = request.url.toString().takeIf { urlPolicy.decide(it) == UrlDecision.Load }
            view.stopLoading()
            showOffline()
        }
    }

    private fun toast(resId: Int) = Toast.makeText(this, resId, Toast.LENGTH_SHORT).show()
    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_SHORT).show()

    private companion object {
        const val SPLASH_MIN_MS = 1_500L
        const val BACK_DEDUPE_MS = 250L
        const val FIRE_TV_FEATURE = "amazon.hardware.fire_tv"
        const val STATE_URL = "url"
        const val STATE_HOME = "home"
    }
}
