package net.joeyhome.media.policy

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** JY-057 look A on TV: two focus rows (bar, buttons), the Audio & subtitles pop-up, up next, auto-hide, media keys. */
class PlayerUiTest {
    private val t0 = 10_000L
    private val start = PlayerUi.initial(t0, hasNext = true)
    private val hidden = start.copy(overlay = PlayerOverlay.NONE)
    private val onBar = start.copy(row = FocusRow.BAR)

    private fun key(state: PlayerUiState, code: Int, now: Long = t0) = PlayerUi.onKey(state, code, now)

    @Test
    fun theControlsShowAtTheStartOnPlayPause() {
        assertEquals(PlayerOverlay.CONTROLS, start.overlay)
        assertEquals(FocusRow.BUTTONS, start.row)
        assertEquals(PlayerButton.PLAY_PAUSE, start.button)
    }

    // ---- controls hidden: any key shows them, Left / Right seek ----

    @Test
    fun hiddenLeftSeeksBackTenSecondsOnTheBar() {
        val step = key(hidden, KeyEvent.KEYCODE_DPAD_LEFT)
        assertEquals(PlayerAction.SeekBy(-10_000L), step.action)
        assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
        assertEquals(FocusRow.BAR, step.state.row)
    }

    @Test
    fun hiddenRightSeeksForwardThirtySecondsOnTheBar() {
        val step = key(hidden, KeyEvent.KEYCODE_DPAD_RIGHT)
        assertEquals(PlayerAction.SeekBy(30_000L), step.action)
        assertEquals(FocusRow.BAR, step.state.row)
    }

    @Test
    fun hiddenOkShowsTheControlsOnPlayPauseWithoutPausing() {
        for (code in listOf(KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER)) {
            val step = key(hidden.copy(button = PlayerButton.TRACKS), code)
            assertEquals(PlayerAction.None, step.action)
            assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
            assertEquals(FocusRow.BUTTONS, step.state.row)
            assertEquals(PlayerButton.PLAY_PAUSE, step.state.button)
        }
    }

    @Test
    fun hiddenUpOrDownShowsTheControlsOnTheBar() {
        for (code in listOf(KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN)) {
            val step = key(hidden, code)
            assertEquals(PlayerAction.None, step.action)
            assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
            assertEquals(FocusRow.BAR, step.state.row)
        }
    }

    // ---- row 1: the seek bar ----

    @Test
    fun theBarSeeksMinusTenPlusThirty() {
        assertEquals(PlayerAction.SeekBy(-10_000L), key(onBar, KeyEvent.KEYCODE_DPAD_LEFT).action)
        assertEquals(PlayerAction.SeekBy(30_000L), key(onBar, KeyEvent.KEYCODE_DPAD_RIGHT).action)
        assertEquals(FocusRow.BAR, key(onBar, KeyEvent.KEYCODE_DPAD_RIGHT).state.row)
    }

    @Test
    fun okOnTheBarPlaysOrPauses() {
        assertEquals(PlayerAction.TogglePlay, key(onBar, KeyEvent.KEYCODE_DPAD_CENTER).action)
    }

    @Test
    fun downDropsToTheButtonsAndUpClimbsBack() {
        val down = key(onBar, KeyEvent.KEYCODE_DPAD_DOWN).state
        assertEquals(FocusRow.BUTTONS, down.row)
        assertEquals(FocusRow.BAR, key(down, KeyEvent.KEYCODE_DPAD_UP).state.row)
        assertEquals(FocusRow.BAR, key(onBar, KeyEvent.KEYCODE_DPAD_UP).state.row)
        assertEquals(FocusRow.BUTTONS, key(down, KeyEvent.KEYCODE_DPAD_DOWN).state.row)
    }

    // ---- row 2: the buttons ----

    @Test
    fun theButtonsInOrderWithNextOnlyWhenThereIsOne() {
        assertEquals(
            listOf(PlayerButton.PLAY_PAUSE, PlayerButton.BACK_10, PlayerButton.FORWARD_30, PlayerButton.TRACKS, PlayerButton.NEXT),
            PlayerUi.buttons(start),
        )
        assertEquals(
            listOf(PlayerButton.PLAY_PAUSE, PlayerButton.BACK_10, PlayerButton.FORWARD_30, PlayerButton.TRACKS),
            PlayerUi.buttons(start.copy(hasNext = false)),
        )
    }

    @Test
    fun leftRightWalkTheButtonsAndStopAtTheEnds() {
        var s = start
        assertEquals(PlayerButton.PLAY_PAUSE, key(s, KeyEvent.KEYCODE_DPAD_LEFT).state.button)
        for (expected in listOf(PlayerButton.BACK_10, PlayerButton.FORWARD_30, PlayerButton.TRACKS, PlayerButton.NEXT, PlayerButton.NEXT)) {
            s = key(s, KeyEvent.KEYCODE_DPAD_RIGHT).state
            assertEquals(expected, s.button)
        }
        val noNext = start.copy(hasNext = false, button = PlayerButton.TRACKS)
        assertEquals(PlayerButton.TRACKS, key(noNext, KeyEvent.KEYCODE_DPAD_RIGHT).state.button)
    }

    @Test
    fun okPressesTheFocusedButton() {
        fun press(b: PlayerButton) = key(start.copy(button = b), KeyEvent.KEYCODE_DPAD_CENTER)
        assertEquals(PlayerAction.TogglePlay, press(PlayerButton.PLAY_PAUSE).action)
        assertEquals(PlayerAction.SeekBy(-10_000L), press(PlayerButton.BACK_10).action)
        assertEquals(PlayerAction.SeekBy(30_000L), press(PlayerButton.FORWARD_30).action)
        assertEquals(PlayerAction.PlayNext, press(PlayerButton.NEXT).action)
        val tracks = press(PlayerButton.TRACKS)
        assertEquals(PlayerAction.None, tracks.action)
        assertEquals(PlayerOverlay.POPUP, tracks.state.overlay)
        assertEquals(PopupColumn.AUDIO, tracks.state.column)
    }

    // ---- the Audio & subtitles pop-up ----

    private val withTracks = PlayerUi.withTracks(start, audio = listOf(1, 2), subtitles = listOf(3, 4), audioIndex = 2, subtitleIndex = -1)
    private val popup = withTracks.copy(overlay = PlayerOverlay.POPUP, column = PopupColumn.AUDIO, button = PlayerButton.TRACKS)

    @Test
    fun thePopUpListsOffFirstAndOpensOnTheCurrentTracks() {
        assertEquals(listOf(1, 2), withTracks.audio)
        assertEquals(listOf(PlayerUi.OFF, 3, 4), withTracks.subtitles)
        assertEquals(1, withTracks.audioCursor)      // index 2 is the second audio track
        assertEquals(0, withTracks.subtitleCursor)   // Off
        val unknown = PlayerUi.withTracks(start, listOf(1, 2), listOf(3), audioIndex = null, subtitleIndex = 9)
        assertEquals(0, unknown.audioCursor)
        assertEquals(0, unknown.subtitleCursor)
    }

    @Test
    fun upDownWalkAListAndStopAtTheEnds() {
        val up = key(popup, KeyEvent.KEYCODE_DPAD_UP).state
        assertEquals(0, up.audioCursor)
        assertEquals(0, key(up, KeyEvent.KEYCODE_DPAD_UP).state.audioCursor)
        assertEquals(1, key(up, KeyEvent.KEYCODE_DPAD_DOWN).state.audioCursor)
        assertEquals(1, key(popup, KeyEvent.KEYCODE_DPAD_DOWN).state.audioCursor)
    }

    @Test
    fun leftRightSwapAudioAndSubtitles() {
        val subs = key(popup, KeyEvent.KEYCODE_DPAD_RIGHT).state
        assertEquals(PopupColumn.SUBTITLES, subs.column)
        assertEquals(PopupColumn.SUBTITLES, key(subs, KeyEvent.KEYCODE_DPAD_RIGHT).state.column)
        assertEquals(PopupColumn.AUDIO, key(subs, KeyEvent.KEYCODE_DPAD_LEFT).state.column)
        assertEquals(2, key(key(subs, KeyEvent.KEYCODE_DPAD_DOWN).state, KeyEvent.KEYCODE_DPAD_DOWN).state.subtitleCursor)
    }

    // 2026-10-27 TV session (row 4): replaces okPicksAndClosesWithFocusBackOnItsButton; a pick keeps the pop-up open
    @Test
    fun okPicksAndThePopUpStaysOpenOnThePick() {
        val audio = key(key(popup, KeyEvent.KEYCODE_DPAD_UP).state, KeyEvent.KEYCODE_DPAD_CENTER)
        assertEquals(PlayerAction.PickAudio(1), audio.action)
        assertEquals(PlayerOverlay.POPUP, audio.state.overlay)
        assertEquals(PopupColumn.AUDIO, audio.state.column)
        assertEquals(0, audio.state.audioCursor)
        // the activity then records the new track: the tick (playing track) and the cursor move, the pop-up stays
        val ticked = PlayerUi.withTracks(audio.state, audio.state.audio, listOf(3, 4), audioIndex = 1, subtitleIndex = -1)
        assertEquals(PlayerOverlay.POPUP, ticked.overlay)
        assertEquals(0, ticked.audioCursor)
        val subs = key(key(key(popup, KeyEvent.KEYCODE_DPAD_RIGHT).state, KeyEvent.KEYCODE_DPAD_DOWN).state, KeyEvent.KEYCODE_ENTER)
        assertEquals(PlayerAction.PickSubtitle(3), subs.action)
        val off = key(key(popup, KeyEvent.KEYCODE_DPAD_RIGHT).state, KeyEvent.KEYCODE_DPAD_CENTER)
        assertEquals(PlayerAction.PickSubtitle(PlayerUi.OFF), off.action)
    }

    @Test
    fun anEmptyAudioListPicksNothing() {
        val none = PlayerUi.withTracks(start, emptyList(), emptyList(), null, -1).copy(overlay = PlayerOverlay.POPUP)
        val step = key(none, KeyEvent.KEYCODE_DPAD_CENTER)
        assertEquals(PlayerAction.None, step.action)
        assertEquals(PlayerOverlay.POPUP, step.state.overlay)   // 2026-10-27 TV session: the pop-up stays open
    }

    @Test
    fun backClosesThePopUpOntoItsButton() {
        val step = key(popup, KeyEvent.KEYCODE_BACK)
        assertEquals(PlayerAction.None, step.action)
        assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
        assertEquals(FocusRow.BUTTONS, step.state.row)
        assertEquals(PlayerButton.TRACKS, step.state.button)
    }

    // ---- media keys ----

    @Test
    fun mediaKeysPlayPauseSeekNextAndStop() {
        assertEquals(PlayerAction.TogglePlay, key(start, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE).action)
        assertEquals(PlayerAction.Play, key(start, KeyEvent.KEYCODE_MEDIA_PLAY).action)
        assertEquals(PlayerAction.Pause, key(start, KeyEvent.KEYCODE_MEDIA_PAUSE).action)
        assertEquals(PlayerAction.SeekBy(30_000L), key(start, KeyEvent.KEYCODE_MEDIA_FAST_FORWARD).action)
        assertEquals(PlayerAction.SeekBy(-10_000L), key(start, KeyEvent.KEYCODE_MEDIA_REWIND).action)
        assertEquals(PlayerAction.PlayNext, key(start, KeyEvent.KEYCODE_MEDIA_NEXT).action)
        assertEquals(PlayerAction.None, key(start.copy(hasNext = false), KeyEvent.KEYCODE_MEDIA_NEXT).action)
        assertEquals(PlayerAction.ReturnToJoey, key(start, KeyEvent.KEYCODE_MEDIA_STOP).action)
    }

    @Test
    fun aMediaKeyFromHiddenShowsTheControls() {
        val step = key(hidden, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)
        assertEquals(PlayerAction.TogglePlay, step.action)
        assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
    }

    @Test
    fun thePlayerHandlesItsKeysAndLeavesVolumeAndHomeAlone() {
        for (code in listOf(KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_BACK,
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_MEDIA_STOP)) {
            assertTrue("$code", PlayerUi.handles(code))
        }
        for (code in listOf(KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN, KeyEvent.KEYCODE_VOLUME_MUTE,
            KeyEvent.KEYCODE_HOME, KeyEvent.KEYCODE_POWER)) {
            assertFalse("$code", PlayerUi.handles(code))
        }
    }

    @Test
    fun everyKeyRecordsTheInputTime() {
        assertEquals(t0 + 7, key(start, KeyEvent.KEYCODE_DPAD_RIGHT, t0 + 7).state.lastInputMs)
    }

    // ---- auto-hide, up next, the countdown ----

    @Test
    fun theControlsHideAfterFiveSecondsOfPlaying() {
        val s = start.copy(lastInputMs = t0)
        assertEquals(PlayerOverlay.CONTROLS, PlayerUi.onTick(s, t0 + 4_999, true, 0, 3_600_000).state.overlay)
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(s, t0 + 5_000, true, 0, 3_600_000).state.overlay)
        assertEquals(PlayerOverlay.CONTROLS, PlayerUi.onTick(s, t0 + 60_000, false, 0, 3_600_000).state.overlay)  // paused: stays
        val pop = s.copy(overlay = PlayerOverlay.POPUP)
        assertEquals(PlayerOverlay.POPUP, PlayerUi.onTick(pop, t0 + 60_000, true, 0, 3_600_000).state.overlay)
    }

    @Test
    fun theUpNextCardShowsInTheLastMinuteWhileTheControlsAreHidden() {
        val dur = 3_000_000L
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(hidden, t0, true, dur - 60_001, dur).state.overlay)
        val card = PlayerUi.onTick(hidden, t0, true, dur - 60_000, dur).state
        assertEquals(PlayerOverlay.UP_NEXT, card.overlay)
        assertEquals(UpNextChoice.PLAY_NOW, card.upNextChoice)
        assertEquals(PlayerOverlay.CONTROLS, PlayerUi.onTick(start.copy(lastInputMs = t0), t0, true, dur - 1_000, dur).state.overlay)
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(hidden.copy(hasNext = false), t0, true, dur - 1_000, dur).state.overlay)
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(hidden, t0, true, 0, 0).state.overlay)   // unknown duration
    }

    @Test
    fun seekingBackOutOfTheLastMinuteHidesTheCard() {
        val card = hidden.copy(overlay = PlayerOverlay.UP_NEXT)
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(card, t0, true, 1_000, 3_000_000).state.overlay)
    }

    // 2026-10-27 TV session (row 7): Right on the card is Watch credits at once (look A "Right is Watch credits"); the
    // old two-step focus move to a Watch credits button left the card on screen
    @Test
    fun theCardOkPlaysNowRightIsWatchCreditsBackIsJoey() {
        val card = hidden.copy(overlay = PlayerOverlay.UP_NEXT)
        assertEquals(PlayerAction.PlayNext, key(card, KeyEvent.KEYCODE_DPAD_CENTER).action)
        val dismissed = key(card, KeyEvent.KEYCODE_DPAD_RIGHT)
        assertEquals(PlayerAction.None, dismissed.action)
        assertEquals(PlayerOverlay.NONE, dismissed.state.overlay)
        assertTrue(dismissed.state.upNextDismissed)
        assertNull(dismissed.state.countdownFromMs)
        assertEquals(PlayerOverlay.NONE, PlayerUi.onTick(dismissed.state, t0, true, 2_999_000, 3_000_000).state.overlay)
        assertEquals(PlayerAction.ReturnToJoey, key(card, KeyEvent.KEYCODE_BACK).action)
    }

    @Test
    fun rightDuringTheEndCountdownCancelsItForThisEpisode() {
        val ended = PlayerUi.onEnded(hidden, t0).state
        val step = key(ended, KeyEvent.KEYCODE_DPAD_RIGHT, t0 + 2_000)
        assertEquals(PlayerOverlay.NONE, step.state.overlay)
        assertNull(step.state.countdownFromMs)
        assertNull(PlayerUi.countdownLeftS(step.state, t0 + 2_000))
        assertEquals(PlayerAction.None, PlayerUi.onTick(step.state, t0 + 20_000, false, 0, 0).action)
    }

    @Test
    fun upOrDownOnTheCardShowsTheControls() {
        val card = hidden.copy(overlay = PlayerOverlay.UP_NEXT)
        val step = key(card, KeyEvent.KEYCODE_DPAD_UP)
        assertEquals(PlayerOverlay.CONTROLS, step.state.overlay)
        assertEquals(FocusRow.BAR, step.state.row)
    }

    @Test
    fun theEndCountsDownEightSecondsThenPlaysNext() {
        // 2026-10-27 follow-up: was onEnded(hidden.copy(upNextDismissed = true)); a dismissed card now ends in Joey
        val ended = PlayerUi.onEnded(hidden, t0)
        assertEquals(PlayerAction.None, ended.action)
        assertEquals(PlayerOverlay.UP_NEXT, ended.state.overlay)
        assertEquals(8, PlayerUi.countdownLeftS(ended.state, t0))
        assertEquals(1, PlayerUi.countdownLeftS(ended.state, t0 + 7_001))
        assertEquals(PlayerAction.None, PlayerUi.onTick(ended.state, t0 + 7_999, false, 0, 0).action)
        val go = PlayerUi.onTick(ended.state, t0 + 8_000, false, 0, 0)
        assertEquals(PlayerAction.PlayNext, go.action)
        assertNull(go.state.countdownFromMs)
        assertNull(PlayerUi.countdownLeftS(hidden, t0))
    }

    @Test
    fun watchCreditsDuringTheCountdownStopsIt() {
        val ended = PlayerUi.onEnded(hidden, t0).state.copy(upNextChoice = UpNextChoice.WATCH_CREDITS)
        val step = key(ended, KeyEvent.KEYCODE_DPAD_CENTER)
        assertNull(step.state.countdownFromMs)
        assertEquals(PlayerAction.None, PlayerUi.onTick(step.state, t0 + 20_000, false, 0, 0).action)
    }

    @Test
    fun afterWatchCreditsTheEndReturnsToJoey() {
        val credits = key(hidden.copy(overlay = PlayerOverlay.UP_NEXT), KeyEvent.KEYCODE_DPAD_RIGHT).state
        val end = PlayerUi.onEnded(credits, t0)
        assertEquals(PlayerAction.ReturnToJoey, end.action)
        assertNull(end.state.countdownFromMs)
    }

    @Test
    fun theEndOfAFilmReturnsToJoey() {
        assertEquals(PlayerAction.ReturnToJoey, PlayerUi.onEnded(hidden.copy(hasNext = false), t0).action)
    }

    // ---- seeking stays inside the file ----

    @Test
    fun seekTargetsAreClamped() {
        assertEquals(0L, PlayerUi.seekTarget(5_000, -10_000, 60_000))
        assertEquals(35_000L, PlayerUi.seekTarget(5_000, 30_000, 60_000))
        assertEquals(59_000L, PlayerUi.seekTarget(50_000, 30_000, 60_000))
        assertEquals(80_000L, PlayerUi.seekTarget(50_000, 30_000, -1))   // duration unknown
    }
}
