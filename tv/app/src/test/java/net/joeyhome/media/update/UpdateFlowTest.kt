package net.joeyhome.media.update

import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import java.nio.file.Files
import java.security.MessageDigest
import net.joeyhome.media.policy.Origin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** WP-B8 step 7 with fake ports and an injected clock: throttle, URL use, and "nothing unverified is installed". */
class UpdateFlowTest {
    private val apkBytes = ByteArray(200_000) { (it % 251).toByte() }
    private val sha = MessageDigest.getInstance("SHA-256").digest(apkBytes)
        .joinToString("") { (it.toInt() and 0xff).toString(16).padStart(2, '0') }
    private val public = Origin.of("https://media.joeyhome.net")!!

    private fun versionJson(sha256: String = sha, size: Int = apkBytes.size) = """{"version": "1.4.0",
        "versionCode": 2026110302, "min_version": 2026102101, "url": "joey-media-1.4.0-2026110302.apk",
        "sha256": "$sha256", "notes": "n", "size": $size, "published": "2026-11-03T01:02:03Z"}"""

    private class FakePorts(var body: String?, var apk: ByteArray) : UpdatePorts {
        val fetched = mutableListOf<String>()
        val opened = mutableListOf<String>()
        val installed = mutableListOf<File>()
        override fun fetch(url: String): String? = body.also { fetched += url }
        override fun open(url: String): InputStream = ByteArrayInputStream(apk).also { opened += url }
        override fun install(apk: File) {
            installed += apk
        }
    }

    private fun tempDir(): File = Files.createTempDirectory("joeytv-updates").toFile()

    @Test
    fun throttledWithinADayMakesNoRequest() {
        val ports = FakePorts(versionJson(), apkBytes)
        var now = 10_000L
        val flow = UpdateFlow(ports, 2026102101) { now }
        assertEquals(CheckResult.Skipped, flow.check(public, lastSuccessMs = now - 1_000))
        assertTrue(ports.fetched.isEmpty())
        now += UpdatePolicy.CHECK_INTERVAL_MS
        val done = flow.check(public, lastSuccessMs = 10_000L - 1_000) as CheckResult.Done
        assertEquals(listOf("https://media.joeyhome.net/app/version.json"), ports.fetched)
        assertEquals(now, done.checkedAt)
        assertTrue(done.decision is UpdateDecision.Offer)
    }

    @Test
    fun manualCheckIgnoresTheThrottle() {
        val ports = FakePorts(versionJson(), apkBytes)
        val flow = UpdateFlow(ports, 2026102101) { 5_000L }
        assertTrue(flow.check(public, lastSuccessMs = 4_999, force = true) is CheckResult.Done)
    }

    @Test
    fun anUnreachableOrBrokenVersionJsonFailsSilently() {
        val flow = UpdateFlow(FakePorts(null, apkBytes), 2026102101) { 0L }
        assertEquals(CheckResult.Failed, flow.check(public, null))
        val broken = UpdateFlow(FakePorts("{\"version\": \"1.4.0\"}", apkBytes), 2026102101) { 0L }
        assertEquals(CheckResult.Failed, broken.check(public, null))
    }

    @Test
    fun verifiedDownloadIsInstalledFromTheResolvedUrl() {
        val ports = FakePorts(versionJson(), apkBytes)
        val flow = UpdateFlow(ports, 2026102101) { 0L }
        val done = flow.check(Origin.of("http://127.0.0.1:8850")!!, null) as CheckResult.Done
        val offer = done.decision as UpdateDecision.Offer
        val dir = tempDir()
        val result = flow.downloadAndInstall(offer.remote, done.versionUrl, dir)
        assertTrue(result is DownloadResult.Installing)
        assertEquals(listOf("http://127.0.0.1:8850/app/joey-media-1.4.0-2026110302.apk"), ports.opened)
        assertEquals(1, ports.installed.size)
        assertTrue(apkBytes.contentEquals(ports.installed[0].readBytes()))
    }

    @Test
    fun hashMismatchDeletesTheFileAndNeverInstalls() {
        val ports = FakePorts(versionJson(), apkBytes.copyOf().also { it[100] = 7 })
        val flow = UpdateFlow(ports, 2026102101) { 0L }
        val done = flow.check(public, null) as CheckResult.Done
        val dir = tempDir()
        val result = flow.downloadAndInstall((done.decision as UpdateDecision.Offer).remote, done.versionUrl, dir)
        assertTrue(result is DownloadResult.Failed)
        assertTrue(ports.installed.isEmpty())
        assertFalse(File(dir, "joey-media-1.4.0-2026110302.apk").exists())
    }

    @Test
    fun aLongerBodyThanTheDeclaredSizeIsRejected() {
        val ports = FakePorts(versionJson(size = apkBytes.size - 1), apkBytes)
        val flow = UpdateFlow(ports, 2026102101) { 0L }
        val done = flow.check(public, null) as CheckResult.Done
        val result = flow.downloadAndInstall((done.decision as UpdateDecision.Offer).remote, done.versionUrl, tempDir())
        assertTrue(result is DownloadResult.Failed)
        assertTrue(ports.installed.isEmpty())
    }

    @Test
    fun anInstallerErrorIsAFailureNotACrash() {
        val ports = object : UpdatePorts {
            override fun fetch(url: String) = versionJson()
            override fun open(url: String): InputStream = ByteArrayInputStream(apkBytes)
            override fun install(apk: File) {
                throw SecurityException("no permission")
            }
        }
        val flow = UpdateFlow(ports, 2026102101) { 0L }
        val done = flow.check(public, null) as CheckResult.Done
        val result = flow.downloadAndInstall((done.decision as UpdateDecision.Offer).remote, done.versionUrl, tempDir())
        assertEquals(DownloadResult.Failed("install: SecurityException"), result)
    }

    @Test
    fun clearEmptiesTheUpdatesDir() {
        val dir = tempDir()
        File(dir, "old.apk").writeBytes(byteArrayOf(1))
        UpdateFlow.clear(dir)
        assertEquals(0, dir.listFiles()!!.size)
    }
}
