import Foundation

/// How the website reaches the scanner (scanner/DASHBOARD.md):
/// 1. Links (the main way): the website shows a QR code of `mint://scan?id=<uuid>` (sell an item) or
///    `mint://verify?id=<uuid>&listing=<listing scan id>` (a buyer checking the item at an in-person deal).
///    The iPhone camera, or Mint's own waiting screen, reads it and the scanner opens for that id.
/// 2. Optional auto-pickup (`scanner/supabase/functions/scan-session`, once deployed): while the app
///    waits it asks for the next request, and during a scan it reports progress so the page can show it
///    live. Reports never block or fail a scan.
struct DashboardLink {
    struct Request: Decodable, Equatable {
        let scan_id: String
        let title: String?
        let seller: String?
        let kind: String?             // "listing" (default) or "verify"
        let listing_scan_id: String?  // verify: the listing to check against
    }

    /// What a link asks for: a scan under `scanID`; with `listingID`, a buyer's verify rescan of that listing.
    struct Link: Equatable {
        let scanID: String
        let listingID: String?
    }

    enum Status: String {
        case scanning, uploading, uploaded, cancelled
    }

    /// Edge Function URL from Info.plist (`MintSessionURL`, set via `MINT_SESSION_URL` in project.yml).
    static var url: URL? {
        guard let s = Bundle.main.object(forInfoDictionaryKey: "MintSessionURL") as? String,
              !s.isEmpty, !s.contains("$(") else { return nil }
        return URL(string: s)
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 4
        c.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: c)
    }()

    /// The dashboard's waiting request, if any. Throws when the dashboard can't be reached.
    static func next() async throws -> Request? {
        struct Reply: Decodable { let request: Request? }
        return try JSONDecoder().decode(Reply.self, from: try await post(["action": "next"])).request
    }

    /// Fire and forget: tells the dashboard where the scan is.
    static func report(_ status: Status, scanID: String, passes: Int, progress: Double? = nil) {
        var body: [String: Any] = ["action": "update", "scan_id": scanID, "status": status.rawValue, "passes": passes]
        if let progress { body["progress"] = max(0, min(1, progress)) }
        Task.detached { _ = try? await post(body) }
    }

    private static func post(_ body: [String: Any]) async throws -> Data {
        guard let url else { throw UploadError("The dashboard link isn't set up (MINT_SESSION_URL).") }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw UploadError("Dashboard: \(String(decoding: data, as: UTF8.self).prefix(160))")
        }
        return data
    }

    /// `mint://scan?id=<uuid>`, `mint://verify?id=<uuid>&listing=<uuid>` (also `scan_id=` and the older
    /// `mintscan://` scheme), from a tapped link or a QR code's text. nil if it isn't one of ours.
    static func parse(_ text: String) -> Link? {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "mint" || url.scheme == "mintscan" else { return nil }
        let q = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func uuid(_ names: String...) -> String? {
            let v = names.lazy.compactMap { n in q.first(where: { $0.name == n })?.value?.lowercased() }.first
            guard let v, v.range(of: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", options: .regularExpression) != nil else { return nil }
            return v
        }
        switch url.host {
        case "scan":
            return uuid("id", "scan_id").map { Link(scanID: $0, listingID: nil) }
        case "verify":
            guard let id = uuid("id", "scan_id"), let listing = uuid("listing", "listing_scan_id"), id != listing else { return nil }
            return Link(scanID: id, listingID: listing)
        default:
            return nil
        }
    }
}
