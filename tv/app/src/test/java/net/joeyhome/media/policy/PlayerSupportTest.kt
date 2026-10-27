package net.joeyhome.media.policy

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** JY-057: the fallback rules, track plans, the DeviceProfile and the words on screen. */
class PlayerSupportTest {
    private val jf = HostConfig.DEFAULT.jellyfin

    // ---- fallback: the Jellyfin app for one release (JY-050 Q7 A) ----

    @Test
    fun aFirstNetworkFailureOrRetryableUpstreamErrorIsRetriedOnce() {
        assertEquals(StartStep.RETRY, PlayerFallback.afterStartFailure(null, attempt = 0))
        assertEquals(StartStep.RETRY, PlayerFallback.afterStartFailure(ApiError(504, "upstream_timeout", true), 0))
        assertEquals(StartStep.RETRY, PlayerFallback.afterStartFailure(ApiError(502, "upstream_unreachable", true), 0))
        assertEquals(StartStep.HAND_OFF, PlayerFallback.afterStartFailure(null, attempt = 1))
        assertEquals(StartStep.HAND_OFF, PlayerFallback.afterStartFailure(ApiError(504, "upstream_timeout", true), 1))
    }

    @Test
    fun everythingElseHandsOffToJellyfin() {
        for (e in listOf(ApiError(404, null, false), ApiError(401, "not_signed_in", false), ApiError(403, "not_allowed", false),
            ApiError(409, "cannot_play", false), ApiError(503, "not_configured", false), ApiError(502, "upstream_refused", false),
            ApiError(303, null, false), ApiError(500, null, true))) {
            assertEquals("$e", StartStep.HAND_OFF, PlayerFallback.afterStartFailure(e, 0))
        }
    }

    @Test
    fun aLostSessionRestartsAndOtherHeartbeatFailuresAreIgnored() {
        assertEquals(ProgressStep.RESTART, PlayerFallback.afterProgressFailure(ApiError(404, "session_unknown", false)))
        assertEquals(ProgressStep.IGNORE, PlayerFallback.afterProgressFailure(ApiError(404, null, false)))
        assertEquals(ProgressStep.IGNORE, PlayerFallback.afterProgressFailure(ApiError(504, "upstream_timeout", true)))
        assertEquals(ProgressStep.IGNORE, PlayerFallback.afterProgressFailure(null))
    }

    // ---- tracks: in the player for direct play, a new session for HLS ----

    private fun track(index: Int, audio: Boolean, external: Boolean = false, text: Boolean = true, delivery: String? = null,
                      url: String? = null) = PlayTrack(index, audio, "t$index", "eng", "c", false, false, external, text, delivery, url)

    private val audio = listOf(track(1, true), track(2, true))
    private val vtt = "https://jellyfin.joeyhome.net:8443/Videos/x/src1/Subtitles/5/0/Stream.vtt"
    private val subs = listOf(track(3, false, delivery = "embed"), track(4, false, text = false, delivery = "embed"),
        track(5, false, external = true, delivery = "external", url = vtt))

    @Test
    fun directPlaySwitchesInThePlayerHlsStartsANewSession() {
        assertEquals(SwitchWay.IN_PLAYER, TrackPlan.way("direct"))
        assertEquals(SwitchWay.RESTART, TrackPlan.way("remux"))
        assertEquals(SwitchWay.RESTART, TrackPlan.way("transcode"))
    }

    @Test
    fun directPlayPicksTheNthEmbeddedTrackOfItsType() {
        assertEquals(TrackSelection(1, TextPick.Off), TrackPlan.selection("direct", audio, subs, 2, -1))
        assertEquals(TrackSelection(0, TextPick.Embedded(1)), TrackPlan.selection("direct", audio, subs, 1, 4))
        assertEquals(TrackSelection(null, TextPick.External(TrackPlan.externalId(5))), TrackPlan.selection("direct", audio, subs, null, 5))
        assertEquals(TrackSelection(null, TextPick.Off), TrackPlan.selection("direct", audio, subs, 9, 9))
    }

    @Test
    fun hlsLeavesAudioToJellyfinAndPicksTheDeliveredSubtitle() {
        assertEquals(TrackSelection(null, TextPick.Off), TrackPlan.selection("remux", audio, subs, 2, -1))
        assertEquals(TrackSelection(null, TextPick.External(TrackPlan.externalId(5))), TrackPlan.selection("remux", audio, subs, 1, 5))
        val inStream = listOf(track(6, false, delivery = "hls"))
        assertEquals(TrackSelection(null, TextPick.InStream), TrackPlan.selection("transcode", audio, inStream, 1, 6))
        val burned = listOf(track(7, false, text = false, delivery = "encode"))
        assertEquals(TrackSelection(null, TextPick.Off), TrackPlan.selection("transcode", audio, burned, 1, 7))
    }

    @Test
    fun onlyExternalTextOnTheJellyfinOriginIsSideLoaded() {
        val offOrigin = track(8, false, external = true, delivery = "external", url = "https://evil.example/s.vtt")
        val noUrl = track(9, false, external = true, delivery = "external")
        assertEquals(listOf(5), TrackPlan.sideloads(subs + offOrigin + noUrl, jf).map { it.index })
    }

    @Test
    fun subtitleMimeComesFromTheExtension() {
        assertEquals("text/vtt", TrackPlan.subtitleMime("$vtt?x=1"))
        assertEquals("application/x-subrip", TrackPlan.subtitleMime("https://h/Stream.srt"))
        assertEquals("text/x-ssa", TrackPlan.subtitleMime("https://h/Stream.ass"))
        assertEquals("text/vtt", TrackPlan.subtitleMime("https://h/Stream"))
    }

    // ---- the DeviceProfile: what this TV decodes ----

    @Test
    fun codecsComeFromTheTvsDecoders() {
        val mimes = setOf("video/avc", "video/hevc", "audio/mp4a-latm", "audio/ac3", "audio/eac3", "audio/opus")
        assertEquals(listOf("h264", "hevc"), DeviceProfile.videoCodecs(mimes))
        assertEquals(listOf("aac", "ac3", "eac3", "opus"), DeviceProfile.audioCodecs(mimes))
        // 2026-10-27 TV session (row 9): replaced `"dts" in audioCodecs(setOf("audio/vnd.dts.hd"))`; a listed DTS decoder
        // no longer counts (the TCL lists one and stalls), see the passthrough tests below
        assertFalse("dts" in DeviceProfile.audioCodecs(setOf("audio/vnd.dts.hd")))
        assertEquals(listOf("h264"), DeviceProfile.videoCodecs(emptySet()))
        assertEquals(listOf("aac"), DeviceProfile.audioCodecs(emptySet()))
    }

    // a capability list like the TCL's (JY-057 TV session, 2026-10-27): DTS and TrueHD decoders listed, no passthrough sink
    private val tcl = setOf("video/avc", "video/hevc", "audio/mp4a-latm", "audio/mpeg", "audio/ac3", "audio/eac3",
        "audio/vnd.dts", "audio/vnd.dts.hd", "audio/true-hd")

    @Test
    fun aListedDtsOrTrueHdDecoderIsNotTrusted() {
        val audio = DeviceProfile.audioCodecs(tcl, passthroughEncodings = emptySet())
        assertEquals(listOf("aac", "mp3", "ac3", "eac3"), audio)
        val direct = DeviceProfile.build(DeviceProfile.videoCodecs(tcl), audio)
            .getJSONArray("DirectPlayProfiles").getJSONObject(0).getString("AudioCodec")
        assertFalse(direct.contains("dts") || direct.contains("truehd"))   // so Jellyfin converts the audio
    }

    @Test
    fun passthroughToAnHdmiSinkAddsDtsTrueHdAndDolby() {
        // AudioFormat encodings: 5 AC-3, 6 E-AC-3, 7 DTS, 8 DTS-HD, 14 TrueHD, 18 E-AC-3 JOC; 2 (PCM) means nothing here
        assertEquals(listOf("aac", "ac3", "eac3", "dts", "truehd"),
            DeviceProfile.audioCodecs(setOf("audio/mp4a-latm"), setOf(2, 5, 18, 8, 14)))
        assertEquals(listOf("aac", "dts"), DeviceProfile.audioCodecs(setOf("audio/mp4a-latm"), setOf(7)))
        assertEquals(listOf("aac"), DeviceProfile.audioCodecs(emptySet(), setOf(2)))
    }

    @Test
    fun theProfileDirectPlaysWhatItDecodesAndAsksForHlsOtherwise() {
        val p: JSONObject = DeviceProfile.build(listOf("h264", "hevc", "av1"), listOf("aac", "ac3", "eac3"))
        assertEquals("Joey TV", p.getString("Name"))
        val direct = p.getJSONArray("DirectPlayProfiles").getJSONObject(0)
        assertEquals("Video", direct.getString("Type"))
        assertTrue(direct.getString("Container").split(",").containsAll(listOf("mkv", "mp4")))
        assertEquals("h264,hevc,av1", direct.getString("VideoCodec"))
        assertEquals("aac,ac3,eac3", direct.getString("AudioCodec"))
        val hls = p.getJSONArray("TranscodingProfiles").getJSONObject(0)
        assertEquals("hls", hls.getString("Protocol"))
        assertEquals("Streaming", hls.getString("Context"))
        assertEquals("hevc,h264", hls.getString("VideoCodec"))
        assertEquals("aac,ac3,eac3", hls.getString("AudioCodec"))
        val subs = p.getJSONArray("SubtitleProfiles")
        val methods = (0 until subs.length()).map { subs.getJSONObject(it) }.map { it.getString("Format") to it.getString("Method") }
        assertTrue(("pgssub" to "Embed") in methods && ("subrip" to "Embed") in methods && ("ass" to "Embed") in methods)
        assertTrue(("vtt" to "External") in methods && ("srt" to "External") in methods)
        assertFalse(("pgssub" to "External") in methods)
        assertFalse(p.toString().contains("dts"))
    }

    @Test
    fun noHevcDecoderMeansH264Hls() {
        val hls = DeviceProfile.build(listOf("h264"), listOf("aac")).getJSONArray("TranscodingProfiles").getJSONObject(0)
        assertEquals("h264", hls.getString("VideoCodec"))
        assertEquals("aac", hls.getString("AudioCodec"))
    }

    // ---- words on screen ----

    @Test
    fun timeWords() {
        assertEquals("0:00", PlayerText.time(0))
        assertEquals("0:00", PlayerText.time(-5))
        assertEquals("4:05", PlayerText.time(245_999))
        assertEquals("31:12", PlayerText.time(1_872_000))
        assertEquals("1:02:03", PlayerText.time(3_723_000))
        assertEquals("31:12 / 52:40", PlayerText.progress(1_872_000, 3_160_000))
        assertEquals("31:12", PlayerText.progress(1_872_000, -1))
    }

    @Test
    fun methodResumeFirstFrameAndCountdownWords() {
        assertEquals("Direct play", PlayerText.method("direct"))
        assertEquals("Remux", PlayerText.method("remux"))
        assertEquals("Transcode", PlayerText.method("transcode"))
        assertEquals("Resumed at 23:41", PlayerText.resumed(1_421_000))
        assertEquals("First frame 2.3 s after Play", PlayerText.firstFrame(2_340))
        assertEquals("Next episode in 5 s", PlayerText.countdown(5))
    }

    @Test
    fun theChapterLineFollowsThePosition() {
        val ch = listOf(Chapter("Opening", 0), Chapter("Harbour", 60_000), Chapter("The Breakwater", 120_000))
        assertEquals("Ch 1 of 3 · Opening", PlayerText.chapter(ch, 59_999))
        assertEquals("Ch 2 of 3 · Harbour", PlayerText.chapter(ch, 60_000))
        assertEquals("Ch 3 of 3 · The Breakwater", PlayerText.chapter(ch, 9_000_000))
        assertNull(PlayerText.chapter(emptyList(), 1_000))
        assertEquals("Ch 2 of 2", PlayerText.chapter(listOf(Chapter("", 0), Chapter("", 10)), 20))
    }

    @Test
    fun theTitleIsThePagesOwnWithoutTheBrand() {
        assertEquals("Library Film", PlayerText.pageTitle("Library Film · Joey Media"))
        assertEquals("Sample Show · S1 · E2", PlayerText.pageTitle("Sample Show · S1 · E2 · Joey"))
        assertEquals("S2 · E3 · The Breakwater", PlayerText.pageTitle("S2 · E3 · The Breakwater"))
        assertEquals("", PlayerText.pageTitle("Joey Media"))
        assertEquals("", PlayerText.pageTitle("https://media.joeyhome.net/media/item/x"))
        assertEquals("", PlayerText.pageTitle(null))
    }

    @Test
    fun trackLabels() {
        assertEquals("English AAC 2.0", PlayerText.track(PlayTrack(1, true, "English AAC 2.0", "eng", "aac", true, false, false, true, null, null)))
        assertEquals("ITA", PlayerText.track(PlayTrack(2, true, null, "ita", "eac3", false, false, false, true, null, null)))
        assertEquals("Track 3", PlayerText.track(PlayTrack(3, false, " ", null, null, false, false, false, true, null, null)))
        assertEquals("Off", PlayerText.subtitleOff())
    }
}
