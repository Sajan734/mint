package ca.htv11.mint.coveragekit

import java.io.File

/**
 * Storage names for a finished scan (all its passes) in the `scans` bucket, under one `{scan_id}/` folder, named
 * the way the splat pipeline reads them (gsplat `fetch_inputs`, scanner/HANDOFF.md):
 *   pass 1   video.mp4  poses.jsonl  capture.json  thumb.jpg
 *   pass 2   bottom.mp4 bottom.poses.jsonl bottom.capture.json   (usually the item flipped over)
 *   pass n   pass{n}.mp4 pass{n}.poses.jsonl pass{n}.capture.json (kept; the pipeline uses the first two)
 * `video.mp4` goes last: its arrival starts the pipeline (Storage webhook → `on_upload`), so every other pass
 * must already be there. A buyer's verify rescan (handover) is named `rescan.mp4` … `rescan{n}.mp4` instead
 * (+ thumb.jpg), so the listing pipeline never turns it into a new listing; `rescan.mp4` goes last.
 */
object UploadPlan {
    /** One file to send: where it is on the phone and its name in Storage. */
    data class Item(val local: File, val key: String, val type: String)

    data class Pass(val directory: File, val pass: Int)

    val types = mapOf("mp4" to "video/mp4", "jsonl" to "application/x-ndjson", "json" to "application/json", "jpg" to "image/jpeg")

    /** The video whose upload completes a scan. */
    fun firstVideo(verify: Boolean) = if (verify) "rescan.mp4" else "video.mp4"

    /** Storage names for one pass's files, in upload order (the video last). Missing files are skipped. */
    fun items(dir: File, pass: Int, verify: Boolean = false): List<Item> {
        val prefix = when {
            verify -> if (pass == 1) "rescan." else "rescan$pass."
            pass == 1 -> ""
            pass == 2 -> "bottom."
            else -> "pass$pass."
        }
        val out = mutableListOf("poses.jsonl" to prefix + "poses.jsonl", "capture.json" to prefix + "capture.json")
        if (pass == 1) out.add("thumb.jpg" to "thumb.jpg")
        out.add("video.mp4" to if (pass == 1 && !verify) "video.mp4" else prefix + "mp4")
        return out.mapNotNull { (local, key) ->
            val f = File(dir, local)
            if (!f.exists()) null else Item(f, key, types[f.extension] ?: "application/octet-stream")
        }
    }

    /** Every file of a scan in upload order: later passes first, then pass 1, ending with its video. */
    fun plan(passes: List<Pass>, verify: Boolean = false): List<Item> =
        passes.sortedByDescending { it.pass }.flatMap { items(it.directory, it.pass, verify) }
}
