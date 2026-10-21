package net.joeyhome.media

import java.io.File
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.format.ResolverStyle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * WP-B8 step 2: Gradle read tv/VERSION (the build's BuildConfig equals the file) and the file obeys D-P9. Gradle-free
 * logic: the parse below is plain Kotlin over the real file (unit tests run with the module dir as working dir).
 */
class VersionFileTest {
    private val file = listOf(File("../VERSION"), File("tv/VERSION")).first { it.isFile }
    private val values = file.readLines().map { it.trim() }
        .filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
        .associate { it.substringBefore("=").trim() to it.substringAfter("=").trim() }
    private val codeRegex = Regex("^20\\d{6}(0[1-9]|[1-9]\\d)$")

    private fun realDate(code: String): Boolean = try {
        LocalDate.parse(code.take(8), DateTimeFormatter.ofPattern("uuuuMMdd").withResolverStyle(ResolverStyle.STRICT))
        true
    } catch (e: DateTimeParseException) {
        false
    }

    @Test
    fun buildConfigComesFromTheFile() {
        assertEquals(values.getValue("versionName"), BuildConfig.VERSION_NAME)
        assertEquals(values.getValue("versionCode").toInt(), BuildConfig.VERSION_CODE)
        assertEquals(values.getValue("minVersionCode").toInt(), BuildConfig.MIN_VERSION_CODE)
    }

    @Test
    fun theFileObeysTheRules() {
        assertEquals(setOf("versionName", "versionCode", "minVersionCode"), values.keys)
        assertTrue(Regex("^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$").matches(values.getValue("versionName")))
        for (key in listOf("versionCode", "minVersionCode")) {
            val code = values.getValue(key)
            if (!codeRegex.matches(code) || !realDate(code) || code.toLong() > 2_100_000_000L) fail("$key $code")
        }
        assertTrue(values.getValue("minVersionCode").toLong() <= values.getValue("versionCode").toLong())
    }

    @Test
    fun theDateCheckIsStrict() {
        assertTrue(realDate("2026102101"))
        assertTrue(!realDate("2026132101") && !realDate("2026023001"))
    }
}
