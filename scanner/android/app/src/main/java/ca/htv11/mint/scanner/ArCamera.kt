package ca.htv11.mint.scanner

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Rect
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.opengl.GLES30
import android.opengl.GLSurfaceView
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.util.Log
import android.util.Size
import com.google.ar.core.CameraConfig
import com.google.ar.core.CameraConfigFilter
import com.google.ar.core.Config
import com.google.ar.core.Coordinates2d
import com.google.ar.core.Session
import java.util.EnumSet
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

/**
 * The AR session and the live camera picture: ARCore world tracking (metric camera poses, gravity up) drawn on a
 * GL view, every frame handed to [CaptureLoop]. The camera is opened as a *shared* camera when the device allows
 * it, so the app can lock focus, exposure and white balance ([CameraLock]); otherwise ARCore drives it alone.
 *
 * [start] / [stop] from the main thread (between them the camera runs). Frames arrive on the GL thread.
 */
class ArCamera(private val context: Context, private val loop: CaptureLoop) : GLSurfaceView.Renderer {
    val view = GLSurfaceView(context).apply {
        preserveEGLContextOnPause = true
        setEGLContextClientVersion(3)
        setEGLConfigChooser(8, 8, 8, 8, 16, 0)
        setRenderer(this@ArCamera)
        renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
    }

    private val cameraThread = HandlerThread("mint.camera").apply { start() }
    private val cameraHandler = Handler(cameraThread.looper)
    private val main = Handler(Looper.getMainLooper())
    val lock = CameraLock(cameraHandler)

    private val sessionLock = Any()
    private var session: Session? = null
    private var shared = false
    @Volatile private var active = false     // the session is resumed: update() may run
    private var wanted = false               // between start() and stop()
    @Volatile private var device: CameraDevice? = null
    @Volatile private var captureSession: CameraCaptureSession? = null
    private val background = BackgroundRenderer()
    @Volatile private var glReady = false
    private var viewport: Size? = null
    private var hasImage = false
    @Volatile private var pendingTap: Pair<Pair<Float, Float>, (Pair<Float, Float>?) -> Unit>? = null

    /** The CPU image every frame's poses and intrinsics refer to (sensor orientation). */
    @Volatile var imageSize = Size(640, 480)
        private set
    /** Degrees the image turns clockwise to stand upright as the phone is held (portrait). */
    @Volatile var sensorOrientation = 90
        private set
    /** Something went wrong starting the camera (shown on the screen that's up). */
    var onError: ((String) -> Unit)? = null

    // MARK: Lifecycle

    fun start() {
        wanted = true
        view.onResume()
        if (!glReady) return   // onSurfaceCreated starts it
        open()
    }

    fun stop() {
        wanted = false
        close()
        view.onPause()
    }

    /** The camera stopped while the app is open (frozen preview): run it again, keeping the session (and its world). */
    fun restart() {
        if (!wanted) return
        close()
        open()
    }

    private fun open() {
        if (!wanted || active || device != null) return
        try {
            val s = session ?: createSession().also { session = it }
            if (glReady) s.setCameraTextureName(background.textureId)
            if (shared) openShared(s) else resume(s)
        } catch (e: Exception) {
            Log.w(TAG, "camera start failed", e)
            onError?.invoke(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun close() {
        synchronized(sessionLock) {
            active = false
            session?.let { runCatching { it.pause() } }
        }
        lock.detach()
        runCatching { captureSession?.close() }
        runCatching { device?.close() }
        captureSession = null
        device = null
    }

    fun destroy() {
        stop()
        session?.close()
        session = null
        cameraThread.quitSafely()
    }

    private fun createSession(): Session {
        val s = try {
            Session(context, EnumSet.of(Session.Feature.SHARED_CAMERA)).also { shared = true }
        } catch (e: Exception) {
            Log.i(TAG, "no shared camera: ${e.message}")
            shared = false
            Session(context)
        }
        configure(s)
        return s
    }

    private fun configure(s: Session) {
        // The back camera's widest 4:3 image up to 1920 px at 30 fps: the recorded video is scaled from it, and its
        // intrinsics refer to exactly these pixels (the poses stay exact). 4:3 is the whole sensor, uncropped.
        val filter = CameraConfigFilter(s).setFacingDirection(CameraConfig.FacingDirection.BACK)
        val configs = s.getSupportedCameraConfigs(filter)
        fun aspect43(c: CameraConfig) = c.imageSize.width * 3 == c.imageSize.height * 4
        fun fps30(c: CameraConfig) = c.fpsRange.upper >= 30
        val pick = configs.filter { aspect43(it) && fps30(it) && it.imageSize.width <= 1920 }.maxByOrNull { it.imageSize.width }
            ?: configs.filter { it.imageSize.width <= 1920 }.maxByOrNull { it.imageSize.width }
            ?: configs.firstOrNull()
        pick?.let { s.cameraConfig = it }
        imageSize = s.cameraConfig.imageSize
        val manager = context.getSystemService(CameraManager::class.java)
        sensorOrientation = runCatching {
            manager.getCameraCharacteristics(s.cameraConfig.cameraId).get(CameraCharacteristics.SENSOR_ORIENTATION)
        }.getOrNull() ?: 90
        Log.i(TAG, "camera ${s.cameraConfig.cameraId} image $imageSize texture ${s.cameraConfig.textureSize} shared=$shared")

        val config = Config(s).apply {
            focusMode = Config.FocusMode.AUTO
            updateMode = Config.UpdateMode.BLOCKING   // one draw per camera frame: every frame reaches the recorder
            planeFindingMode = Config.PlaneFindingMode.DISABLED
            lightEstimationMode = Config.LightEstimationMode.DISABLED
            depthMode = Config.DepthMode.DISABLED
            instantPlacementMode = Config.InstantPlacementMode.DISABLED
        }
        s.configure(config)
    }

    private fun resume(s: Session) {
        synchronized(sessionLock) {
            s.resume()
            active = true
        }
    }

    @SuppressLint("MissingPermission")   // MainActivity starts the camera only once it's granted
    private fun openShared(s: Session) {
        val sharedCamera = s.sharedCamera
        val cameraId = s.cameraConfig.cameraId
        val manager = context.getSystemService(CameraManager::class.java)
        val array = manager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
            ?: Rect(0, 0, imageSize.width, imageSize.height)
        val sessionCallback = object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(cs: CameraCaptureSession) {
                captureSession = cs
                val d = device ?: return
                lock.attach(d, cs, sharedCamera.arCoreSurfaces, array)
                main.post {
                    if (!wanted || captureSession !== cs) return@post
                    try { resume(s) } catch (e: Exception) { fallBack("resume failed: ${e.message}") }
                }
            }

            override fun onConfigureFailed(cs: CameraCaptureSession) { main.post { fallBack("capture session failed") } }
        }
        val deviceCallback = object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) {
                device = d
                try {
                    @Suppress("DEPRECATION")
                    d.createCaptureSession(sharedCamera.arCoreSurfaces, sharedCamera.createARSessionStateCallback(sessionCallback, cameraHandler), cameraHandler)
                } catch (e: Exception) {
                    main.post { fallBack("capture session: ${e.message}") }
                }
            }

            override fun onDisconnected(d: CameraDevice) {
                d.close()
                if (device === d) device = null
                main.postDelayed({ restart() }, 500)   // another app had the camera: take it back
            }

            override fun onError(d: CameraDevice, error: Int) {
                d.close()
                if (device === d) device = null
                main.postDelayed({ restart() }, 500)
            }
        }
        manager.openCamera(cameraId, sharedCamera.createARDeviceStateCallback(deviceCallback, cameraHandler), cameraHandler)
    }

    /** The shared camera didn't come up on this device: let ARCore drive the camera (no focus or exposure locks). */
    private fun fallBack(why: String) {
        if (!shared) return
        Log.w(TAG, "shared camera unavailable ($why): ARCore drives the camera")
        close()
        session?.close()
        session = null
        shared = false
        if (wanted) {
            session = Session(context).also { configure(it) }
            open()
        }
    }

    /**
     * View pixels → sensor-normalized (the camera's landscape image, top-left origin), on the next frame. `done` gets
     * null when there's no frame (the camera isn't running). Called on the GL thread.
     */
    fun toSensor(x: Float, y: Float, done: (Pair<Float, Float>?) -> Unit) {
        if (!active) { done(null); return }
        pendingTap = (x to y) to done
    }

    // MARK: GL

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        GLES30.glClearColor(0f, 0f, 0f, 1f)
        background.create()
        glReady = true
        main.post {
            session?.setCameraTextureName(background.textureId)
            if (wanted) open()
        }
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        GLES30.glViewport(0, 0, width, height)
        viewport = Size(width, height)
        synchronized(sessionLock) { session?.setDisplayGeometry(android.view.Surface.ROTATION_0, width, height) }
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT or GLES30.GL_DEPTH_BUFFER_BIT)
        synchronized(sessionLock) {
            val s = session
            if (s == null || !active) {
                if (hasImage) background.draw()
                return
            }
            viewport?.let { s.setDisplayGeometry(android.view.Surface.ROTATION_0, it.width, it.height) }
            val frame = try { s.update() } catch (e: Exception) {
                if (hasImage) background.draw()
                return
            }
            background.draw(frame)
            if (frame.timestamp != 0L) hasImage = true
            pendingTap?.let { (p, done) ->
                pendingTap = null
                val out = FloatArray(2)
                frame.transformCoordinates2d(Coordinates2d.VIEW, floatArrayOf(p.first, p.second), Coordinates2d.IMAGE_NORMALIZED, out)
                done(out[0] to out[1])
            }
            loop.onFrame(frame, imageSize, sensorOrientation)
        }
    }

    private companion object {
        const val TAG = "MintCamera"
    }
}
