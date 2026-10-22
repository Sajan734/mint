package ca.htv11.mint.scanner

import android.content.Context
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import ca.htv11.mint.coveragekit.PaperTurn
import ca.htv11.mint.coveragekit.ScanLinks
import ca.htv11.mint.coveragekit.TurnCoverage
import ca.htv11.mint.coveragekit.UploadPlan
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.UUID
import kotlin.math.PI
import kotlin.math.abs

/**
 * The app, start to finish, for one product at a time:
 *
 *   waiting  ── a mint:// link from the website (QR code read by the phone's camera app or by this screen),
 *      │        the dashboard's auto-pickup, or "scan without the dashboard"
 *      ↓
 *   ready → recording (until the stop button) → saving → review ─┬─ Scan again → ready (the next pass)
 *                                                                ├─ Discard the last pass
 *                                                                └─ Done → sending → finished ("look at your computer")
 *                                                                                       ↓ (next request, or Next product)
 *                                                                                    waiting
 *
 * One product = one scan_id = one or more passes (a lap, then maybe flipped over, …). A job is either a
 * seller's listing scan or a buyer's verify rescan of a listing (in-person deal). The ring shows how
 * much of one lap has been seen, measured from the paper's turn; it's a guide and never ends a pass.
 *
 * Main thread only. Compose reads the state directly.
 */
class CaptureSession(private val context: Context) {
    sealed interface Phase {
        data object Waiting : Phase
        data object Ready : Phase
        data object Recording : Phase
        data object Saving : Phase
        data object Review : Phase
        data class Sending(val progress: Double) : Phase
        data object Finished : Phase
        data class Failed(val message: String) : Phase
    }

    /** The product being scanned. */
    data class Job(
        val scanId: String,
        val fromDashboard: Boolean,
        val title: String?,
        /** A buyer's verify rescan of this listing (null: a seller's listing scan). */
        val listingId: String? = null,
    ) {
        val isVerify: Boolean get() = listingId != null
    }

    /** Whether the dashboard can be reached (shown on the waiting screen). */
    enum class Link { NOT_SET_UP, CONNECTING, ONLINE, OFFLINE }

    companion object {
        /** A pass stops by itself only here: Storage takes 50 MB per file and the video is ~1 MB/s. */
        const val MAX_PASS_SECONDS = 45.0
        /** Ticks round the ring: 5° each, clockwise from the top, like the item's sides seen from above. */
        const val TICK_COUNT = 72
    }

    var phase: Phase by mutableStateOf(Phase.Waiting)
        private set
    var job: Job? by mutableStateOf(null)
        private set
    var link: Link by mutableStateOf(if (DashboardLink.url == null) Link.NOT_SET_UP else Link.CONNECTING)
        private set
    /** Uptime (ms) the current pass started. */
    var recordStart: Long? by mutableStateOf(null)
        private set
    var passes: List<VideoRecorder.Summary> by mutableStateOf(emptyList())
        private set
    /** How much of one lap has been seen ([TurnCoverage]): measured from the paper's turn, nothing scripted. */
    var percent by mutableIntStateOf(0)
        private set
    /**
     * ticks[i], 0…1: how well the item's side i × 5° (clockwise from above, from the side that faced the
     * camera at the start) has been seen head-on.
     */
    var ticks: List<Double> by mutableStateOf(List(TICK_COUNT) { 0.0 })
        private set
    /**
     * How far the paper has turned this pass (radians, clockwise from above), eased for display: the ring's
     * bright spot sits at this angle (clockwise from the top), on the side the camera is looking at now.
     */
    var ringTurn by mutableDoubleStateOf(0.0)
        private set
    /** Uptime (ms) the lap was completed. */
    var lapCompletedAt: Long? by mutableStateOf(null)
        private set
    /** The sheet's edges were read in the last moment (false: no paper, or hands covering it). */
    var paperSeen by mutableStateOf(false)
        private set

    val isRecording: Boolean get() = phase == Phase.Recording
    val inScanner: Boolean get() = phase == Phase.Ready || phase == Phase.Recording || phase == Phase.Saving || phase == Phase.Review
    val nextPass: Int get() = passes.size + 1
    val isSending: Boolean get() = phase is Phase.Sending

    val loop = CaptureLoop()
    val camera = ArCamera(context, loop)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var ticker: CoroutineJob? = null
    private var poller: CoroutineJob? = null
    private val handled = mutableSetOf<String>()
    private val sent = mutableSetOf<String>()
    private var linkFailures = 0
    private val turn = PaperTurn()
    private var coverage = TurnCoverage()
    private var lastObservation: Double? = null
    private var lastPaperAt = 0L
    private var fullSlices = 0
    private var previewing = false   // debug screen previews only
    private var reportedTenth = -1
    private var exposureLocked = false
    /** The camera should be running (between [run] and [pause]). */
    var isRunning = false
        private set
    private var startedAt = 0L
    private var lastRestart = 0L
    private val haptics = Haptics(context)

    init {
        loop.onSight = { apply(it) }
        loop.lookForCodes = true   // read QR codes from the very first screen
        // The screen that's up stays: the frame watchdog in onTick restarts the camera.
        camera.onError = { message -> android.util.Log.w("MintSession", "camera: $message") }
    }

    private fun enter(p: Phase) {
        phase = p
        loop.lookForCodes = readsCodes(p)
    }

    /** Read QR codes only while waiting for a product (or on the done / failed screens). */
    private fun readsCodes(p: Phase) = p == Phase.Waiting || p == Phase.Finished || p is Phase.Failed

    // MARK: - Lifecycle

    /** Starts the camera, AR tracking, the 30 Hz tick and the dashboard polling. Safe to call again. */
    fun run() {
        camera.start()
        isRunning = true
        startedAt = SystemClock.uptimeMillis()
        ticker?.cancel()
        ticker = scope.launch {
            while (isActive) {
                onTick()
                delay(1000L / 30)
            }
        }
        startPolling()
    }

    /** Back in the foreground (from the camera app's QR banner, the app switcher, a call…): run again if paused. */
    fun resume() { if (!isRunning) run() }

    fun pause() {
        if (phase == Phase.Recording) cancelPass()
        camera.stop()
        isRunning = false
        ticker?.cancel()
        poller?.cancel()
        poller = null
    }

    fun destroy() {
        pause()
        camera.destroy()
    }

    /**
     * The camera stopped while the app is open (frozen preview: no frames for a while, the camera came back from
     * another app, or the session failed). Run it again; ARCore keeps its world, so a pass's poses stay in one
     * frame. At most once every 2 s.
     */
    private fun restartCamera() {
        val now = SystemClock.uptimeMillis()
        if (!isRunning || now - lastRestart <= 2000) return
        lastRestart = now
        camera.restart()
        if (phase == Phase.Recording) camera.lock.lock()
    }

    // MARK: - Getting a product to scan

    /** While waiting (or showing "done"), ask the dashboard for the next "New product" every 1.5 s. */
    private fun startPolling() {
        poller?.cancel()
        if (DashboardLink.url == null) { link = Link.NOT_SET_UP; return }
        poller = scope.launch {
            while (isActive) {
                if (phase == Phase.Waiting || phase == Phase.Finished) {
                    try {
                        val request = DashboardLink.next()
                        linkFailures = 0
                        link = Link.ONLINE
                        if (request != null && request.scanId !in handled && (phase == Phase.Waiting || phase == Phase.Finished)) {
                            val listing = if (request.kind == "verify") request.listingScanId else null
                            begin(Job(request.scanId, fromDashboard = true, title = request.title, listingId = listing))
                        }
                    } catch (_: Exception) {
                        linkFailures += 1
                        if (linkFailures >= 2) link = Link.OFFLINE
                    }
                }
                delay(1500)
            }
        }
    }

    /** A website link (`mint://scan?id=…` / `mint://verify?id=…&listing=…`) opened the app. */
    fun open(url: String) = follow(url, explicit = true)

    /**
     * `explicit`: the link was opened on purpose (tapped, or from the camera app's QR banner). Such a link always
     * wins, unless that scan was already sent or something has been recorded for the current one. A QR code read
     * by this app's own camera never reopens an id it has seen: a cancelled scan's QR may still be on the laptop's screen.
     */
    private fun follow(text: String, explicit: Boolean = false) {
        val l = ScanLinks.parse(text) ?: return
        if (isSending || l.scanId in sent || l.scanId == job?.scanId || (!explicit && l.scanId in handled)) return
        if (inScanner) {
            // In the scanner only before anything was recorded: drop that job for the new one.
            val old = job
            if (phase != Phase.Ready || passes.isNotEmpty() || old == null) return
            DashboardLink.report(DashboardLink.Status.CANCELLED, old.scanId, 0)
        }
        begin(Job(l.scanId, fromDashboard = true, title = null, listingId = l.listingId))
    }

    /** No dashboard: scan anyway (the product gets its own scan_id). */
    fun scanWithoutDashboard() = begin(Job(UUID.randomUUID().toString().lowercase(), fromDashboard = false, title = null))

    private fun begin(j: Job) {
        handled.add(j.scanId)
        camera.lock.unlock(resetPoint = true)   // a new item: focus on the middle until tapped
        job = j
        passes = emptyList()
        resetCoverage()
        enter(Phase.Ready)
        haptics.success()
        DashboardLink.report(DashboardLink.Status.SCANNING, j.scanId, 0)
    }

    /** Give up on this product (from the scanner, before sending): its passes are deleted. */
    fun cancelJob() {
        val j = job ?: return
        if (phase != Phase.Ready && phase != Phase.Review) return
        VideoRecorder.folder(context, j.scanId).deleteRecursively()
        DashboardLink.report(DashboardLink.Status.CANCELLED, j.scanId, 0)
        backToWaiting()
    }

    fun backToWaiting() {
        camera.lock.unlock(resetPoint = true)
        job = null
        passes = emptyList()
        recordStart = null
        resetCoverage()
        enter(Phase.Waiting)
    }

    // MARK: - Passes

    /** The big button: start a pass, or finish it. */
    fun primaryAction() {
        when (phase) {
            Phase.Ready -> startPass()
            Phase.Recording -> stopPass()
            else -> {}
        }
    }

    /** Another pass of the same product (flipped over, another height, touch-ups). */
    fun scanAgain() {
        if (phase != Phase.Review) return
        resetCoverage()
        enter(Phase.Ready)
    }

    /** Throws away the most recent pass. */
    fun discardLastPass() {
        val j = job ?: return
        val last = passes.lastOrNull() ?: return
        if (phase != Phase.Review) return
        passes = passes.dropLast(1)
        last.directory.deleteRecursively()
        DashboardLink.report(DashboardLink.Status.SCANNING, j.scanId, passes.size)
        if (passes.isEmpty()) {
            resetCoverage()
            enter(Phase.Ready)
        }
    }

    private fun resetCoverage() {
        coverage = TurnCoverage()
        lastObservation = null
        fullSlices = 0
        lapCompletedAt = null
        ringTurn = 0.0
        publishCoverage()
    }

    private fun startPass() {
        val j = job ?: return
        val recorder = try {
            VideoRecorder(context, j.scanId, nextPass, j.listingId, camera.imageSize, camera.sensorOrientation)
        } catch (e: Exception) {
            enter(Phase.Failed("Couldn't start recording: ${e.message}"))
            return
        }
        exposureLocked = camera.lock.lock()
        turn.restart()
        resetCoverage()
        recordStart = SystemClock.uptimeMillis()
        enter(Phase.Recording)
        haptics.heavy()
        loop.startRecording(recorder)
    }

    private fun stopPass() {
        if (phase != Phase.Recording) return
        enter(Phase.Saving)
        haptics.heavy()
        val locked = exposureLocked
        val pct = percent
        val recorder = loop.stopRecording()
        if (recorder == null) {
            enter(Phase.Failed("Nothing was recorded."))
            return
        }
        recorder.finish(locked, pct) { result ->
            camera.lock.unlock()
            result.onSuccess { s ->
                passes = passes + s
                enter(Phase.Review)
                job?.let { DashboardLink.report(DashboardLink.Status.SCANNING, it.scanId, passes.size) }
            }.onFailure { e ->
                enter(Phase.Failed(if (e.message == "Nothing was recorded.") e.message!! else "Couldn't save: ${e.message}"))
            }
        }
    }

    private fun cancelPass() {
        loop.cancel()
        camera.lock.unlock()
        enter(if (passes.isEmpty()) Phase.Ready else Phase.Review)
        recordStart = null
    }

    // MARK: - Sending

    /** Done with this product: send every pass, then tell the seller to look at their computer. */
    fun finish() {
        val j = job ?: return
        if (phase != Phase.Review || passes.isEmpty()) return
        send(j)
    }

    fun retrySend() {
        val j = job ?: return
        if (phase !is Phase.Failed || passes.isEmpty()) return
        send(j)
    }

    private fun send(j: Job) {
        enter(Phase.Sending(0.0))
        reportedTenth = -1
        val count = passes.size
        val list = passes.map { UploadPlan.Pass(it.directory, it.pass) }
        DashboardLink.report(DashboardLink.Status.UPLOADING, j.scanId, count, 0.0)
        scope.launch {
            try {
                SupabaseUploader.upload(j.scanId, list, j.isVerify) { p ->
                    scope.launch {
                        if (!isSending) return@launch
                        enter(Phase.Sending(p))
                        val tenth = (p * 10).toInt()
                        if (tenth != reportedTenth) {
                            reportedTenth = tenth
                            DashboardLink.report(DashboardLink.Status.UPLOADING, j.scanId, count, p)
                        }
                    }
                }
                sent.add(j.scanId)
                DashboardLink.report(DashboardLink.Status.UPLOADED, j.scanId, count, 1.0)
                haptics.success()
                enter(Phase.Finished)
            } catch (e: Exception) {
                enter(Phase.Failed(e.message ?: e.javaClass.simpleName))
            }
        }
    }

    // MARK: - Measuring

    /**
     * 30 Hz: the size limit on a pass, whether the paper is in view, and easing the ring's turn towards the
     * latest reading (they come ~8 times a second).
     */
    private fun onTick() {
        // Watchdog: frames normally arrive 30 times a second. None for 1.5 s (and not just started) = frozen.
        val now = SystemClock.uptimeMillis()
        if (isRunning && !previewing && now - startedAt > 3000 && now - loop.lastFrameAt > 1500) restartCamera()
        val start = recordStart
        if (phase == Phase.Recording && start != null && (now - start) / 1000.0 >= MAX_PASS_SECONDS) stopPass()
        val seen = now - lastPaperAt < 600
        if (seen != paperSeen) paperSeen = seen
        // The ring follows the paper while recording, then stays where the paper stopped.
        val goal = turn.turned.toDouble()
        if (phase == Phase.Recording && lapCompletedAt == null && !previewing && abs(goal - ringTurn) > 0.0005) ringTurn += (goal - ringTurn) * 0.3
    }

    /**
     * A new reading of the frame: a QR code (while waiting), or how far the paper has turned, which while
     * recording fills the coverage.
     */
    private fun apply(sight: PaperReader.Sight) {
        sight.code?.let { follow(it) }
        val reading = sight.paper ?: return
        if (!turn.update(reading, sight.timestamp)) return
        lastPaperAt = SystemClock.uptimeMillis()
        // Once the lap is done the measurement stops: hand-held touch-ups (walking round, other heights)
        // vary run to run, and the ring just stays full.
        val elevation = sight.elevation ?: return
        if (phase != Phase.Recording || lapCompletedAt != null) return
        coverage.observe(turn.turned, elevation, lastObservation?.let { sight.timestamp - it } ?: 0.0)
        lastObservation = sight.timestamp
        publishCoverage()
    }

    // MARK: - Tap to focus

    /**
     * Focus where the camera view was tapped (view pixels), like the camera app. Before a scan, focus and exposure
     * follow that point until the scan starts and locks them; during a scan, focus runs once there and holds
     * (exposure stays locked). false: the camera isn't running or can't be set.
     */
    fun focus(viewX: Float, viewY: Float): Boolean {
        if (!isRunning || !(phase == Phase.Waiting || phase == Phase.Ready || phase == Phase.Recording) || !camera.lock.isAvailable) return false
        val hold = phase == Phase.Recording
        camera.view.queueEvent {
            camera.toSensor(viewX, viewY) { p ->
                if (p != null) scope.launch { camera.lock.focus(p, holdExposure = hold) }
            }
        }
        haptics.tick(0.6f)
        return true
    }

    private fun publishCoverage() {
        percent = coverage.percent
        ticks = List(TICK_COUNT) { i -> coverage.level((i.toFloat() / TICK_COUNT * 2 * PI).toFloat()).toDouble() }
        // A tick of the phone for every 10° slice that fills, a big one when the lap is done (the pass carries on).
        val full = coverage.fill[0].count { it >= 0.98f }
        if (full > fullSlices && phase == Phase.Recording) haptics.tick(0.45f)
        fullSlices = full
        if (percent >= 100 && lapCompletedAt == null && phase == Phase.Recording) {
            lapCompletedAt = SystemClock.uptimeMillis()
            haptics.success()
        }
    }

    /**
     * Design check only (debug builds): `adb shell am start … --es MintPreview ready|early|recording|verify|full|review|sending|finished|failed`
     * puts the app on that screen with made-up coverage so the layout can be screenshotted without a real scan.
     * Never in a release build, never on stage.
     */
    fun preview(screen: String) {
        if (!BuildConfig.DEBUG) return
        poller?.cancel()
        previewing = true
        val j = Job(
            UUID.randomUUID().toString().lowercase(), fromDashboard = true, title = "Logitech M325 mouse",
            listingId = if (screen.startsWith("verify")) UUID.randomUUID().toString().lowercase() else null,
        )
        job = j
        val fake = VideoRecorder.Summary(java.io.File("/nonexistent"), j.scanId, 1, 23.0, 690, 23.0)
        lastPaperAt = Long.MAX_VALUE / 2
        // Made-up coverage: the paper turned `deg` clockwise, so sides −deg…0 have been seen.
        fun fill(deg: Double) {
            ticks = List(TICK_COUNT) { i ->
                val side = (360 - i * 5.0) % 360
                if (side <= deg) 1.0 else if (side <= deg + 20) 0.4 else 0.0
            }
            ringTurn = deg * PI / 180
            percent = minOf(100.0, deg / 3.15).toInt()
        }
        val now = SystemClock.uptimeMillis()
        when (screen) {
            "ready" -> enter(Phase.Ready)
            "early" -> { recordStart = now - 4000; fill(120.0); enter(Phase.Recording) }
            "recording", "verify" -> { recordStart = now - 9000; fill(205.0); enter(Phase.Recording) }
            "full" -> { recordStart = now - 17000; fill(360.0); lapCompletedAt = now; enter(Phase.Recording) }
            "review" -> { fill(360.0); passes = listOf(fake); enter(Phase.Review) }
            "sending" -> { passes = listOf(fake, fake); enter(Phase.Sending(0.62)) }
            "finished" -> { passes = listOf(fake); enter(Phase.Finished) }
            "failed" -> { passes = listOf(fake); enter(Phase.Failed("Couldn't get upload links: {\"code\":\"NOT_FOUND\"}")) }
            else -> { job = null; link = Link.ONLINE }
        }
    }
}

/** The phone's taptic moments: a light tick, a heavy bump, a success buzz. */
private class Haptics(context: Context) {
    private val vibrator = context.getSystemService(Vibrator::class.java)

    fun tick(intensity: Float) = vibrate(VibrationEffect.createOneShot(12, (255 * intensity).toInt().coerceIn(1, 255)))
    fun heavy() = vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK))
    fun success() = vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_DOUBLE_CLICK))

    private fun vibrate(effect: VibrationEffect) {
        runCatching { if (vibrator?.hasVibrator() == true) vibrator.vibrate(effect) }
    }
}
