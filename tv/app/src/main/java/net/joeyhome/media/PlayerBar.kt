package net.joeyhome.media

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View

/**
 * JY-057 look A's seek bar on TV: track, buffer, fill, thumb and chapter ticks. JY-307 P5 (option B, P2b scale): a thin
 * 8 px track, a 16 px thumb that grows to 24 px with the 6 px white ring on the thumb only when the bar is the focused
 * row (`isActivated`, set by PlayerActivity from PlayerUi's state; Android focus is not used in the player).
 */
class PlayerBar @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    var durationMs = 0L
    var positionMs = 0L
    var bufferedMs = 0L
    var chapterStartsMs: List<Long> = emptyList()

    private val trackH = resources.getDimension(R.dimen.player_bar_track)
    private val thumbD = resources.getDimension(R.dimen.player_bar_thumb)
    private val thumbOnD = resources.getDimension(R.dimen.player_bar_thumb_on)
    private val tickW = resources.getDimension(R.dimen.player_bar_tick)
    private val ringW = resources.getDimension(R.dimen.player_ring)
    private val track = paint(R.color.joey_line)
    private val buffer = paint(R.color.joey_text_4).apply { alpha = 110 }
    private val fill = paint(R.color.joey_primary)
    private val thumb = paint(R.color.joey_text_1)
    private val tick = paint(R.color.joey_text_2)
    private val ring = paint(R.color.joey_ring).apply {
        style = Paint.Style.STROKE
        strokeWidth = ringW
    }
    private val rect = RectF()

    private fun paint(color: Int) = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = context.getColor(color) }

    fun update(durationMs: Long, positionMs: Long, bufferedMs: Long, chapterStartsMs: List<Long>) {
        this.durationMs = durationMs
        this.positionMs = positionMs
        this.bufferedMs = bufferedMs
        this.chapterStartsMs = chapterStartsMs
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val gap = ringW / 2   // a dark hairline between the white thumb and its ring, so the ring reads as a ring
        val pad = thumbOnD / 2 + gap + ringW   // the focused thumb and its ring stay inside the view at both ends
        val left = pad
        val right = width - pad
        val cy = height / 2f
        val h = trackH
        val span = (right - left).coerceAtLeast(1f)
        fun x(ms: Long): Float = if (durationMs > 0) left + span * (ms.coerceIn(0L, durationMs).toFloat() / durationMs) else left

        rect.set(left, cy - h / 2, right, cy + h / 2)
        canvas.drawRoundRect(rect, h / 2, h / 2, track)
        rect.set(left, cy - h / 2, x(bufferedMs), cy + h / 2)
        canvas.drawRoundRect(rect, h / 2, h / 2, buffer)
        rect.set(left, cy - h / 2, x(positionMs), cy + h / 2)
        canvas.drawRoundRect(rect, h / 2, h / 2, fill)
        for (start in chapterStartsMs) {
            if (start <= 0 || durationMs <= 0) continue
            val cx = x(start)
            canvas.drawRect(cx - tickW / 2, cy - h, cx + tickW / 2, cy + h, tick)
        }
        val r = (if (isActivated) thumbOnD else thumbD) / 2
        canvas.drawCircle(x(positionMs), cy, r, thumb)
        if (isActivated) canvas.drawCircle(x(positionMs), cy, r + gap + ringW / 2, ring)
    }
}
