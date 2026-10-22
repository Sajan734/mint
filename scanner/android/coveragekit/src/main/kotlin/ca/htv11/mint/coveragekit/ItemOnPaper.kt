package ca.htv11.mint.coveragekit

import kotlin.math.max
import kotlin.math.min

/** A small image as brightness + colour strength per pixel (row-major). */
class ImageGrid(val width: Int, val height: Int, val luma: ByteArray, val chroma: ByteArray) {
    init {
        require(luma.size == width * height && chroma.size == width * height)
    }

    fun lumaAt(i: Int): Int = luma[i].toInt() and 0xFF
    fun chromaAt(i: Int): Int = chroma[i].toInt() and 0xFF

    companion object {
        /**
         * From brightness and colour difference (YCbCr's Cb and Cr, centred on 0), with colour strength measured
         * against the paper's own tint: under warm (or cool) room light white paper isn't colourless in the
         * camera image, and read as is it stopped counting as paper at night.
         */
        fun fromYCbCr(width: Int, height: Int, luma: ByteArray, cb: FloatArray, cr: FloatArray): ImageGrid {
            val n = width * height
            require(luma.size == n && cb.size == n && cr.size == n)
            val (tu, tv) = paperTint(luma, cb, cr)
            val chroma = ByteArray(n)
            for (i in 0 until n) {
                val l = (luma[i].toInt() and 0xFF).toFloat()
                val u = cb[i] - tu * l
                val v = cr[i] - tv * l
                val r = l + 1.402f * v
                val g = l - 0.344f * u - 0.714f * v
                val b = l + 1.772f * u
                chroma[i] = max(0f, min(255f, max(r, max(g, b)) - min(r, min(g, b)))).toInt().toByte()
            }
            return ImageGrid(width, height, luma, chroma)
        }

        /**
         * The room light's tint on the paper, as (Cb, Cr) per unit of brightness: the mean of the brightest
         * near-neutral pixels (the sheet is the brightest big thing in view). Capped, so a bright coloured item
         * can't pass for the white.
         */
        internal fun paperTint(luma: ByteArray, cb: FloatArray, cr: FloatArray): Pair<Float, Float> {
            val hist = IntArray(256)
            for (l in luma) hist[l.toInt() and 0xFF]++
            var bright = 255
            var count = 0
            while (bright > 0 && count + hist[bright] < luma.size * 15 / 100) { count += hist[bright]; bright -= 1 }
            var su = 0f
            var sv = 0f
            var k = 0f
            for (i in luma.indices) {
                val li = luma[i].toInt() and 0xFF
                if (li < max(bright, 24)) continue
                val l = li.toFloat()
                val u = cb[i] / l
                val v = cr[i] / l
                if (u * u + v * v > 0.22f * 0.22f) continue
                su += u; sv += v; k += 1
            }
            if (k < (luma.size / 100).toFloat()) return 0f to 0f
            val cap = 0.16f
            return min(cap, max(-cap, su / k)) to min(cap, max(-cap, sv / k))
        }
    }
}

/**
 * Finds the item sitting on a sheet of paper: the sheet is the big bright colourless region, and
 * the item is what the sheet *encloses*. A hand reaches in from the sheet's edge and ruled lines run off it,
 * so neither is enclosed.
 */
object ItemOnPaper {
    class Result(
        val item: ByteArray,    // 1 = item pixel
        val sheet: ByteArray,   // 1 = sheet pixel
        val itemArea: Int,
    )

    fun segment(g: ImageGrid, chromaMax: Int = 16): Result? {
        val w = g.width
        val h = g.height
        val n = w * h

        // Paper: colourless and bright relative to the paper itself (shadows are darker). How bright follows
        // the room: the brightest colourless pixels (the sheet) set the floor, 100 in good light, lower in a dim
        // room, never under 40 (black plastic, shadows).
        // Colourless relative to brightness: chromaMax on bright paper (luma 200), less in the dark, where a
        // beige table's colour shrinks too.
        fun colourless(i: Int) = g.chromaAt(i).toFloat() <= max(4f, chromaMax.toFloat() * g.lumaAt(i).toFloat() / 200f)
        val neutralList = ArrayList<Int>()
        for (i in 0 until n) if (colourless(i)) neutralList.add(g.lumaAt(i))
        if (neutralList.size <= n / 50) return null
        val neutral = neutralList.toIntArray().also { it.sort() }
        val floor = max(40f, min(100f, neutral[neutral.size * 95 / 100].toFloat() * 0.5f))
        val lumas = neutral.filter { it.toFloat() >= floor }
        if (lumas.size <= n / 50) return null
        val paperLuma = lumas[lumas.size * 3 / 4].toFloat()
        val minLuma = max(floor * 0.8f, min(255f, paperLuma * 0.62f)).toInt()
        var white = ByteArray(n)
        for (i in 0 until n) if (g.lumaAt(i) >= minLuma && colourless(i)) white[i] = 1
        // Bridge thin features: ruled lines run edge to edge and would cut the sheet into strips.
        repeat(2) { white = dilate(white, w, h) }
        repeat(2) { white = erode(white, w, h) }

        // The sheet: the biggest white region.
        val (labels, sizes) = label(white, w, h, 1)
        var sheetLabel = -1
        var sheetArea = 0
        for (l in 1 until sizes.size) if (sizes[l] > sheetArea) { sheetArea = sizes[l]; sheetLabel = l }
        if (sheetLabel < 0 || sheetArea < n / 50) return null
        val sheet = ByteArray(n)
        for (i in 0 until n) if (labels[i] == sheetLabel) sheet[i] = 1

        // Everything not sheet that can reach the image border is outside; the rest is enclosed.
        val outside = ByteArray(n)
        val stack = IntStack()
        fun seed(i: Int) {
            if (sheet[i].toInt() == 0 && outside[i].toInt() == 0) { outside[i] = 1; stack.push(i) }
        }
        for (x in 0 until w) { seed(x); seed((h - 1) * w + x) }
        for (y in 0 until h) { seed(y * w); seed(y * w + w - 1) }
        while (stack.isNotEmpty()) {
            val i = stack.pop()
            val x = i % w
            val y = i / w
            if (x > 0) seed(i - 1)
            if (x < w - 1) seed(i + 1)
            if (y > 0) seed(i - w)
            if (y < h - 1) seed(i + w)
        }
        val enclosed = ByteArray(n)
        for (i in 0 until n) if (sheet[i].toInt() == 0 && outside[i].toInt() == 0) enclosed[i] = 1

        // The item: the biggest enclosed region (punched holes and specks are tiny).
        val (hl, hs) = label(enclosed, w, h, 1)
        var itemLabel = -1
        var itemArea = 0
        for (l in 1 until hs.size) if (hs[l] > itemArea) { itemArea = hs[l]; itemLabel = l }
        if (itemLabel < 0 || itemArea < max(12, n / 2000) || itemArea > sheetArea) return null
        val item = ByteArray(n)
        for (i in 0 until n) if (hl[i] == itemLabel) item[i] = 1
        return Result(item, sheet, itemArea)
    }

    fun dilate(m: ByteArray, w: Int, h: Int): ByteArray {
        val out = m.copyOf()
        for (y in 0 until h) for (x in 0 until w) {
            val i = y * w + x
            if (m[i].toInt() != 0) continue
            if ((x > 0 && m[i - 1].toInt() != 0) || (x < w - 1 && m[i + 1].toInt() != 0) ||
                (y > 0 && m[i - w].toInt() != 0) || (y < h - 1 && m[i + w].toInt() != 0)
            ) out[i] = 1
        }
        return out
    }

    fun erode(m: ByteArray, w: Int, h: Int): ByteArray {
        val out = m.copyOf()
        for (y in 0 until h) for (x in 0 until w) {
            val i = y * w + x
            if (m[i].toInt() == 0) continue
            if (x == 0 || y == 0 || x == w - 1 || y == h - 1 || m[i - 1].toInt() == 0 || m[i + 1].toInt() == 0 ||
                m[i - w].toInt() == 0 || m[i + w].toInt() == 0
            ) out[i] = 0
        }
        return out
    }

    /** 4-connected labels of pixels equal to `value` (0 = not that value); sizes[label] = pixel count. */
    fun label(m: ByteArray, w: Int, h: Int, value: Int): Pair<IntArray, IntArray> {
        val labels = IntArray(w * h)
        val sizes = IntList().apply { add(0) }
        val stack = IntStack()
        for (s in 0 until w * h) {
            if (m[s].toInt() != value || labels[s] != 0) continue
            val l = sizes.size
            sizes.add(0)
            labels[s] = l
            stack.push(s)
            while (stack.isNotEmpty()) {
                val i = stack.pop()
                sizes[l] = sizes[l] + 1
                val x = i % w
                val y = i / w
                if (x > 0) visit(i - 1, m, value, labels, l, stack)
                if (x < w - 1) visit(i + 1, m, value, labels, l, stack)
                if (y > 0) visit(i - w, m, value, labels, l, stack)
                if (y < h - 1) visit(i + w, m, value, labels, l, stack)
            }
        }
        return labels to sizes.toIntArray()
    }

    private fun visit(j: Int, m: ByteArray, value: Int, labels: IntArray, l: Int, stack: IntStack) {
        if (m[j].toInt() == value && labels[j] == 0) {
            labels[j] = l
            stack.push(j)
        }
    }
}

/** A growable int stack without boxing (flood fills on 320 × 240 grids, ~8 times a second). */
internal class IntStack {
    private var a = IntArray(1024)
    private var n = 0
    fun push(v: Int) {
        if (n == a.size) a = a.copyOf(n * 2)
        a[n++] = v
    }
    fun pop(): Int = a[--n]
    fun isNotEmpty() = n > 0
}

internal class IntList {
    private var a = IntArray(64)
    var size = 0
        private set
    fun add(v: Int) {
        if (size == a.size) a = a.copyOf(size * 2)
        a[size++] = v
    }
    operator fun get(i: Int) = a[i]
    operator fun set(i: Int, v: Int) { a[i] = v }
    fun toIntArray(): IntArray = a.copyOf(size)
}
