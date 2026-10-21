package net.joeyhome.media

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import net.joeyhome.media.policy.IntentSpec
import net.joeyhome.media.policy.Jellyfin
import net.joeyhome.media.policy.PlaybackRoute

/**
 * Hand-off launcher. Order: Jellyfin missing → the store card; item id + [route] intent → start it; on no route,
 * ActivityNotFoundException or SecurityException → route 3 (the app home via its leanback launch intent);
 * route 3 failing too → the store card. Every successful start marks "returning from playback" so onResume reloads.
 *
 * Step-7 seam: [route] is [net.joeyhome.media.policy.PendingPlaybackRoute] until the WP-B6 decision line lands
 * (see the TODO there). Settings → "Test hand-off" calls [open] too, so it always exercises the same code path.
 */
class JellyfinLauncher(
    private val activity: Activity,
    private val route: PlaybackRoute,
    private val onMissing: () -> Unit,
    private val onLaunched: () -> Unit,
) {
    fun isInstalled(): Boolean = try {
        @Suppress("DEPRECATION")
        activity.packageManager.getPackageInfo(Jellyfin.PACKAGE, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    fun open(itemId: String?) {
        if (!isInstalled()) {
            onMissing()
            return
        }
        val spec = itemId?.trim()?.takeIf { it.isNotEmpty() }?.let { route.itemIntent(it) }
        if (spec != null && start(spec.toIntent())) return
        if (openAppHome()) return
        onMissing()
    }

    /** Route 3 (research F4): the explicit leanback launch component, NEW_TASK. */
    private fun openAppHome(): Boolean {
        val pm = activity.packageManager
        val home = pm.getLeanbackLaunchIntentForPackage(Jellyfin.PACKAGE)
            ?: pm.getLaunchIntentForPackage(Jellyfin.PACKAGE)
            ?: return false
        return start(home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun start(intent: Intent): Boolean = try {
        activity.startActivity(intent)
        onLaunched()
        true
    } catch (e: ActivityNotFoundException) {
        false
    } catch (e: SecurityException) {
        false
    }
}

fun IntentSpec.toIntent(): Intent = Intent().also { intent ->
    intent.setClassName(packageName, className)
    action?.let { intent.action = it }
    intent.flags = flags
    for ((key, value) in extras) {
        when (value) {
            is String -> intent.putExtra(key, value)
            is Boolean -> intent.putExtra(key, value)
            is Int -> intent.putExtra(key, value)
            is Long -> intent.putExtra(key, value)
            else -> intent.putExtra(key, value.toString())
        }
    }
}
