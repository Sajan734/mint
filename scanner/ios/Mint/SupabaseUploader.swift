import Foundation

/// Sends a finished scan to Supabase Storage (bucket `scans`, key `{scan_id}/{file}`).
/// The app holds no keys: it asks our Edge Function (`scanner/supabase/functions/scan-upload`) for
/// one-time signed upload URLs, then PUTs each file to its URL.
enum SupabaseUploader {
    /// Edge Function URL from Info.plist (`MintUploadURL`, set via `MINT_UPLOAD_URL` in project.yml).
    static var functionURL: URL? {
        guard let s = Bundle.main.object(forInfoDictionaryKey: "MintUploadURL") as? String,
              !s.isEmpty, !s.contains("$(") else { return nil }
        return URL(string: s)
    }

    static let files: [(name: String, type: String)] = [
        ("video.mp4", "video/mp4"),
        ("poses.jsonl", "application/x-ndjson"),
        ("capture.json", "application/json"),
        ("thumb.jpg", "image/jpeg"),
    ]

    struct Signed: Decodable {
        let file: String
        let path: String
        let signed_url: String
    }

    /// Uploads the scan; `progress` (0…1, by bytes) is called on the main actor. Returns the video's storage path.
    @MainActor
    static func upload(directory: URL, scanID: String, progress: @escaping @MainActor (Double) -> Void) async throws -> String {
        guard let functionURL else { throw UploadError("Uploads aren't set up yet (MINT_UPLOAD_URL).") }
        let present = files.filter { FileManager.default.fileExists(atPath: directory.appendingPathComponent($0.name).path) }

        var request = URLRequest(url: functionURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["scan_id": scanID, "files": present.map(\.name)])
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw UploadError("Couldn't get upload links: \(String(decoding: data, as: UTF8.self).prefix(200))")
        }
        let signed = try JSONDecoder().decode([String: [Signed]].self, from: data)["uploads"] ?? []

        let sizes = present.map { Int64((try? directory.appendingPathComponent($0.name).resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
        let total = max(1, sizes.reduce(0, +))
        var done: Int64 = 0
        var videoPath = ""
        for (file, size) in zip(present, sizes) {
            guard let s = signed.first(where: { $0.file == file.name }), let url = URL(string: s.signed_url) else {
                throw UploadError("No upload link for \(file.name)")
            }
            var put = URLRequest(url: url)
            put.httpMethod = "PUT"
            put.setValue(file.type, forHTTPHeaderField: "Content-Type")
            put.setValue("true", forHTTPHeaderField: "x-upsert")
            let before = done
            let watcher = ProgressWatcher { sent in
                Task { @MainActor in progress(Double(before + sent) / Double(total)) }
            }
            let (body, resp) = try await URLSession.shared.upload(for: put, fromFile: directory.appendingPathComponent(file.name), delegate: watcher)
            guard let code = (resp as? HTTPURLResponse)?.statusCode, (200..<300).contains(code) else {
                throw UploadError("\(file.name) upload failed: \(String(decoding: body, as: UTF8.self).prefix(200))")
            }
            done += size
            progress(Double(done) / Double(total))
            if file.name == "video.mp4" { videoPath = s.path }
        }
        return videoPath
    }
}

/// Per-task delegate reporting bytes sent.
private final class ProgressWatcher: NSObject, URLSessionTaskDelegate {
    let onSent: (Int64) -> Void
    init(onSent: @escaping (Int64) -> Void) { self.onSent = onSent }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        onSent(totalBytesSent)
    }
}

struct UploadError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
