package ca.htv11.mint.coveragekit

/**
 * One line of poses.jsonl: one per frame of video.mp4, in order (line n = encoded frame n).
 * Same fields as the iOS app's `PoseRecord` (scanner/HANDOFF.md).
 */
data class PoseRecord(
    val frame: Int,
    val tMs: Int,
    /** Raw AR camera pose (camera-to-world, camera axes +x right, +y up, looking along −z), row-major. */
    val poseWorld: List<List<Double>>,
    /** Camera-to-item. The item doesn't move relative to the AR world in this app, so it equals [poseWorld]. */
    val pose: List<List<Double>>?,
    /** K for the video's pixels. */
    val intrinsics: List<List<Double>>,
    val tracking: String,       // "normal" | "limited" | "not_available"
    val state: String,          // "recording"
    val sharpness: Double,
    val segment: String? = null,
    val counted: Boolean = false,
    val itemCentre: List<Double>? = null,
) {
    fun toJson(): Map<String, Any?> = mapOf(
        "frame" to frame, "t_ms" to tMs, "pose_world" to poseWorld, "pose" to pose, "intrinsics" to intrinsics,
        "tracking" to tracking, "state" to state, "sharpness" to sharpness, "segment" to segment,
        "counted" to counted, "item_centre" to itemCentre,
    )
}

/** capture.json: everything about the session that isn't per-frame (the iOS app's `CaptureInfo`). */
data class CaptureInfo(
    val scanId: String,
    val device: String,
    val os: String,
    val createdAt: String,
    val durationMs: Int,
    val video: String,              // "video.mp4"
    val videoWidth: Int,
    val videoHeight: Int,
    val videoFrames: Int,
    val sensorWidth: Int,
    val sensorHeight: Int,
    val orientation: String,        // "sensor_landscape": frames are NOT rotated to portrait
    val exposureLocked: Boolean,
    val mode: String? = null,       // "turntable"
    val coveragePct: Int? = null,
    /** Which recording of the item this is (1 = the main lap; 2 = usually the item flipped over; …). */
    val pass: Int? = null,
    /** "listing" (a seller's scan) or "handover" (a buyer's verify rescan at an in-person deal). */
    val kind: String? = null,
    /** Handover: the scan_id of the listing this rescan is checked against. */
    val listingScanId: String? = null,
    val platform: String? = null,   // "android"
) {
    fun toJson(): Map<String, Any?> = mapOf(
        "v" to 1, "scan_id" to scanId, "device" to device, "os" to os, "created_at" to createdAt,
        "duration_ms" to durationMs, "video" to video, "video_width" to videoWidth, "video_height" to videoHeight,
        "video_frames" to videoFrames, "sensor_width" to sensorWidth, "sensor_height" to sensorHeight,
        "orientation" to orientation, "exposure_locked" to exposureLocked, "mode" to mode,
        "coverage_pct" to coveragePct, "pass" to pass, "kind" to kind, "listing_scan_id" to listingScanId,
        "platform" to platform,
    )
}

/**
 * Stable JSON, like the iOS app's `CaptureJSON`: sorted keys, null fields left out, slashes not escaped.
 * One line for JSONL; `pretty` for capture.json. Values: null, Boolean, Number, String, List, Map<String, *>.
 */
object CaptureJson {
    fun encode(value: Any?, pretty: Boolean = false): String = StringBuilder().also { write(it, value, pretty, 0) }.toString()

    private fun write(out: StringBuilder, value: Any?, pretty: Boolean, depth: Int) {
        when (value) {
            null -> out.append("null")
            is Boolean -> out.append(value)
            is Int, is Long, is Short, is Byte -> out.append(value)
            is Double -> number(out, value)
            is Float -> number(out, value.toDouble())
            is String -> string(out, value)
            is Map<*, *> -> {
                val entries = value.entries.filter { it.value != null }.sortedBy { it.key as String }
                if (entries.isEmpty()) { out.append("{}"); return }
                out.append('{')
                entries.forEachIndexed { i, e ->
                    if (i > 0) out.append(',')
                    if (pretty) newline(out, depth + 1)
                    string(out, e.key as String)
                    out.append(if (pretty) " : " else ":")
                    write(out, e.value, pretty, depth + 1)
                }
                if (pretty) newline(out, depth)
                out.append('}')
            }
            is List<*> -> {
                if (value.isEmpty()) { out.append("[]"); return }
                out.append('[')
                value.forEachIndexed { i, v ->
                    if (i > 0) out.append(',')
                    if (pretty) newline(out, depth + 1)
                    write(out, v, pretty, depth + 1)
                }
                if (pretty) newline(out, depth)
                out.append(']')
            }
            else -> throw IllegalArgumentException("Can't encode ${value::class.simpleName}")
        }
    }

    private fun newline(out: StringBuilder, depth: Int) {
        out.append('\n')
        repeat(depth) { out.append("  ") }
    }

    /** Whole numbers without a fraction (as Swift's JSONEncoder writes them); never NaN/∞ (not JSON). */
    private fun number(out: StringBuilder, d: Double) {
        when {
            d.isNaN() || d.isInfinite() -> out.append("null")
            d == Math.rint(d) && kotlin.math.abs(d) < 1e15 -> out.append(d.toLong())
            else -> out.append(d.toString())
        }
    }

    private fun string(out: StringBuilder, s: String) {
        out.append('"')
        for (c in s) {
            when (c) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                else -> if (c < ' ') out.append(String.format("\\u%04x", c.code)) else out.append(c)
            }
        }
        out.append('"')
    }
}
