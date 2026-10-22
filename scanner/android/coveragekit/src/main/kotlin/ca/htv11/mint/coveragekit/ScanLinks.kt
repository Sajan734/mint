package ca.htv11.mint.coveragekit

import java.net.URI
import java.net.URLDecoder

/**
 * The website's links to the scanner (scanner/DASHBOARD.md): `mint://scan?id=<uuid>` (sell an item) and
 * `mint://verify?id=<uuid>&listing=<listing scan id>` (a buyer checking it at an in-person deal). Also
 * `scan_id=` / `listing_scan_id=` and the older `mintscan://` scheme. From a tapped link or a QR code's text.
 */
object ScanLinks {
    /** What a link asks for: a scan under [scanId]; with [listingId], a buyer's verify rescan of that listing. */
    data class Link(val scanId: String, val listingId: String?)

    private val uuid = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    private val plainId = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    private val uuidish = Regex("^[0-9A-Fa-f-]{36}$")

    /** null if it isn't one of ours. */
    fun parse(text: String): Link? {
        val uri = try { URI(text.trim()) } catch (_: Exception) { return null }
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "mint" && scheme != "mintscan") return null
        val query = parseQuery(uri.rawQuery)
        fun value(vararg names: String): String? = names.firstNotNullOfOrNull { n -> query.firstOrNull { it.first == n }?.second?.trim() }
        // The scan id names the Storage folder, so it must be a UUID (the website makes one per scan).
        fun scanId(): String? = value("id", "scan_id")?.lowercase()?.takeIf { uuid.matches(it) }
        // The listing is only written into rescan.capture.json: any plain id the website uses (a scan's UUID, or a
        // listing id such as a demo listing's), so a verify QR is never ignored for its format.
        fun listingId(): String? {
            val v = value("listing", "listing_scan_id")?.takeIf { plainId.matches(it) } ?: return null
            return if (uuidish.matches(v)) v.lowercase() else v
        }
        return when (uri.host?.lowercase()) {
            "scan" -> scanId()?.let { Link(it, null) }
            "verify" -> {
                val id = scanId() ?: return null
                val listing = listingId() ?: return null
                if (id == listing) null else Link(id, listing)
            }
            else -> null
        }
    }

    private fun parseQuery(raw: String?): List<Pair<String, String>> {
        if (raw.isNullOrEmpty()) return emptyList()
        return raw.split('&').mapNotNull { part ->
            if (part.isEmpty()) return@mapNotNull null
            val eq = part.indexOf('=')
            val name = decode(if (eq < 0) part else part.substring(0, eq))
            val value = if (eq < 0) "" else decode(part.substring(eq + 1))
            name to value
        }
    }

    private fun decode(s: String): String = try { URLDecoder.decode(s, "UTF-8") } catch (_: Exception) { s }
}
