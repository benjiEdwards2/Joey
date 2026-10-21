package net.joeyhome.media

import android.app.Activity
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.TextView
import net.joeyhome.media.policy.SettingsGesture

/**
 * The native screens, stacked in the overlay above the WebView. Layouts live in res/layout/screen_*.xml and every
 * colour/size in res/values, so restyling after the WP-M sign-off touches no code. Each screen has an explicit
 * initial focus and its own Back behaviour.
 */
class Screens(
    private val activity: Activity,
    private val host: FrameLayout,
    private val onOpenChanged: (open: Boolean) -> Unit,
) {
    enum class Kind { SPLASH, OFFLINE, SETTINGS, JELLYFIN_MISSING, UPDATE }

    private class Entry(val kind: Kind, val view: View, val focus: View, val onBack: () -> Unit)

    private val stack = ArrayList<Entry>()

    val isOpen: Boolean get() = stack.isNotEmpty()
    val top: Kind? get() = stack.lastOrNull()?.kind

    /** True while OK is held on Splash/Offline (the Splash waits instead of navigating mid-gesture). */
    var okHeld = false
        private set

    fun back() {
        stack.lastOrNull()?.onBack?.invoke()
    }

    /** Removes the top screen and refocuses the one below (if any). */
    fun pop() {
        val entry = stack.removeLastOrNull() ?: return
        host.removeView(entry.view)
        stack.lastOrNull()?.let { it.view.visibility = View.VISIBLE; it.focus.requestFocus() }
        if (stack.isEmpty()) onOpenChanged(false)
    }

    fun clear() {
        stack.clear()
        host.removeAllViews()
        okHeld = false
        onOpenChanged(false)
    }

    fun showSplash(onSettings: () -> Unit, onBack: () -> Unit) {
        clear()
        val view = inflate(R.layout.screen_splash)
        val root = view.findViewById<View>(R.id.splash_root)
        attachSettingsGesture(root, onSettings)
        push(Kind.SPLASH, view, root, onBack)
    }

    fun showOffline(onRetry: () -> Unit, onOpenJellyfin: () -> Unit, onSettings: () -> Unit, onBack: () -> Unit) {
        clear()
        val view = inflate(R.layout.screen_offline)
        val retry = view.findViewById<Button>(R.id.offline_retry)
        val openJf = view.findViewById<Button>(R.id.offline_open_jellyfin)
        retry.setOnClickListener { onRetry() }
        openJf.setOnClickListener { onOpenJellyfin() }
        attachSettingsGesture(retry, onSettings)
        attachSettingsGesture(openJf, onSettings)
        push(Kind.OFFLINE, view, retry, onBack)
    }

    fun showJellyfinMissing(fireTv: Boolean, jellyfinAddress: String, onGet: () -> Unit) {
        val view = inflate(R.layout.screen_jellyfin_missing)
        val get = view.findViewById<Button>(R.id.nojf_get)
        get.setOnClickListener { onGet() }
        view.findViewById<Button>(R.id.nojf_back).setOnClickListener { pop() }
        view.findViewById<TextView>(R.id.nojf_store)
            .setText(if (fireTv) R.string.nojf_store_amazon else R.string.nojf_store_play)
        view.findViewById<TextView>(R.id.nojf_server).text = activity.getString(R.string.nojf_server, jellyfinAddress)
        push(Kind.JELLYFIN_MISSING, view, get) { pop() }
    }

    /** WP-B8 step 7 decides when to call this; [onExit] is Back on a forced prompt. */
    fun showUpdate(offer: UpdateOffer, onUpdate: () -> Unit, onExit: () -> Unit) {
        val view = inflate(R.layout.screen_update)
        view.findViewById<TextView>(R.id.update_title)
            .setText(if (offer.forced) R.string.update_title_forced else R.string.update_title)
        view.findViewById<TextView>(R.id.update_body).text = if (offer.forced) {
            activity.getString(R.string.update_body_forced)
        } else {
            activity.getString(R.string.update_body, offer.newVersion, offer.installedVersion)
        }
        view.findViewById<TextView>(R.id.update_notes).text = offer.notes
        val now = view.findViewById<Button>(R.id.update_now)
        now.setOnClickListener { onUpdate() }
        val later = view.findViewById<Button>(R.id.update_later)
        if (offer.forced) later.visibility = View.GONE else later.setOnClickListener { pop() }
        push(Kind.UPDATE, view, now) { if (offer.forced) onExit() else pop() }
    }

    fun showSettings(model: SettingsModel, actions: SettingsActions) {
        val view = inflate(R.layout.screen_settings)
        val ui = view.findViewById<EditText>(R.id.settings_ui)
        val jf = view.findViewById<EditText>(R.id.settings_jf)
        val item = view.findViewById<EditText>(R.id.settings_item)
        val info = view.findViewById<TextView>(R.id.settings_info)
        fun fill(m: SettingsModel) {
            ui.setText(m.uiOverride.orEmpty())
            ui.hint = m.uiDefault
            jf.setText(m.jellyfinOverride.orEmpty())
            jf.hint = m.jellyfinDefault
            info.text = m.info
        }
        fill(model)
        val save = view.findViewById<Button>(R.id.settings_save)
        save.setOnClickListener { actions.save(ui.text.toString(), jf.text.toString()) }
        view.findViewById<Button>(R.id.settings_reset).setOnClickListener { fill(actions.reset()) }
        view.findViewById<Button>(R.id.settings_laptop).apply {
            visibility = if (model.debugBuild) View.VISIBLE else View.GONE
            setOnClickListener { ui.setText(model.laptopPreset) }
        }
        view.findViewById<Button>(R.id.settings_check_update).apply {
            visibility = if (model.updaterEnabled) View.VISIBLE else View.GONE
            setOnClickListener { actions.checkForUpdate() }
        }
        view.findViewById<Button>(R.id.settings_clear_signin).setOnClickListener { actions.clearSignIn() }
        view.findViewById<Button>(R.id.settings_test_handoff)
            .setOnClickListener { actions.testHandOff(item.text.toString()) }
        view.findViewById<Button>(R.id.settings_close).setOnClickListener { actions.close() }
        push(Kind.SETTINGS, view, save) { actions.close() }
    }

    private fun inflate(layout: Int): View = LayoutInflater.from(activity).inflate(layout, host, false)

    private fun push(kind: Kind, view: View, focus: View, onBack: () -> Unit) {
        stack.lastOrNull()?.view?.visibility = View.INVISIBLE
        stack.add(Entry(kind, view, focus, onBack))
        host.addView(view)
        onOpenChanged(true)
        focus.requestFocus()
    }

    /**
     * Hold OK ≥ 2 s on this view → [onOpen]. Key repeats arrive as ACTION_DOWN with the original downTime. The key-up
     * after a fired gesture is swallowed here; the new screen's initial focus is a button, which ignores a stray up.
     */
    private fun attachSettingsGesture(view: View, onOpen: () -> Unit) {
        var fired = false
        view.setOnKeyListener { _, keyCode, event ->
            if (!SettingsGesture.isOkKey(keyCode)) return@setOnKeyListener false
            when (event.action) {
                KeyEvent.ACTION_DOWN -> {
                    okHeld = true
                    if (!fired && SettingsGesture.reached(event.downTime, event.eventTime)) {
                        fired = true
                        okHeld = false
                        onOpen()
                    }
                    fired
                }
                KeyEvent.ACTION_UP -> {
                    okHeld = false
                    val consumed = fired
                    fired = false
                    consumed
                }
                else -> false
            }
        }
    }
}

data class UpdateOffer(val newVersion: String, val installedVersion: String, val notes: String, val forced: Boolean)

data class SettingsModel(
    val uiOverride: String?,
    val jellyfinOverride: String?,
    val uiDefault: String,
    val jellyfinDefault: String,
    val laptopPreset: String,
    val debugBuild: Boolean,
    val updaterEnabled: Boolean,
    val info: String,
)

interface SettingsActions {
    fun save(ui: String, jellyfin: String)
    fun reset(): SettingsModel
    fun checkForUpdate()
    fun clearSignIn()
    fun testHandOff(itemId: String)
    fun close()
}
