package net.joeyhome.media

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View

/**
 * JY-057 look A's seek bar on TV: track, buffer, fill, thumb and chapter ticks, with the 4 dp white ring when it is the
 * focused row (`isActivated`, set by PlayerActivity from PlayerUi's state; Android focus is not used in the player).
 */
class PlayerBar @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    var durationMs = 0L
    var positionMs = 0L
    var bufferedMs = 0L
    var chapterStartsMs: List<Long> = emptyList()

    private val dp = resources.displayMetrics.density
    private val track = paint(R.color.joey_line)
    private val buffer = paint(R.color.joey_text_4).apply { alpha = 110 }
    private val fill = paint(R.color.joey_primary)
    private val thumb = paint(R.color.joey_text_1)
    private val tick = paint(R.color.joey_text_2)
    private val ring = paint(R.color.joey_ring).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4 * dp
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
        val pad = 14 * dp
        val left = pad
        val right = width - pad
        val cy = height / 2f
        val h = 7 * dp // JY-259 phase 4: the mock's 14 px track at 1920
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
            canvas.drawRect(cx - 1 * dp, cy - h, cx + 1 * dp, cy + h, tick)
        }
        val r = if (isActivated) 10 * dp else 7 * dp
        canvas.drawCircle(x(positionMs), cy, r, thumb)
        if (isActivated) {
            rect.set(2 * dp, 2 * dp, width - 2 * dp, height - 2 * dp)
            canvas.drawRoundRect(rect, 6 * dp, 6 * dp, ring) // --tv-r
        }
    }
}
