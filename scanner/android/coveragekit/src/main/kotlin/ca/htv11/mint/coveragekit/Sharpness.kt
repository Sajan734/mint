package ca.htv11.mint.coveragekit

/** A small 8-bit grayscale image (row-major, tightly packed). */
class GrayImage(val width: Int, val height: Int, val pixels: ByteArray) {
    init { require(pixels.size == width * height) }
}

/**
 * Per-frame sharpness for reconstruction to pick the crispest frames: the luma plane is scaled to a
 * 480 × 360 thumbnail (area average), then the variance of its 4-neighbour Laplacian is taken. Higher =
 * sharper; blur drives it towards 0. Same definition as the iOS app's `FastSharpness`.
 */
object FastSharpness {
    class Result(
        val sharpness: Double,  // variance of the Laplacian on the thumbnail
        val meanLuma: Double,   // 0–255
    )

    /** Scales a luma plane (`rowStride` ≥ `width`) to `thumbWidth × thumbHeight`, then measures it. */
    fun measure(
        plane: ByteArray, width: Int, height: Int, rowStride: Int,
        thumbWidth: Int = 480, thumbHeight: Int = 360,
    ): Result? {
        if (width < thumbWidth || height < thumbHeight) return measure(GrayImage(width, height, pack(plane, width, height, rowStride)))
        return measure(downscale(plane, width, height, rowStride, thumbWidth, thumbHeight))
    }

    /** Laplacian variance + mean luma of a small image, over the interior. */
    fun measure(img: GrayImage): Result? {
        val w = img.width
        val h = img.height
        if (w < 3 || h < 3) return null
        val p = img.pixels
        var meanSum = 0L
        for (b in p) meanSum += b.toInt() and 0xFF
        var sum = 0.0
        var sumSq = 0.0
        for (y in 1 until h - 1) {
            val row = y * w
            for (x in 1 until w - 1) {
                val i = row + x
                val lap = (p[i - w].toInt() and 0xFF) + (p[i + w].toInt() and 0xFF) + (p[i - 1].toInt() and 0xFF) +
                    (p[i + 1].toInt() and 0xFF) - 4 * (p[i].toInt() and 0xFF)
                val v = lap.toDouble()
                sum += v
                sumSq += v * v
            }
        }
        val n = ((w - 2) * (h - 2)).toDouble()
        val mean = sum / n
        return Result(sumSq / n - mean * mean, meanSum.toDouble() / p.size)
    }

    /** Area-average downscale (each output pixel = the mean of the source box it covers). */
    fun downscale(plane: ByteArray, width: Int, height: Int, rowStride: Int, outW: Int, outH: Int): GrayImage {
        val out = ByteArray(outW * outH)
        for (oy in 0 until outH) {
            val y0 = oy * height / outH
            val y1 = maxOf(y0 + 1, (oy + 1) * height / outH)
            for (ox in 0 until outW) {
                val x0 = ox * width / outW
                val x1 = maxOf(x0 + 1, (ox + 1) * width / outW)
                var s = 0
                for (y in y0 until y1) {
                    val r = y * rowStride
                    for (x in x0 until x1) s += plane[r + x].toInt() and 0xFF
                }
                out[oy * outW + ox] = (s / ((y1 - y0) * (x1 - x0))).toByte()
            }
        }
        return GrayImage(outW, outH, out)
    }

    private fun pack(plane: ByteArray, width: Int, height: Int, rowStride: Int): ByteArray {
        if (rowStride == width) return plane.copyOf(width * height)
        val out = ByteArray(width * height)
        for (y in 0 until height) System.arraycopy(plane, y * rowStride, out, y * width, width)
        return out
    }
}
