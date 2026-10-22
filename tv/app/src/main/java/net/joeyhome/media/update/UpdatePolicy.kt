package net.joeyhome.media.update

import java.net.URI
import net.joeyhome.media.policy.Origin

sealed interface UpdateDecision {
    data object None : UpdateDecision

    /** [forced] = the installed versionCode is below `min_version`: no Later, Back exits (DECISIONS F). */
    data class Offer(val remote: RemoteVersion, val forced: Boolean) : UpdateDecision
}

/** When to check, what to offer and where the APK lives (DECISIONS F: on launch, at most once a day). */
object UpdatePolicy {
    const val CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000

    /** Only a strictly newer versionCode is offered; an equal or older remote (a rolled-back server) never is. */
    fun decide(installedCode: Long, remote: RemoteVersion?): UpdateDecision = when {
        remote == null || remote.versionCode <= installedCode -> UpdateDecision.None
        else -> UpdateDecision.Offer(remote, forced = installedCode < remote.minVersion)
    }

    /** Due when there was no successful check yet, 24 h have passed, or the clock went backwards. */
    fun due(nowMs: Long, lastSuccessMs: Long?): Boolean =
        lastSuccessMs == null || nowMs < lastSuccessMs || nowMs - lastSuccessMs >= CHECK_INTERVAL_MS

    /** version.json on the UI host in use (the baked public host, or a LAN / adb-reverse override). */
    fun versionUrl(ui: Origin): String = "$ui/app/version.json"

    /** The relative `url` resolved next to version.json; only a bare APK name is accepted. */
    fun apkUrl(versionUrl: String, relative: String): String? {
        if (!RemoteVersion.APK_NAME.matches(relative)) return null
        return try {
            URI(versionUrl).resolve(relative).toString()
        } catch (e: IllegalArgumentException) {
            null
        } catch (e: java.net.URISyntaxException) {
            null
        }
    }
}
