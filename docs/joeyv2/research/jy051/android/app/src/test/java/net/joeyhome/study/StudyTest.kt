package net.joeyhome.study

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StudyTest {
    private val streams = listOf(
        StreamFact(0, "Video", "hevc", false),
        StreamFact(1, "Audio", "eac3", false),
        StreamFact(2, "Audio", "aac", false),
        StreamFact(3, "Subtitle", "subrip", false),
        StreamFact(4, "Subtitle", "pgssub", false),
        StreamFact(5, "Subtitle", "subrip", true),
    )

    @Test fun twelveItems() {
        assertEquals((1..12).toList(), Study.ITEMS.map { it.n })
        assertTrue(Study.ITEMS.all { Regex("^[0-9a-f]{32}$").matches(it.id) })
    }

    @Test fun positionsCountOwnStreamsOnly() {
        assertEquals(1, Study.internalPosition(streams, "Audio", 2))
        assertEquals(1, Study.internalPosition(streams, "Subtitle", 4))
        assertEquals(-1, Study.internalPosition(streams, "Subtitle", 5))
        assertTrue(Study.isExternal(streams, 5))
        assertFalse(Study.isExternal(streams, 3))
    }

    @Test fun methodFromReasons() {
        val base = "/videos/x/master.m3u8?ApiKey=0123456789abcdef0123456789abcdef&TranscodeReasons="
        assertEquals("DirectPlay", Study.method(true, false, null).first)
        assertEquals("Remux", Study.method(false, false, base + "ContainerNotSupported").first)
        assertEquals("Remux+Audio", Study.method(false, false, base + "ContainerNotSupported%2CAudioCodecNotSupported").first)
        assertEquals("Transcode", Study.method(false, false, base + "SubtitleCodecNotSupported").first)
        assertEquals(listOf("ContainerNotSupported", "AudioCodecNotSupported"),
            Study.method(false, false, base + "ContainerNotSupported,AudioCodecNotSupported").second)
    }

    @Test fun codecsFromMimes() {
        val mimes = setOf("video/avc", "video/hevc", "audio/mp4a-latm", "audio/ac3", "audio/eac3")
        assertEquals(listOf("h264", "hevc"), Study.videoCodecs(mimes))
        assertEquals(listOf("aac", "ac3", "eac3"), Study.audioCodecs(mimes, false))
        assertTrue("dts" in Study.audioCodecs(mimes, true))
    }

    @Test fun medianAndScrub() {
        assertEquals(2.0, Study.median(listOf(3L, 1L, 2L))!!, 0.0)
        assertEquals(1.5, Study.median(listOf(2L, 1L))!!, 0.0)
        val tok = "0123456789abcdef0123456789abcdef"
        val out = Study.scrub("a $tok https://x.example/y?ApiKey=$tok b", tok)
        assertFalse(out.contains(tok))
        assertFalse(out.contains("https://"))
    }
}
