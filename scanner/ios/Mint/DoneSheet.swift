import SwiftUI

/// After a scan: what was captured, and AirDrop/share the folder as a zip.
struct DoneSheet: View {
    let summary: ScanSummary
    let onNewScan: () -> Void

    @State private var zipURL: URL?
    @State private var zipError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(summary.coveragePct >= 90 ? Copy.complete : "Saved at \(summary.coveragePct)% coverage.",
                  systemImage: summary.coveragePct >= 90 ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                .font(.title3.weight(.semibold))
                .foregroundStyle(summary.coveragePct >= 90 ? Color.brandMint : Color.brandAmber)

            Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 6) {
                row("Time", String(format: "%.1f s", summary.seconds))
                row("Video", "\(summary.videoFrames) frames · 960×720")
                row("Keyframes", "\(summary.keyframes)")
                row("Size", String(format: "%.1f MB", summary.megabytes))
                row("Scan ID", String(summary.scanID.prefix(8)))
            }
            .font(.subheadline)

            if let zipURL {
                ShareLink(item: zipURL) {
                    Label("Send to teammate", systemImage: "square.and.arrow.up")
                        .font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
            } else if let zipError {
                Text(zipError).foregroundStyle(Color.brandAmber)
            } else {
                ProgressView("Packing…").frame(maxWidth: .infinity, minHeight: 50)
            }

            Button("New scan", action: onNewScan)
                .font(.headline).frame(maxWidth: .infinity, minHeight: 44)
        }
        .padding(24)
        .task { await pack() }
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k).foregroundStyle(.secondary)
            Text(v).monospacedDigit()
        }
    }

    private func pack() async {
        let dir = summary.directory, id = summary.scanID
        let result = await Task.detached { Result { try ScanExport.zip(directory: dir, scanID: id) } }.value
        switch result {
        case .success(let url): zipURL = url
        case .failure(let e): zipError = "Couldn't pack the scan: \(e.localizedDescription)"
        }
    }
}

enum ScanExport {
    /// Zips a scan folder (via NSFileCoordinator's built-in zipping) into Documents/exports/mint-{id}.zip.
    static func zip(directory: URL, scanID: String) throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let exports = docs.appendingPathComponent("exports", isDirectory: true)
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        let dest = exports.appendingPathComponent("mint-\(scanID.prefix(8)).zip")
        try? FileManager.default.removeItem(at: dest)

        var coordError: NSError?
        var copyError: Error?
        NSFileCoordinator().coordinate(readingItemAt: directory, options: .forUploading, error: &coordError) { tmpZip in
            do { try FileManager.default.copyItem(at: tmpZip, to: dest) } catch { copyError = error }
        }
        if let e = coordError ?? copyError { throw e }
        return dest
    }
}
