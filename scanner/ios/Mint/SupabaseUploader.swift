import Foundation

/// Sends a finished scan (all its passes) to Supabase Storage, bucket `scans`, under one `{scan_id}/`
/// folder, named the way the splat pipeline reads them (gsplat `fetch_inputs`):
///   pass 1   video.mp4  poses.jsonl  capture.json  thumb.jpg
///   pass 2   bottom.mp4 bottom.poses.jsonl bottom.capture.json   (usually the item flipped over)
///   pass n   pass{n}.mp4 pass{n}.poses.jsonl pass{n}.capture.json (kept; the pipeline uses the first two)
/// `video.mp4` goes last: its arrival starts the pipeline (Storage webhook → `on_upload`), so every
/// other pass must already be there.
/// The app holds no keys: it asks our Edge Function (`scanner/supabase/functions/scan-upload`) for
/// one-time signed upload URLs, then PUTs each file to its URL.
enum SupabaseUploader {
    /// Edge Function URL from Info.plist (`MintUploadURL`, set via `MINT_UPLOAD_URL` in project.yml).
    static var functionURL: URL? {
        guard let s = Bundle.main.object(forInfoDictionaryKey: "MintUploadURL") as? String,
              !s.isEmpty, !s.contains("$(") else { return nil }
        return URL(string: s)
    }

    /// One file to send: where it is on the phone and its name in Storage.
    struct Item: Equatable {
        let local: URL
        let key: String
        let type: String
    }

    static let types = ["mp4": "video/mp4", "jsonl": "application/x-ndjson", "json": "application/json", "jpg": "image/jpeg"]

    /// Storage names for one pass's files, in upload order (the video last).
    static func items(passDirectory dir: URL, pass: Int) -> [Item] {
        let prefix = pass == 1 ? "" : (pass == 2 ? "bottom." : "pass\(pass).")
        var out: [(String, String)] = [("poses.jsonl", prefix + "poses.jsonl"), ("capture.json", prefix + "capture.json")]
        if pass == 1 { out.append(("thumb.jpg", "thumb.jpg")) }
        out.append(("video.mp4", pass == 1 ? "video.mp4" : prefix + "mp4"))
        return out.compactMap { local, key in
            let url = dir.appendingPathComponent(local)
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
            return Item(local: url, key: key, type: types[url.pathExtension] ?? "application/octet-stream")
        }
    }

    /// Every file of a scan in upload order: later passes first, then pass 1, ending with video.mp4.
    static func plan(passes: [(directory: URL, pass: Int)]) -> [Item] {
        passes.sorted { $0.pass > $1.pass }.flatMap { items(passDirectory: $0.directory, pass: $0.pass) }
    }

    struct Signed: Decodable {
        let file: String
        let path: String
        let signed_url: String
    }

    /// Uploads the scan; `progress` (0…1, by bytes) is called on the main actor. Returns the scan's storage folder.
    @MainActor
    static func upload(scanID: String, passes: [(directory: URL, pass: Int)], progress: @escaping @MainActor (Double) -> Void) async throws -> String {
        guard let functionURL else { throw UploadError("Uploads aren't set up yet (MINT_UPLOAD_URL).") }
        let plan = plan(passes: passes)
        guard plan.contains(where: { $0.key == "video.mp4" }) else { throw UploadError("The first pass's video is missing.") }

        var request = URLRequest(url: functionURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["scan_id": scanID, "files": plan.map(\.key)])
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw UploadError("Couldn't get upload links: \(String(decoding: data, as: UTF8.self).prefix(200))")
        }
        let signed = try JSONDecoder().decode([String: [Signed]].self, from: data)["uploads"] ?? []

        let sizes = plan.map { Int64((try? $0.local.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
        let total = max(1, sizes.reduce(0, +))
        var done: Int64 = 0
        var folder = ""
        for (item, size) in zip(plan, sizes) {
            guard let s = signed.first(where: { $0.file == item.key }), let url = URL(string: s.signed_url) else {
                throw UploadError("No upload link for \(item.key)")
            }
            var put = URLRequest(url: url)
            put.httpMethod = "PUT"
            put.setValue(item.type, forHTTPHeaderField: "Content-Type")
            put.setValue("true", forHTTPHeaderField: "x-upsert")
            let before = done
            let watcher = ProgressWatcher { sent in
                Task { @MainActor in progress(Double(before + sent) / Double(total)) }
            }
            let (body, resp) = try await URLSession.shared.upload(for: put, fromFile: item.local, delegate: watcher)
            guard let code = (resp as? HTTPURLResponse)?.statusCode, (200..<300).contains(code) else {
                throw UploadError("\(item.key) upload failed: \(String(decoding: body, as: UTF8.self).prefix(200))")
            }
            done += size
            progress(Double(done) / Double(total))
            if item.key == "video.mp4" { folder = String(s.path.dropLast("video.mp4".count)) }
        }
        return folder
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
