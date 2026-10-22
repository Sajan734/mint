package ca.htv11.mint.coveragekit

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

private const val TWO_PI = (2 * PI).toFloat()
private const val PI_F = PI.toFloat()

/**
 * How much of the item has been seen, on the turntable: which sides have faced the camera, from
 * which height, and for how long. Driven only by measurements: the paper's turn ([PaperTurn])
 * and the camera's elevation above the item.
 *
 * The item's sides are 36 slices of 10° (item frame, 0 = the side facing the camera at the start).
 * One band (the default, what the app shows): one lap at any height. Two bands: band 0 = the height
 * of the first lap, band 1 = a clearly different height (≥ [bandGap] above or below). Each reading,
 * every slice within 25° of facing the camera (looked at nearly head-on) gains
 * cos(angle off the camera) × seconds / [secondsToFill], so a slice fills as it turns past the
 * front, and 100% means the paper really went (nearly) all the way round: sides only glimpsed at a
 * steep angle don't count.
 */
class TurnCoverage(
    val bands: Int = 1,
    val secondsToFill: Float = 0.5f,
    val bandGap: Float = 10 * PI_F / 180,
) {
    init { require(bands == 1 || bands == 2) }

    /** fill[band][slice], 0…1. */
    val fill: Array<FloatArray> = Array(bands) { FloatArray(SLICES) }
    /** The side currently facing the camera (item frame, radians, clockwise from above). */
    var facing = 0f
        private set
    var band = 0
        private set
    var firstElevation: Float? = null
        private set

    /**
     * One measurement. `turned`: the paper's turn since the start ([PaperTurn.turned], clockwise
     * from above); `elevation`: the camera above the item (radians); `dt`: seconds since the last one.
     */
    fun observe(turned: Float, elevation: Float, dt: Double) {
        // The item turned clockwise by `turned`, so the side facing the camera is the one that
        // started `turned` anticlockwise of it.
        facing = -turned
        val first = firstElevation ?: elevation.also { firstElevation = it }
        band = if (bands == 2 && abs(elevation - first) >= bandGap) 1 else 0
        val gain = min(dt, 0.25).toFloat() / secondsToFill
        if (gain <= 0) return
        for (s in 0 until SLICES) {
            val d = wrapPi(centre(s) - facing)
            if (abs(d) >= REACH) continue
            fill[band][s] = min(1f, fill[band][s] + gain * cos(d))
        }
    }

    /** 0…100, the share of all slices (at every height) that have been seen. 100 only when every one is full. */
    val percent: Int
        get() {
            var sum = 0f
            var all = true
            for (b in fill) for (v in b) { sum += v; if (v < 0.999f) all = false }
            if (all) return 100
            return min(99, (sum / (bands * SLICES) * 100).toInt())
        }

    /** How well a side has been seen (heights averaged), 0…1, interpolated between slices. */
    fun level(side: Float): Float {
        val x = wrap2Pi(side) / TWO_PI * SLICES - 0.5f
        val i0 = floor(x).toInt()
        val f = x - floor(x)
        val a = (i0 % SLICES + SLICES) % SLICES
        val b = (a + 1) % SLICES
        fun both(s: Int): Float = fill.fold(0f) { acc, band -> acc + band[s] } / bands
        return both(a) * (1 - f) + both(b) * f
    }

    /**
     * The side seen at horizontal offset `s` across the item's silhouette (−1 = its left edge on
     * screen, +1 = its right edge), modelling the item as an upright cylinder.
     */
    fun side(atOffset: Float): Float = facing - asin(max(-1f, min(1f, atOffset)))

    companion object {
        const val SLICES = 36
        val REACH = 25 * PI_F / 180

        internal fun centre(s: Int): Float = (s + 0.5f) / SLICES * TWO_PI

        internal fun wrapPi(a: Float): Float {
            var x = a % TWO_PI
            if (x > PI_F) x -= TWO_PI
            if (x <= -PI_F) x += TWO_PI
            return x
        }

        internal fun wrap2Pi(a: Float): Float {
            var x = a % TWO_PI
            if (x < 0) x += TWO_PI
            return x
        }
    }
}
