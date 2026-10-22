package ca.htv11.mint.scanner

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Size
import ca.htv11.mint.coveragekit.CameraK
import ca.htv11.mint.coveragekit.CaptureInfo
import ca.htv11.mint.coveragekit.CaptureJson
import ca.htv11.mint.coveragekit.FastSharpness
import ca.htv11.mint.coveragekit.Geometry
import ca.htv11.mint.coveragekit.PoseRecord
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.Writer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.roundToInt

/**
 * Writes one pass of a scan to files/scans/{scan_id}/pass{n}/ (an item can have several passes, e.g. upright then
 * flipped over; they share the scan_id):
 *   video.mp4     H.264, 960 × 720 from a 4:3 camera image (smaller images are kept at their own size), sensor
 *                 (landscape) orientation, no B-frames, 8 Mbps; frame n ↔ poses.jsonl line n
 *   poses.jsonl   one [PoseRecord] per video frame (raw AR camera pose + K for the video's pixels)
 *   capture.json  session info
 *   thumb.jpg     the first frame, upright, for the UI
 * Frames are encoded on the recorder's own thread, in order; a frame the encoder can't take gets no pose line.
 */
class VideoRecorder(
    context: Context,
    val scanId: String,
    val pass: Int,
    /** The listing a verify rescan is checked against (null: a seller's listing scan). */
    val listingId: String?,
    /** The camera image the poses and intrinsics refer to. */
    private val sensorSize: Size,
    private val sensorOrientation: Int,
) {
    class Summary(val directory: File, val scanId: String, val pass: Int, val seconds: Double, val frames: Int, val megabytes: Double)

    class FrameMeta(
        val cameraPose: FloatArray,   // column-major 4×4, raw AR camera pose (camera-to-world)
        val intrinsics: CameraK,      // camera-image pixels
        val tracking: String,
    )

    val directory: File = File(folder(context, scanId), "pass$pass").apply { mkdirs() }
    val videoSize: Size = videoSize(sensorSize)

    private val thread = Executors.newSingleThreadExecutor { Thread(it, "mint.record") }
    private val main = Handler(Looper.getMainLooper())
    private val pending = AtomicInteger(0)
    private val startDate = Date()
    private val codec: MediaCodec
    private val muxer: MediaMuxer
    private val poses: Writer
    private var track = -1
    private var muxing = false
    private var t0 = -1L
    private var lastTimestamp = -1L
    private var frameIndex = 0
    private val info = MediaCodec.BufferInfo()
    private val sx = videoSize.width.toFloat() / sensorSize.width
    private val sy = videoSize.height.toFloat() / sensorSize.height

    init {
        val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, videoSize.width, videoSize.height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
            setInteger(MediaFormat.KEY_BIT_RATE, 8_000_000)          // generous for 720p: sharp detail for the splat
            setInteger(MediaFormat.KEY_FRAME_RATE, 30)
            setFloat(MediaFormat.KEY_I_FRAME_INTERVAL, 0.5f)         // a key frame every 15 frames
            setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)              // decode order = capture order
            if (supportsHighProfile()) {
                setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileHigh)
                setInteger(MediaFormat.KEY_LEVEL, MediaCodecInfo.CodecProfileLevel.AVCLevel41)
            }
        }
        codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        codec.start()
        muxer = MediaMuxer(File(directory, "video.mp4").path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        poses = File(directory, "poses.jsonl").bufferedWriter()
    }

    /** Adds one frame to the video and the pose log (the log only gets lines for frames in the video). Takes `yuv` (retained). */
    fun append(yuv: YuvFrame, timestampNs: Long, meta: FrameMeta) {
        if (pending.get() >= 4) { yuv.release(); return }   // the encoder is behind: drop rather than pile up
        pending.incrementAndGet()
        thread.execute {
            try { encode(yuv, timestampNs, meta) } catch (_: Exception) { } finally {
                yuv.release()
                pending.decrementAndGet()
            }
        }
    }

    private fun encode(yuv: YuvFrame, ts: Long, meta: FrameMeta) {
        if (ts <= lastTimestamp) return
        val index = codec.dequeueInputBuffer(10_000)
        if (index < 0) return
        val image = codec.getInputImage(index) ?: run { codec.queueInputBuffer(index, 0, 0, 0, 0); return }
        writeScaled(yuv, image)
        if (t0 < 0) {
            t0 = ts
            saveThumbnail(yuv)
        }
        val us = (ts - t0) / 1000
        codec.queueInputBuffer(index, 0, videoSize.width * videoSize.height * 3 / 2, us, 0)
        lastTimestamp = ts
        drain(endOfStream = false)

        val sharpness = FastSharpness.measure(yuv.y, yuv.width, yuv.height, yuv.width)?.sharpness ?: 0.0
        val pose = Geometry.rowMajor4(meta.cameraPose)
        val record = PoseRecord(
            frame = frameIndex, tMs = ((ts - t0) / 1_000_000.0).roundToInt(),
            poseWorld = pose, pose = pose,
            intrinsics = meta.intrinsics.scaled(sx, sy).rowMajor(),
            tracking = meta.tracking, state = "recording", sharpness = sharpness,
        )
        poses.write(CaptureJson.encode(record.toJson()))
        poses.write("\n")
        frameIndex += 1
    }

    /** Scales the camera image into the encoder's input (bilinear luma, nearest chroma), whatever its plane layout. */
    private fun writeScaled(yuv: YuvFrame, image: android.media.Image) {
        val ow = videoSize.width
        val oh = videoSize.height
        val iw = yuv.width
        val ih = yuv.height
        val yPlane = image.planes[0]
        val yb = yPlane.buffer
        val row = ByteArray(ow)
        val same = ow == iw && oh == ih
        val fx = ((iw - 1).toFloat() / maxOf(1, ow - 1) * 256).toInt()
        val fy = ((ih - 1).toFloat() / maxOf(1, oh - 1) * 256).toInt()
        for (y in 0 until oh) {
            if (same) {
                System.arraycopy(yuv.y, y * iw, row, 0, ow)
            } else {
                val syf = y * fy
                val y0 = syf shr 8
                val wy = syf and 0xFF
                val y1 = minOf(ih - 1, y0 + 1)
                val r0 = y0 * iw
                val r1 = y1 * iw
                for (x in 0 until ow) {
                    val sxf = x * fx
                    val x0 = sxf shr 8
                    val wx = sxf and 0xFF
                    val x1 = minOf(iw - 1, x0 + 1)
                    val a = (yuv.y[r0 + x0].toInt() and 0xFF) * (256 - wx) + (yuv.y[r0 + x1].toInt() and 0xFF) * wx
                    val b = (yuv.y[r1 + x0].toInt() and 0xFF) * (256 - wx) + (yuv.y[r1 + x1].toInt() and 0xFF) * wx
                    row[x] = ((a * (256 - wy) + b * wy) shr 16).toByte()
                }
            }
            if (yPlane.pixelStride == 1) {
                yb.position(y * yPlane.rowStride)
                yb.put(row, 0, ow)
            } else {
                for (x in 0 until ow) yb.put(y * yPlane.rowStride + x * yPlane.pixelStride, row[x])
            }
        }
        val cw = ow / 2
        val chh = oh / 2
        val icw = iw / 2
        val ich = ih / 2
        for ((plane, src) in listOf(image.planes[1] to yuv.u, image.planes[2] to yuv.v)) {
            val buf = plane.buffer
            val rs = plane.rowStride
            val ps = plane.pixelStride
            for (y in 0 until chh) {
                val sr = (y * ich / chh) * icw
                for (x in 0 until cw) buf.put(y * rs + x * ps, src[sr + x * icw / cw])
            }
        }
    }

    private fun drain(endOfStream: Boolean) {
        while (true) {
            val index = codec.dequeueOutputBuffer(info, if (endOfStream) 10_000 else 0)
            when {
                index == MediaCodec.INFO_TRY_AGAIN_LATER -> if (!endOfStream) return
                index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    track = muxer.addTrack(codec.outputFormat)
                    muxer.start()
                    muxing = true
                }
                index >= 0 -> {
                    val out = codec.getOutputBuffer(index)
                    if (out != null && info.size > 0 && muxing && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                        out.position(info.offset)
                        out.limit(info.offset + info.size)
                        muxer.writeSampleData(track, out, info)
                    }
                    codec.releaseOutputBuffer(index, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) return
                }
            }
        }
    }

    /** Closes the video and writes capture.json. `completion` runs on the main thread. */
    fun finish(exposureLocked: Boolean, coveragePct: Int, completion: (Result<Summary>) -> Unit) {
        thread.execute {
            val result = runCatching {
                val frames = frameIndex
                val seconds = if (t0 < 0) 0.0 else (lastTimestamp - t0) / 1e9
                val index = codec.dequeueInputBuffer(100_000)
                if (index >= 0) codec.queueInputBuffer(index, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                if (muxing || frames > 0) drain(endOfStream = true)
                codec.stop()
                codec.release()
                poses.close()
                if (!muxing || frames == 0) {
                    runCatching { muxer.release() }
                    directory.deleteRecursively()
                    throw IllegalStateException("Nothing was recorded.")
                }
                muxer.stop()
                muxer.release()
                val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }
                val capture = CaptureInfo(
                    scanId = scanId, device = deviceModel(), os = Build.VERSION.RELEASE, createdAt = iso.format(startDate),
                    durationMs = (seconds * 1000).roundToInt(), video = "video.mp4",
                    videoWidth = videoSize.width, videoHeight = videoSize.height, videoFrames = frames,
                    sensorWidth = sensorSize.width, sensorHeight = sensorSize.height, orientation = "sensor_landscape",
                    exposureLocked = exposureLocked, mode = "turntable", coveragePct = coveragePct, pass = pass,
                    kind = if (listingId == null) "listing" else "handover", listingScanId = listingId, platform = "android",
                )
                File(directory, "capture.json").writeText(CaptureJson.encode(capture.toJson(), pretty = true))
                val bytes = directory.listFiles()?.sumOf { it.length() } ?: 0
                Summary(directory, scanId, pass, seconds, frames, bytes / 1_000_000.0)
            }
            thread.shutdown()
            main.post { completion(result) }
        }
    }

    /** Stops without saving: removes the folder. */
    fun cancel() {
        thread.execute {
            runCatching { codec.stop() }
            runCatching { codec.release() }
            runCatching { if (muxing) muxer.stop() }
            runCatching { muxer.release() }
            runCatching { poses.close() }
            directory.deleteRecursively()
            thread.shutdown()
        }
    }

    /** The first frame, turned upright as the phone was held, as thumb.jpg (for the UI). */
    private fun saveThumbnail(yuv: YuvFrame) {
        val (nv21, w, h) = yuv.nv21()
        val file = File(directory, "thumb.jpg")
        Thread {
            runCatching {
                val jpeg = ByteArrayOutputStream().also { YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 90, it) }.toByteArray()
                var bmp = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
                val scale = videoSize.width.toFloat() / w
                val m = Matrix().apply { postScale(scale, scale); postRotate(sensorOrientation.toFloat()) }
                bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
                file.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 80, it) }
            }
        }.start()
    }

    companion object {
        /** Where all passes of a scan live on the phone (app storage; reachable over USB under Android/data). */
        fun folder(context: Context, scanId: String): File = File(context.getExternalFilesDir(null) ?: context.filesDir, "scans/$scanId")

        /** 960 × 720 from a 4:3 camera image (no crop, so K only scales); never upscaled; even sides for the encoder. */
        fun videoSize(sensor: Size): Size {
            val s = minOf(1f, 960f / sensor.width)
            fun even(v: Float) = (v / 2).roundToInt() * 2
            return Size(even(sensor.width * s), even(sensor.height * s))
        }

        private fun deviceModel(): String = "${Build.MANUFACTURER} ${Build.MODEL} Android ${Build.VERSION.RELEASE}"

        private fun supportsHighProfile(): Boolean = runCatching {
            MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { it.isEncoder && MediaFormat.MIMETYPE_VIDEO_AVC in it.supportedTypes }
                .any { info -> info.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC).profileLevels.any { it.profile == MediaCodecInfo.CodecProfileLevel.AVCProfileHigh } }
        }.getOrDefault(false)
    }
}
