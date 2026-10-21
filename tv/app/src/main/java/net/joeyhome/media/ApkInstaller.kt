package net.joeyhome.media

import android.app.Activity
import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import net.joeyhome.media.update.UpdatePorts

/**
 * The sideload updater's Android half (WP-B8 step 7): HTTP for version.json and the APK, the unknown-sources
 * permission, and a PackageInstaller session (MODE_FULL_INSTALL). The session's status comes back to
 * [UpdateStatusReceiver], which is declared `exported="false"` in the sideload manifest only, so no other app can
 * forge a status (and with it an EXTRA_INTENT for us to start).
 */
class AndroidUpdatePorts(private val activity: Activity, private val userAgent: String) : UpdatePorts {

    override fun fetch(url: String): String? {
        val conn = connect(url, READ_TIMEOUT_VERSION_MS) ?: return null
        return try {
            if (conn.responseCode == 200) conn.inputStream.bufferedReader().use { it.readText() } else null
        } catch (e: IOException) {
            null
        } finally {
            conn.disconnect()
        }
    }

    override fun open(url: String): InputStream? {
        val conn = connect(url, READ_TIMEOUT_APK_MS) ?: return null
        return try {
            if (conn.responseCode == 200) {
                conn.inputStream
            } else {
                conn.disconnect()
                null
            }
        } catch (e: IOException) {
            conn.disconnect()
            null
        }
    }

    override fun install(apk: File) {
        val installer = activity.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(activity.packageName)
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            apk.inputStream().use { input ->
                session.openWrite("base.apk", 0, apk.length()).use { out ->
                    input.copyTo(out)
                    session.fsync(out)
                }
            }
            val status = Intent(activity, UpdateStatusReceiver::class.java).setAction(UpdateStatusReceiver.ACTION)
            // The system fills EXTRA_STATUS / EXTRA_INTENT into it, so it must be mutable (explicit component).
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
            val pending = PendingIntent.getBroadcast(activity, sessionId, status, flags)
            session.commit(pending.intentSender)
        }
    }

    private fun connect(url: String, readTimeoutMs: Int): HttpURLConnection? = try {
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = readTimeoutMs
            useCaches = false
            setRequestProperty("User-Agent", userAgent)
        }
    } catch (e: IOException) {
        null
    }

    private companion object {
        const val CONNECT_TIMEOUT_MS = 5_000
        const val READ_TIMEOUT_VERSION_MS = 5_000
        const val READ_TIMEOUT_APK_MS = 30_000
    }
}

/** Unknown-sources permission (Android 8+: per app). */
object InstallPermission {
    fun granted(context: Context): Boolean = context.packageManager.canRequestPackageInstalls()

    /** Opens "Install unknown apps" for this app; false where the screen does not exist (Fire OS). */
    fun openSettings(activity: Activity): Boolean = try {
        activity.startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${activity.packageName}")),
        )
        true
    } catch (e: ActivityNotFoundException) {
        false
    }
}

/** PackageInstaller session status: user confirmation → the system's confirm screen; a failure → a toast. */
class UpdateStatusReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION) return
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                try {
                    confirm?.let { context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } ?: failed(context)
                } catch (e: ActivityNotFoundException) {
                    failed(context)
                }
            }
            PackageInstaller.STATUS_SUCCESS -> Unit // the system replaces and stops the app
            else -> failed(context)
        }
    }

    private fun failed(context: Context) {
        Toast.makeText(context, R.string.update_failed, Toast.LENGTH_LONG).show()
    }

    companion object {
        const val ACTION = "net.joeyhome.media.UPDATE_STATUS"
    }
}
