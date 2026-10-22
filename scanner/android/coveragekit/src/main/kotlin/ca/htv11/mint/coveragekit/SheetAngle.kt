package ca.htv11.mint.coveragekit

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

private const val HALF_PI = (PI / 2).toFloat()
private const val QUARTER_PI = (PI / 4).toFloat()
private const val DEG = (PI / 180).toFloat()

/**
 * How far the sheet of paper has turned, read straight off the camera image (the turntable demo:
 * the phone stays still, the paper turns). Needs only the sheet's mask ([ItemOnPaper]) and which
 * way is down (the camera's rotation): no table plane, no item position, no lock.
 *
 * The sheet's outline is projected onto a horizontal plane under the camera. The plane's height
 * is unknown, but angles on it don't depend on the height, so the straight edges give the sheet's
 * angle (mod 90°). Angles are measured relative to the camera's heading, so if the AR world
 * slowly turns (the turning paper fills much of the view), it cancels out.
 */
object SheetAngle {
    data class Reading(
        /** Sheet edge direction, radians in [0, π/2), relative to the camera's heading (0 = straight away from the camera, π/2 = to its right). */
        val angleMod90: Float,
        /** Share of the outline that agrees with [angleMod90] (straight edges vs hands, clutter). */
        val confidence: Float,
        /** Outline samples used. */
        val samples: Int,
    )

    /** Pinhole intrinsics in the mask's own pixel units. */
    data class Intrinsics(val fx: Float, val fy: Float, val cx: Float, val cy: Float) {
        companion object {
            /** The camera's K for an image `step` times larger than the mask. */
            fun of(k: CameraK, step: Float) = Intrinsics(k.fx / step, k.fy / step, k.cx / step, k.cy / step)
        }
    }

    /** A horizontal frame that turns with the camera: +Y up (gravity), −Z the camera's heading. */
    class HeadingFrame private constructor(
        val right: Vec3,
        val up: Vec3,
        val back: Vec3,
        private val rotation: Mat3,   // camera → world (camera axes: +x right, +y up, looks along −z)
    ) {
        companion object {
            fun of(r: Mat3): HeadingFrame? {
                val forward = r * Vec3(0f, 0f, -1f)
                var h = Vec3(forward.x, 0f, forward.z)
                if (h.length < 0.1f) {   // looking straight down: the image's top edge gives the heading
                    val top = r * Vec3(0f, 1f, 0f)
                    h = Vec3(top.x, 0f, top.z)
                }
                if (h.length <= 1e-4f) return null
                val up = Vec3(0f, 1f, 0f)
                val back = -h.normalized()
                return HeadingFrame(up cross back, up, back, r)
            }
        }

        /** Image pixel → viewing ray in this frame (x right, y up, z towards the camera's back). */
        fun ray(u: Float, v: Float, k: Intrinsics): Vec3 {
            val d = rotation * Vec3((u - k.cx) / k.fx, -(v - k.cy) / k.fy, -1f)
            return Vec3(d dot right, d dot up, d dot back)
        }

        /** Where the ray hits the plane one unit below the camera, as (x, z); null near the horizon. */
        fun onPlane(u: Float, v: Float, k: Intrinsics): Pair<Float, Float>? {
            val d = ray(u, v, k)
            val len = d.length
            if (d.y >= -0.08f * len) return null
            return (d.x / -d.y) to (d.z / -d.y)
        }

        /** Elevation of the camera above an image point (radians; π/2 = looking straight down at it). */
        fun elevation(u: Float, v: Float, k: Intrinsics): Float {
            val d = ray(u, v, k)
            return asin(max(-1f, min(1f, -d.y / d.length)))
        }
    }

    /** Reads the sheet's angle. `sheet` / `item`: w × h masks (1 = inside, [ItemOnPaper.Result]). */
    fun read(sheet: ByteArray, item: ByteArray, w: Int, h: Int, k: Intrinsics, frame: HeadingFrame): Reading? {
        val n = w * h
        if (sheet.size != n || item.size != n || w <= 8 || h <= 8) return null

        // Soft edges: a thresholded mask is a staircase; blurring twice makes the gradient follow the true edge.
        var m = FloatArray(n)
        for (i in 0 until n) if (sheet[i].toInt() != 0) m[i] = 1f
        m = boxBlur(boxBlur(m, w, h), w, h)
        // Edges against the item turn with the paper too, but a boxy item's sides aren't the sheet's angle.
        var nearItem = item
        repeat(3) { nearItem = ItemOnPaper.dilate(nearItem, w, h) }

        val margin = 4   // the image border cuts the sheet along straight lines that aren't its edges
        val angles = FloatList(2048)
        for (y in margin until h - margin) {
            for (x in margin until w - margin) {
                val i = y * w + x
                if (m[i] <= 0.1f || m[i] >= 0.9f || nearItem[i].toInt() != 0) continue
                val gx = (m[i - w + 1] + 2 * m[i + 1] + m[i + w + 1]) - (m[i - w - 1] + 2 * m[i - 1] + m[i + w - 1])
                val gy = (m[i + w - 1] + 2 * m[i + w] + m[i + w + 1]) - (m[i - w - 1] + 2 * m[i - w] + m[i - w + 1])
                val mag = sqrt(gx * gx + gy * gy)
                if (mag <= 0.5f) continue
                // Edge tangent in the image → on the plane.
                val tx = -gy / mag
                val ty = gx / mag
                val u = x.toFloat()
                val v = y.toFloat()
                val p0 = frame.onPlane(u - tx, v - ty, k) ?: continue
                val p1 = frame.onPlane(u + tx, v + ty, k) ?: continue
                val dx = p1.first - p0.first
                val dz = p1.second - p0.second
                if (sqrt(dx * dx + dz * dz) <= 1e-6f) continue
                var a = atan2(dx, -dz) % HALF_PI   // 0 = away from the camera
                if (a < 0) a += HALF_PI
                angles.add(a)
            }
        }
        if (angles.size < 40) return null

        // Peak of a 1° histogram with period 90°, then a circular mean of the samples near it.
        val hist = FloatArray(90)
        for (j in 0 until angles.size) hist[min(89, (angles[j] / DEG).toInt())] += 1f
        var best = 0
        var bestScore = -1f
        for (b in 0 until 90) {
            var s = 0f
            for (d in -2..2) s += hist[(b + d + 90) % 90]
            if (s > bestScore) { bestScore = s; best = b }
        }
        val peak = (best + 0.5f) * DEG
        val tol = 6 * DEG
        var sx = 0f
        var sy = 0f
        var agree = 0
        for (j in 0 until angles.size) {
            val a = angles[j]
            if (abs(wrap90(a - peak)) >= tol) continue
            sx += cos(4 * a)   // period 90° → ×4 on the circle
            sy += sin(4 * a)
            agree += 1
        }
        var angle = atan2(sy, sx) / 4
        if (angle < 0) angle += HALF_PI
        return Reading(angle, agree.toFloat() / angles.size, angles.size)
    }

    /** The equivalent of `d` in (−45°, 45°]. */
    fun wrap90(d: Float): Float {
        var x = d % HALF_PI
        if (x > QUARTER_PI) x -= HALF_PI
        if (x <= -QUARTER_PI) x += HALF_PI
        return x
    }

    internal fun boxBlur(m: FloatArray, w: Int, h: Int): FloatArray {
        val out = m.copyOf()
        for (y in 1 until h - 1) for (x in 1 until w - 1) {
            val i = y * w + x
            out[i] = (m[i - w - 1] + m[i - w] + m[i - w + 1] + m[i - 1] + m[i] + m[i + 1] + m[i + w - 1] + m[i + w] + m[i + w + 1]) / 9
        }
        return out
    }
}

/**
 * Follows the sheet's angle through a scan: one reading only knows it mod 90°, so each new one is
 * taken as the equivalent closest to the last (right while the paper turns < 45° between reads;
 * at a 10 s lap and ~8 reads/s it turns ~5°). Readings that disagree with the motion so far are
 * dropped (a hand's edge briefly outvoting the sheet's).
 */
class PaperTurn {
    var angle: Float? = null   // continuous, radians
        private set
    var start = 0f
        private set
    private var lastTime = 0.0
    private var rejects = 0

    /** Total turn since [restart] (or the first reading), radians. Positive = clockwise seen from above. */
    val turned: Float get() = (angle ?: start) - start

    fun restart() { start = angle ?: 0f }

    /** Returns true if the reading was used. `maxRate`: rad/s ≈ a lap in 2.5 s, 4× the demo pace. */
    fun update(r: SheetAngle.Reading, time: Double, minConfidence: Float = 0.3f, maxRate: Float = 2.5f): Boolean {
        if (r.confidence < minConfidence) return false
        val prev = angle
        if (prev == null) {
            angle = r.angleMod90
            start = r.angleMod90
            lastTime = time
            return true
        }
        val d = SheetAngle.wrap90(r.angleMod90 - prev)
        val dt = max(0.0, time - lastTime).toFloat()
        // A few rejections in a row means the paper really moved while we weren't watching: accept.
        if (abs(d) > maxRate * dt + 0.1f && rejects < 3) {
            rejects += 1
            return false
        }
        rejects = 0
        angle = prev + d
        lastTime = time
        return true
    }
}

internal class FloatList(capacity: Int) {
    private var a = FloatArray(capacity)
    var size = 0
        private set
    fun add(v: Float) {
        if (size == a.size) a = a.copyOf(size * 2)
        a[size++] = v
    }
    operator fun get(i: Int) = a[i]
}
