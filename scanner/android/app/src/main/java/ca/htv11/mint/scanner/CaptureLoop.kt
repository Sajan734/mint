package ca.htv11.mint.scanner

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Size
import ca.htv11.mint.coveragekit.CameraK
import ca.htv11.mint.coveragekit.Mat3
import com.google.ar.core.Frame
import com.google.ar.core.TrackingState

/**
 * Every AR frame, on the GL thread: keeps the paper's angle fresh for the coverage ring (~8 Hz) and, while
 * recording, hands every frame (30 fps) to the recorder. Never holds a Frame: the camera image is copied out.
 */
class CaptureLoop {
    /** Set once before the camera runs; called on the main thread. */
    var onSight: ((PaperReader.Sight) -> Unit)? = null
    /** Read QR codes instead of the paper (while the app waits for a product). A stale read is harmless. */
    @Volatile var lookForCodes = false

    /** When the last camera frame arrived (uptime, ms): the session's watchdog reads it to spot a frozen camera. */
    @Volatile var lastFrameAt = 0L
        private set

    private val main = Handler(Looper.getMainLooper())
    private val pool = YuvFrame.Pool()
    private val reader = PaperReader()
    @Volatile private var recorder: VideoRecorder? = null
    private var lastRecorded = 0L
    private var lastRead = 0L
    private val pose = FloatArray(16)

    fun startRecording(r: VideoRecorder) {
        lastRecorded = 0
        recorder = r
    }

    /** Stops recording and hands the recorder back (call `finish` on it). */
    fun stopRecording(): VideoRecorder? = recorder.also { recorder = null }

    fun cancel() {
        recorder?.cancel()
        recorder = null
    }

    fun onFrame(frame: Frame, imageSize: Size, sensorOrientation: Int) {
        val ts = frame.timestamp
        if (ts == 0L) return
        lastFrameAt = SystemClock.uptimeMillis()
        val camera = frame.camera
        val rec = recorder
        val readDue = ts - lastRead >= READ_INTERVAL_NS && !reader.isBusy(ts)
        val recordDue = rec != null && ts - lastRecorded >= RECORD_INTERVAL_NS - 4_000_000
        if (!readDue && !recordDue) return

        val image = try { frame.acquireCameraImage() } catch (_: Exception) { return }   // not yet available
        val yuv = try { pool.copy(image) } finally { image.close() }
        try {
            camera.pose.toMatrix(pose, 0)
            val ki = camera.imageIntrinsics
            val f = ki.focalLength
            val c = ki.principalPoint
            val k = CameraK(f[0], f[1], c[0], c[1])
            if (readDue) {
                lastRead = ts
                val cam = PaperReader.Camera(Mat3.rotationOf(pose), k, ts / 1e9, sensorOrientation)
                reader.process(yuv.retain(), cam, lookForCodes) { sight -> main.post { onSight?.invoke(sight) } }
            }
            if (rec != null && recordDue) {
                lastRecorded = ts
                val tracking = when (camera.trackingState) {
                    TrackingState.TRACKING -> "normal"
                    TrackingState.PAUSED -> "limited"
                    else -> "not_available"
                }
                rec.append(yuv.retain(), ts, VideoRecorder.FrameMeta(pose.copyOf(), k, tracking))
            }
        } finally {
            yuv.release()
        }
    }

    private companion object {
        const val RECORD_INTERVAL_NS = 1_000_000_000L / 30
        const val READ_INTERVAL_NS = 120_000_000L
    }
}
