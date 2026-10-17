import Foundation

/// The phone's side of the hand-off with the seller's dashboard (`scanner/supabase/functions/scan-session`,
/// see scanner/DASHBOARD.md): while the app waits on its home screen it asks for the next "New product"
/// request; during a scan it reports progress so the dashboard can show it live. Reports never block
/// or fail a scan.
struct DashboardLink {
    struct Request: Decodable, Equatable {
        let scan_id: String
        let title: String?
        let seller: String?
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

    /// `mintscan://scan?scan_id=<uuid>` (the QR code on the dashboard's "check your phone" page): the
    /// scan it asks for, or nil if the link isn't one of ours.
    static func scanID(from link: URL) -> String? {
        guard link.scheme == "mintscan", link.host == "scan" else { return nil }
        let id = URLComponents(url: link, resolvingAgainstBaseURL: false)?.queryItems?
            .first(where: { $0.name == "scan_id" })?.value?.lowercased()
        guard let id, id.range(of: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", options: .regularExpression) != nil else { return nil }
        return id
    }
}
