package net.joeyhome.media

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import net.joeyhome.media.policy.HandOff
import net.joeyhome.media.policy.HandOffStep
import net.joeyhome.media.policy.IntentSpec
import net.joeyhome.media.policy.Jellyfin
import net.joeyhome.media.policy.JellyfinItemRoute
import net.joeyhome.media.policy.PlaybackRoute

/**
 * Hand-off launcher (WP-B7 step 7): executes [HandOff.plan] in order. Route 1b item intent → route 3 app home →
 * the store card. Every successful start marks "returning from playback" so the next onResume reloads the page.
 * Back from Jellyfin lands on the Google TV launcher (its MainActivity uses TASK_ON_HOME); that is expected.
 * Settings → "Test hand-off" calls [open] too, so it always exercises the same code path.
 */
class JellyfinLauncher(
    private val activity: Activity,
    private val onMissing: () -> Unit,
    private val onLaunched: () -> Unit,
    private val route: PlaybackRoute = JellyfinItemRoute,
) {
    fun isInstalled(): Boolean = try {
        @Suppress("DEPRECATION")
        activity.packageManager.getPackageInfo(Jellyfin.PACKAGE, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    fun open(itemId: String?) {
        HandOff.run(HandOff.plan(isInstalled(), itemId, route)) { step ->
            when (step) {
                is HandOffStep.Item -> start(step.spec.toIntent())
                HandOffStep.AppHome -> openAppHome()
                HandOffStep.MissingCard -> {
                    onMissing()
                    true
                }
            }
        }
    }

    /** Route 3: the explicit leanback launch component, NEW_TASK (never the implicit `-p` form). */
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
