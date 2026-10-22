package ca.htv11.mint.scanner

import android.media.Image
import ca.htv11.mint.coveragekit.ImageGrid
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.atomic.AtomicInteger

/**
 * A copy of one camera image (YUV 4:2:0, sensor orientation), planar and tightly packed, so the AR frame can be
 * released at once (ARCore has only a few). Shared read-only between the paper reader and the recorder:
 * [retain] / [release], and it goes back to [Pool] when nobody holds it.
 */
class YuvFrame private constructor(val width: Int, val height: Int, private val pool: Pool) {
    val y = ByteArray(width * height)
    val u = ByteArray((width / 2) * (height / 2))
    val v = ByteArray((width / 2) * (height / 2))
    private val refs = AtomicInteger(0)

    fun retain(): YuvFrame { refs.incrementAndGet(); return this }

    fun release() {
        if (refs.decrementAndGet() == 0) pool.recycle(this)
    }

    /** NV21 (Y, then interleaved V/U), what ML Kit and `YuvImage` read. `crop`: a centred share of the frame (1 = all). */
    fun nv21(crop: Float = 1f): Triple<ByteArray, Int, Int> {
        val cw = ((width * crop).toInt() / 2) * 2
        val ch = ((height * crop).toInt() / 2) * 2
        val x0 = ((width - cw) / 4) * 2
        val y0 = ((height - ch) / 4) * 2
        val out = ByteArray(cw * ch * 3 / 2)
        for (r in 0 until ch) System.arraycopy(y, (y0 + r) * width + x0, out, r * cw, cw)
        val cw2 = width / 2
        var o = cw * ch
        for (r in 0 until ch / 2) {
            val row = (y0 / 2 + r) * cw2 + x0 / 2
            for (c in 0 until cw / 2) {
                out[o++] = v[row + c]
                out[o++] = u[row + c]
            }
        }
        return Triple(out, cw, ch)
    }

    /**
     * Brightness + colour strength, every `step`-th pixel. Colour is measured against the paper's tint
     * ([ImageGrid.fromYCbCr]), so the sheet still reads under warm room light.
     */
    fun grid(step: Int): ImageGrid {
        val w = width / step
        val h = height / step
        val luma = ByteArray(w * h)
        val cb = FloatArray(w * h)
        val cr = FloatArray(w * h)
        val cw = width / 2
        for (gy in 0 until h) {
            val sy = gy * step
            for (gx in 0 until w) {
                val sx = gx * step
                val ci = (sy / 2) * cw + sx / 2
                val i = gy * w + gx
                luma[i] = y[sy * width + sx]
                cb[i] = ((u[ci].toInt() and 0xFF) - 128).toFloat()
                cr[i] = ((v[ci].toInt() and 0xFF) - 128).toFloat()
            }
        }
        return ImageGrid.fromYCbCr(w, h, luma, cb, cr)
    }

    private fun fill(image: Image) {
        val planes = image.planes
        val yp = planes[0]
        val yb = yp.buffer
        val yStride = yp.rowStride
        if (yStride == width) {
            yb.position(0); yb.get(y, 0, width * height)
        } else {
            for (r in 0 until height) { yb.position(r * yStride); yb.get(y, r * width, width) }
        }
        copyChroma(planes[1], u)
        copyChroma(planes[2], v)
    }

    private fun copyChroma(plane: Image.Plane, out: ByteArray) {
        val buf = plane.buffer
        val stride = plane.rowStride
        val px = plane.pixelStride
        val cw = width / 2
        val ch = height / 2
        if (px == 1) {
            for (r in 0 until ch) { buf.position(r * stride); buf.get(out, r * cw, cw) }
            return
        }
        // Interleaved (NV12/NV21 behind YUV_420_888): one row at a time, then every other byte.
        val row = ByteArray(stride)
        val limit = buf.capacity()
        for (r in 0 until ch) {
            val start = r * stride
            val len = minOf(stride, limit - start)
            buf.position(start)
            buf.get(row, 0, len)
            for (c in 0 until cw) out[r * cw + c] = row[c * px]
        }
    }

    /** Recycles frames of one size: at 30 fps a fresh 2 MB copy per frame would keep the garbage collector busy. */
    class Pool(private val capacity: Int = 8) {
        private val free = ArrayBlockingQueue<YuvFrame>(capacity)

        /** A copy of `image` (YUV_420_888), held once; call [release] when done. */
        fun copy(image: Image): YuvFrame {
            var f = free.poll()
            while (f != null && (f.width != image.width || f.height != image.height)) f = free.poll()
            val frame = f ?: YuvFrame(image.width, image.height, this)
            frame.fill(image)
            frame.refs.set(1)
            return frame
        }

        internal fun recycle(f: YuvFrame) { free.offer(f) }
    }
}
