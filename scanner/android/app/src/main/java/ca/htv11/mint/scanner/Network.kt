package ca.htv11.mint.scanner

import ca.htv11.mint.coveragekit.UploadPlan
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * How the website reaches the scanner (scanner/DASHBOARD.md):
 * 1. Links (the main way): the website shows a QR code of `mint://scan?id=<uuid>` (sell an item) or
 *    `mint://verify?id=<uuid>&listing=<listing scan id>` (a buyer checking the item at an in-person deal).
 *    The phone's camera app, or Mint's own waiting screen, reads it and the scanner opens for that id
 *    (parsing: `ScanLinks` in coveragekit).
 * 2. Optional auto-pickup (`scanner/supabase/functions/scan-session`, once deployed): while the app waits it asks
 *    for the next request, and during a scan it reports progress so the page can show it live. Reports never block
 *    or fail a scan.
 */
object DashboardLink {
    class Request(val scanId: String, val title: String?, val seller: String?, val kind: String?, val listingScanId: String?)

    enum class Status(val wire: String) { SCANNING("scanning"), UPLOADING("uploading"), UPLOADED("uploaded"), CANCELLED("cancelled") }

    /** The Edge Function URL (`MINT_SESSION_URL` in app/build.gradle.kts); null when not set up. */
    val url: String? get() = BuildConfig.MINT_SESSION_URL.ifBlank { null }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** The dashboard's waiting request, if any. Throws when the dashboard can't be reached. */
    suspend fun next(): Request? = withContext(Dispatchers.IO) {
        val reply = JSONObject(post(JSONObject().put("action", "next")))
        val r = reply.optJSONObject("request") ?: return@withContext null
        Request(
            scanId = r.getString("scan_id"), title = r.optStringOrNull("title"), seller = r.optStringOrNull("seller"),
            kind = r.optStringOrNull("kind"), listingScanId = r.optStringOrNull("listing_scan_id"),
        )
    }

    /** Fire and forget: tells the dashboard where the scan is. */
    fun report(status: Status, scanId: String, passes: Int, progress: Double? = null) {
        val body = JSONObject().put("action", "update").put("scan_id", scanId).put("status", status.wire).put("passes", passes)
        if (progress != null) body.put("progress", progress.coerceIn(0.0, 1.0))
        scope.launch { runCatching { post(body) } }
    }

    private fun post(body: JSONObject): String {
        val u = url ?: throw IOException("The dashboard link isn't set up (MINT_SESSION_URL).")
        val c = URL(u).openConnection() as HttpURLConnection
        try {
            c.requestMethod = "POST"
            c.connectTimeout = 4000
            c.readTimeout = 4000
            c.useCaches = false
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = c.responseCode
            val text = (if (code in 200..299) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            if (code != 200) throw IOException("Dashboard: ${text.take(160)}")
            return text
        } finally {
            c.disconnect()
        }
    }
}

/**
 * Sends a finished scan (all its passes) to Supabase Storage, bucket `scans`, under one `{scan_id}/` folder, named
 * the way the splat pipeline reads them ([UploadPlan]). The app holds no keys: it asks our Edge Function
 * (`scanner/supabase/functions/scan-upload`) for one-time signed upload URLs, then PUTs each file to its URL.
 */
object SupabaseUploader {
    /** The Edge Function URL (`MINT_UPLOAD_URL` in app/build.gradle.kts); null when not set up. */
    val functionUrl: String? get() = BuildConfig.MINT_UPLOAD_URL.ifBlank { null }

    /** Uploads the scan; `progress` (0…1, by bytes) is called from the upload thread. Returns the scan's storage folder. */
    suspend fun upload(scanId: String, passes: List<UploadPlan.Pass>, verify: Boolean, progress: (Double) -> Unit): String = withContext(Dispatchers.IO) {
        val fn = functionUrl ?: throw IOException("Uploads aren't set up yet (MINT_UPLOAD_URL).")
        val plan = UploadPlan.plan(passes, verify)
        val firstVideo = UploadPlan.firstVideo(verify)
        if (plan.none { it.key == firstVideo }) throw IOException("The first pass's video is missing.")

        val request = JSONObject().put("scan_id", scanId).put("files", JSONArray(plan.map { it.key }))
        val (code, text) = send(fn, "POST", "application/json", request.toString().toByteArray())
        if (code != 200) throw IOException("Couldn't get upload links: ${text.take(200)}")
        val uploads = JSONObject(text).optJSONArray("uploads") ?: JSONArray()
        val signed = (0 until uploads.length()).map { uploads.getJSONObject(it) }

        val total = maxOf(1L, plan.sumOf { it.local.length() })
        var done = 0L
        var folder = ""
        for (item in plan) {
            val s = signed.firstOrNull { it.optString("file") == item.key } ?: throw IOException("No upload link for ${item.key}")
            val before = done
            val (putCode, body) = put(s.getString("signed_url"), item.type, item.local) { sent -> progress((before + sent).toDouble() / total) }
            if (putCode !in 200..299) throw IOException("${item.key} upload failed: ${body.take(200)}")
            done += item.local.length()
            progress(done.toDouble() / total)
            if (item.key == firstVideo) folder = s.getString("path").dropLast(firstVideo.length)
        }
        folder
    }

    private fun send(url: String, method: String, type: String, body: ByteArray): Pair<Int, String> {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = 15_000
            c.readTimeout = 30_000
            c.doOutput = true
            c.setRequestProperty("Content-Type", type)
            c.setFixedLengthStreamingMode(body.size)
            c.outputStream.use { it.write(body) }
            return c.responseCode to readBody(c)
        } finally {
            c.disconnect()
        }
    }

    private fun put(url: String, type: String, file: File, onSent: (Long) -> Unit): Pair<Int, String> {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = "PUT"
            c.connectTimeout = 15_000
            c.readTimeout = 60_000
            c.doOutput = true
            c.setRequestProperty("Content-Type", type)
            c.setRequestProperty("x-upsert", "true")
            c.setFixedLengthStreamingMode(file.length())
            c.outputStream.use { out ->
                file.inputStream().use { input ->
                    val buf = ByteArray(64 * 1024)
                    var sent = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        sent += n
                        onSent(sent)
                    }
                }
            }
            return c.responseCode to readBody(c)
        } finally {
            c.disconnect()
        }
    }

    private fun readBody(c: HttpURLConnection): String =
        runCatching { (if (c.responseCode in 200..299) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } }.getOrNull() ?: ""
}

private fun JSONObject.optStringOrNull(name: String): String? = if (isNull(name)) null else optString(name).ifEmpty { null }
