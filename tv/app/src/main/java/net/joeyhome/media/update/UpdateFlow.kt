package net.joeyhome.media.update

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import net.joeyhome.media.policy.Origin

/** The Android side of the updater (HTTP + PackageInstaller); tests pass fakes. Blocking: call off the main thread. */
interface UpdatePorts {
    /** GET with 5 s timeouts; the body on HTTP 200, else null. Never throws. */
    fun fetch(url: String): String?

    /** The APK body on HTTP 200, else null. Never throws. */
    fun open(url: String): InputStream?

    /** Hands a verified APK to the system installer; may throw. */
    fun install(apk: File)
}

sealed interface CheckResult {
    data object Skipped : CheckResult
    data object Failed : CheckResult
    data class Done(val decision: UpdateDecision, val versionUrl: String, val checkedAt: Long) : CheckResult
}

sealed interface DownloadResult {
    data class Installing(val apk: File) : DownloadResult
    data class Failed(val reason: String) : DownloadResult
}

/**
 * The updater's logic (WP-B8 step 7), pure JVM: the 24 h throttle, version.json → decision, the streamed download
 * with SHA-256 + size verification, and the rule that nothing reaches [UpdatePorts.install] unless it verified.
 */
class UpdateFlow(
    private val ports: UpdatePorts,
    private val installedCode: Long,
    private val now: () -> Long,
) {
    fun check(ui: Origin, lastSuccessMs: Long?, force: Boolean = false): CheckResult {
        val at = now()
        if (!force && !UpdatePolicy.due(at, lastSuccessMs)) return CheckResult.Skipped
        val url = UpdatePolicy.versionUrl(ui)
        val remote = RemoteVersion.parse(ports.fetch(url)) ?: return CheckResult.Failed
        return CheckResult.Done(UpdatePolicy.decide(installedCode, remote), url, at)
    }

    fun downloadAndInstall(remote: RemoteVersion, versionUrl: String, dir: File): DownloadResult {
        val apkUrl = UpdatePolicy.apkUrl(versionUrl, remote.url) ?: return DownloadResult.Failed("bad url")
        val input = ports.open(apkUrl) ?: return DownloadResult.Failed("download")
        val apk = save(input, dir, remote) ?: return DownloadResult.Failed("verify")
        return try {
            ports.install(apk)
            DownloadResult.Installing(apk)
        } catch (e: Exception) {
            DownloadResult.Failed("install: ${e.javaClass.simpleName}")
        }
    }

    companion object {
        /** Streams [input] to `dir/<remote.url>` hashing as it goes; a size or hash mismatch deletes the file. */
        fun save(input: InputStream, dir: File, remote: RemoteVersion): File? {
            dir.mkdirs()
            val target = File(dir, remote.url)
            val digest = MessageDigest.getInstance("SHA-256")
            var total = 0L
            try {
                input.use { source ->
                    FileOutputStream(target).use { out ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val n = source.read(buffer)
                            if (n < 0) break
                            total += n
                            if (total > remote.size) throw IOException("longer than version.json size")
                            digest.update(buffer, 0, n)
                            out.write(buffer, 0, n)
                        }
                    }
                }
            } catch (e: IOException) {
                target.delete()
                return null
            }
            val hex = digest.digest().joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }
            if (total != remote.size || hex != remote.sha256) {
                target.delete()
                return null
            }
            return target
        }

        /** The next launch clears `cacheDir/updates` (an installed or abandoned APK is never kept). */
        fun clear(dir: File) {
            dir.listFiles()?.forEach { it.delete() }
        }
    }
}
