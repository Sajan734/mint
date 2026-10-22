package ca.htv11.mint.scanner

import android.graphics.Rect
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.MeteringRectangle
import android.os.Handler
import android.view.Surface

/**
 * Camera control for a sharp, consistent scan, through the Camera2 device ARCore shares with the app.
 *
 * - While lining up, autofocus and auto exposure are continuous, on the middle of the frame or on the point
 *   the user tapped ([focus]), like the camera app.
 * - At scan start, focus, exposure and white balance lock ([lock]). In a turntable scan the phone stays
 *   still and the item turns, so the distance never changes: a locked focus keeps every frame sharp, where
 *   continuous autofocus hunts as the item turns, blurs frames (the edges first) and shifts the focal length
 *   a little between frames, which the splat cannot model.
 * - A tap during a scan focuses once on that point and holds it there; exposure and white balance stay locked.
 *
 * Calls come from the main thread; requests go out on the camera's handler thread. Without a shared camera
 * (ARCore drives the camera itself) every call returns false and the scan runs on ARCore's autofocus.
 */
class CameraLock(private val handler: Handler) {
    private class Target(val device: CameraDevice, val session: CameraCaptureSession, val surfaces: List<Surface>, val array: Rect)

    @Volatile private var target: Target? = null
    private var point = CENTRE          // sensor-normalized (0…1, top-left origin, the camera's landscape image)
    private var aeLocked = false
    private var afMode = CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO

    val isAvailable: Boolean get() = target != null

    /** The camera is open and streaming to ARCore's surfaces: from now on requests go to it. */
    fun attach(device: CameraDevice, session: CameraCaptureSession, surfaces: List<Surface>, activeArray: Rect) {
        target = Target(device, session, surfaces, activeArray)
        handler.post { send(trigger = null) }
    }

    fun detach() { target = null }

    fun lock(): Boolean = configure {
        // Still settling or not: a trigger in continuous mode finishes the current focus, then holds it.
        aeLocked = true
        afMode = CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO
        CameraMetadata.CONTROL_AF_TRIGGER_START
    }

    /**
     * Tap to focus. `p` is sensor-normalized. Before a scan, focus and exposure keep following that point; during
     * one (`holdExposure`), focus runs once there and holds, and exposure and white balance stay locked so every
     * frame of the scan has the same brightness.
     */
    fun focus(p: Pair<Float, Float>, holdExposure: Boolean): Boolean = configure {
        point = p.first.coerceIn(0f, 1f) to p.second.coerceIn(0f, 1f)
        if (holdExposure) {
            afMode = CameraMetadata.CONTROL_AF_MODE_AUTO
            CameraMetadata.CONTROL_AF_TRIGGER_START
        } else {
            aeLocked = false
            afMode = CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO
            CameraMetadata.CONTROL_AF_TRIGGER_CANCEL
        }
    }

    /** Back to continuous autofocus and exposure. `resetPoint`: on the middle of the frame again (a new item). */
    fun unlock(resetPoint: Boolean = false) {
        configure {
            if (resetPoint) point = CENTRE
            aeLocked = false
            afMode = CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO
            CameraMetadata.CONTROL_AF_TRIGGER_CANCEL
        }
    }

    /** Applies the state change; the returned trigger (if any) goes out once, then the repeating request. */
    private fun configure(change: () -> Int?): Boolean {
        if (target == null) return false
        val trigger = change()
        handler.post { send(trigger) }
        return true
    }

    private fun send(trigger: Int?) {
        val t = target ?: return
        try {
            if (trigger != null) t.session.capture(build(t, trigger), null, handler)
            t.session.setRepeatingRequest(build(t, null), null, handler)
        } catch (_: Exception) {
            // The camera closed underneath (pause, another app): the next attach sends the state again.
        }
    }

    private fun build(t: Target, trigger: Int?): CaptureRequest {
        val b = t.device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD)
        t.surfaces.forEach(b::addTarget)
        b.set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO)
        b.set(CaptureRequest.CONTROL_AF_MODE, afMode)
        b.set(CaptureRequest.CONTROL_AE_MODE, CameraMetadata.CONTROL_AE_MODE_ON)
        b.set(CaptureRequest.CONTROL_AE_LOCK, aeLocked)
        b.set(CaptureRequest.CONTROL_AWB_LOCK, aeLocked)
        val region = arrayOf(region(t.array))
        b.set(CaptureRequest.CONTROL_AF_REGIONS, region)
        b.set(CaptureRequest.CONTROL_AE_REGIONS, region)
        if (trigger != null) b.set(CaptureRequest.CONTROL_AF_TRIGGER, trigger)
        return b.build()
    }

    /** A box an eighth of the sensor wide round the point, in active-array pixels. */
    private fun region(a: Rect): MeteringRectangle {
        val w = a.width() / 8
        val h = a.height() / 8
        val x = (a.left + point.first * a.width() - w / 2).toInt().coerceIn(a.left, a.right - w)
        val y = (a.top + point.second * a.height() - h / 2).toInt().coerceIn(a.top, a.bottom - h)
        return MeteringRectangle(x, y, w, h, MeteringRectangle.METERING_WEIGHT_MAX - 1)
    }

    private companion object {
        val CENTRE = 0.5f to 0.5f
    }
}
