package ca.htv11.mint.scanner

import ca.htv11.mint.coveragekit.CameraK
import ca.htv11.mint.coveragekit.ItemOnPaper
import ca.htv11.mint.coveragekit.Mat3
import ca.htv11.mint.coveragekit.SheetAngle
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Reads the sheet of paper the item sits on (the turntable demo): how far it has turned, and how high the
 * camera is above the item. The item is what the sheet encloses ([ItemOnPaper]); nothing else is ever taken
 * for the item. While the app waits for a product it also reads QR codes (the website's `mint://` links).
 * Runs on its own thread and drops frames while busy, so it never slows the camera or the recording.
 */
class PaperReader {
    /** What one camera frame shows. */
    class Sight(
        val paper: SheetAngle.Reading?,   // null: no sheet, or its edges weren't clear (a hand over it)
        val elevation: Float?,            // the camera above the item, radians
        val code: String?,                // a QR code's text, when asked to look for one
        val timestamp: Double,            // seconds
    )

    /** The camera for one frame, copied out of the AR frame (which mustn't be held). */
    class Camera(
        val rotation: Mat3,               // camera → world, camera axes (+x right, +y up, looks along −z)
        val intrinsics: CameraK,          // pixels of the CPU image
        val timestamp: Double,            // seconds
        val sensorOrientation: Int,
    )

    private val executor = Executors.newSingleThreadExecutor { Thread(it, "mint.paper").apply { priority = Thread.NORM_PRIORITY + 1 } }
    private val busySince = AtomicLong(-1)   // frame timestamp (ns) of the read in progress
    private val scanner by lazy {
        BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    }

    /**
     * One read at a time. A read that never came back (it shouldn't happen) frees the reader after 2 s, so the ring
     * and the QR reader can't stop for good.
     */
    fun isBusy(nowNs: Long): Boolean {
        val since = busySince.get()
        return since >= 0 && nowNs - since < 2_000_000_000L
    }

    /** Takes `yuv` (already retained) and releases it. `completion` runs on the reader's thread. */
    fun process(yuv: YuvFrame, camera: Camera, lookForCodes: Boolean, completion: (Sight) -> Unit) {
        busySince.set((camera.timestamp * 1e9).toLong())
        executor.execute {
            try {
                // While looking for codes only the QR code is read: the paper isn't needed then, and the reads come faster.
                val sight = if (lookForCodes) Sight(null, null, qrCode(yuv, camera.sensorOrientation), camera.timestamp)
                else read(yuv, camera)
                completion(sight)
            } catch (_: Exception) {
                completion(Sight(null, null, null, camera.timestamp))
            } finally {
                yuv.release()
                busySince.set(-1)
            }
        }
    }

    /**
     * The first QR code in view, if any. The whole frame first; then the middle of it, at a higher effective
     * resolution, for a code that is small in the frame (a small or far-away screen).
     */
    private fun qrCode(yuv: YuvFrame, rotation: Int): String? {
        for (crop in floatArrayOf(1f, 0.6f)) {
            val (nv21, w, h) = yuv.nv21(crop)
            val image = InputImage.fromByteArray(nv21, w, h, rotation, InputImage.IMAGE_FORMAT_NV21)
            val codes = runCatching { Tasks.await(scanner.process(image), 2, TimeUnit.SECONDS) }.getOrNull() ?: continue
            codes.firstNotNullOfOrNull { it.rawValue }?.let { return it }
        }
        return null
    }

    companion object {
        /** The sheet's angle and the camera's elevation above the item, from the camera image downsampled to ~320 px wide. */
        fun read(yuv: YuvFrame, camera: Camera): Sight {
            val none = Sight(null, null, null, camera.timestamp)
            val step = max(1, (yuv.width / 320f).roundToInt())
            val grid = yuv.grid(step)
            val r = ItemOnPaper.segment(grid) ?: return none
            val frame = SheetAngle.HeadingFrame.of(camera.rotation) ?: return none
            val k = SheetAngle.Intrinsics.of(camera.intrinsics, step.toFloat())
            val paper = SheetAngle.read(r.sheet, r.item, grid.width, grid.height, k, frame)
            // Elevation above the item's middle (the mean of its pixels).
            var sx = 0f
            var sy = 0f
            var n = 0f
            for (y in 0 until grid.height) for (x in 0 until grid.width) {
                if (r.item[y * grid.width + x].toInt() != 0) { sx += x; sy += y; n += 1 }
            }
            return Sight(paper, if (n > 0) frame.elevation(sx / n, sy / n, k) else null, null, camera.timestamp)
        }
    }
}
