import ARKit
import RealityKit
import SwiftUI

struct CaptureView: View {
    @StateObject private var session = CaptureSession()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            CameraView(session: session).ignoresSafeArea()

            // Legibility: darken the top and bottom edges of the camera image.
            LinearGradient(stops: [.init(color: .black.opacity(0.55), location: 0), .init(color: .clear, location: 0.22),
                                   .init(color: .clear, location: 0.62), .init(color: .black.opacity(0.7), location: 1)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
                .allowsHitTesting(false)

            TimelineView(.animation) { ctx in
                ScanOverlay(outline: session.outline, sparkles: session.sparkles, recording: session.isRecording,
                            time: ctx.date.timeIntervalSinceReferenceDate)
            }
            .ignoresSafeArea()
            .allowsHitTesting(false)

            VStack(spacing: 18) {
                TopBar(session: session)
                Spacer()
                Caption(session: session)
                TimelineView(.animation) { ctx in
                    CaptureRing(session: session, now: ctx.date)
                }
                .frame(width: 210, height: 210)
                .contentShape(Circle())
                .onTapGesture { session.primaryAction() }
                .accessibilityLabel(session.isRecording ? "Finish scan" : "Start scan")
                .accessibilityAddTraits(.isButton)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)

            if case .countdown(let n) = session.phase {
                Text("\(n)")
                    .font(.system(size: 150, weight: .heavy, design: .rounded))
                    .foregroundStyle(Color.brandMint)
                    .shadow(color: .brandMint.opacity(0.8), radius: 30)
                    .id(n)
                    .transition(.asymmetric(insertion: .scale(scale: 1.6).combined(with: .opacity), removal: .scale(scale: 0.6).combined(with: .opacity)))
                    .allowsHitTesting(false)
            }

            if case .done(let summary) = session.phase {
                VStack {
                    Spacer()
                    DoneCard(summary: summary, upload: session.upload, retry: session.retryUpload, newScan: session.newScan)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: session.phase)
        .background(Color.black)
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear { session.run() }
        .onChange(of: scenePhase) { old, phase in
            if phase == .background { session.pause() }
            if phase == .active && old == .background { session.run() }
        }
    }
}

// MARK: - Camera

private struct CameraView: UIViewRepresentable {
    let session: CaptureSession
    func makeUIView(context: Context) -> ARView { session.arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

// MARK: - Top bar

private struct TopBar: View {
    @ObservedObject var session: CaptureSession

    var body: some View {
        HStack(alignment: .center) {
            HStack(spacing: 6) {
                Circle().fill(Color.brandMint).frame(width: 10, height: 10).shadow(color: .brandMint, radius: 6)
                Text("mint").font(.system(size: 28, weight: .heavy, design: .rounded)).foregroundStyle(.white)
            }
            Spacer()
            status
        }
        .padding(.top, 6)
    }

    @ViewBuilder private var status: some View {
        switch session.phase {
        case .recording:
            TimelineView(.periodic(from: .now, by: 0.1)) { ctx in
                let t = session.recordStart.map { ctx.date.timeIntervalSince($0) } ?? 0
                HStack(spacing: 8) {
                    Circle().fill(Color.red).frame(width: 9, height: 9)
                        .opacity(Int(t * 2) % 2 == 0 ? 1 : 0.35)
                    Text(String(format: "REC  0:%02d", min(Int(CaptureSession.duration), Int(t))))
                        .font(.system(.subheadline, design: .monospaced).weight(.semibold))
                }
                .chip()
            }
        case .ready, .countdown:
            HStack(spacing: 7) {
                Circle().fill(session.outline.isEmpty ? Color.white.opacity(0.5) : Color.brandMint).frame(width: 8, height: 8)
                Text(session.outline.isEmpty ? "LOOKING" : "ITEM FOUND")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
            }
            .chip()
        case .saving, .done:
            Label("CAPTURED", systemImage: "checkmark.seal.fill")
                .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                .foregroundStyle(Color.brandMint)
                .chip()
        case .failed:
            EmptyView()
        }
    }
}

private extension View {
    func chip() -> some View {
        padding(.horizontal, 12).padding(.vertical, 8).background(.ultraThinMaterial, in: Capsule())
    }
}

// MARK: - Caption

private struct Caption: View {
    @ObservedObject var session: CaptureSession

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.25)) { ctx in
            let (text, symbol) = content(ctx.date)
            if !text.isEmpty {
                Label(text, systemImage: symbol)
                    .font(.system(.headline, design: .rounded))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 18).padding(.vertical, 12)
                    .background(.ultraThinMaterial, in: Capsule())
                    .id(text)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
        }
        .animation(.easeOut(duration: 0.25), value: session.phase)
    }

    private func content(_ now: Date) -> (String, String) {
        switch session.phase {
        case .ready: return ("Put it on a sheet of paper. Tap Scan.", "viewfinder")
        case .countdown: return ("Get ready to turn the paper", "arrow.triangle.2.circlepath")
        case .recording:
            let t = session.recordStart.map { now.timeIntervalSince($0) } ?? 0
            return t < CaptureSession.duration / 2
                ? ("Lap 1 · turn the paper slowly", "arrow.triangle.2.circlepath")
                : ("Lap 2 · raise the phone, keep turning", "arrow.up.circle")
        case .saving: return ("Sealing the capture…", "seal")
        case .done: return ("", "")
        case .failed(let message): return (message, "exclamationmark.triangle")
        }
    }
}

// MARK: - The item: live outline with a holographic scan inside it

struct ScanOverlay: View {
    let outline: [CGPoint]
    let sparkles: [CGPoint]
    let recording: Bool
    let time: Double

    var body: some View {
        Canvas { ctx, _ in
            guard outline.count > 8 else { return }
            let shape = Path.smoothClosed(outline)
            let box = shape.boundingRect
            let mint = Color.brandMint

            // Inside the silhouette: a faint fill, a fine grid, and (recording) a bright band sweeping over it.
            ctx.drawLayer { layer in
                layer.clip(to: shape)
                layer.fill(shape, with: .color(mint.opacity(recording ? 0.16 : 0.08)))
                var grid = Path()
                let step: CGFloat = 11
                var x = box.minX - box.height
                while x < box.maxX {
                    grid.move(to: CGPoint(x: x, y: box.maxY)); grid.addLine(to: CGPoint(x: x + box.height, y: box.minY))
                    x += step
                }
                layer.stroke(grid, with: .color(.white.opacity(recording ? 0.13 : 0.06)), lineWidth: 0.6)
                if recording {
                    let period = 1.6
                    let f = CGFloat(time.truncatingRemainder(dividingBy: period) / period)
                    let y = box.minY - 50 + (box.height + 100) * f
                    let band = CGRect(x: box.minX - 10, y: y - 34, width: box.width + 20, height: 68)
                    layer.fill(Path(band), with: .linearGradient(
                        Gradient(colors: [mint.opacity(0), mint.opacity(0.55), .white.opacity(0.7), mint.opacity(0.55), mint.opacity(0)]),
                        startPoint: CGPoint(x: band.midX, y: band.minY), endPoint: CGPoint(x: band.midX, y: band.maxY)))
                }
            }

            // Outline with a breathing glow.
            let pulse = 0.7 + 0.3 * sin(time * (recording ? 5 : 2.5))
            ctx.drawLayer { layer in
                layer.addFilter(.blur(radius: recording ? 10 : 7))
                layer.stroke(shape, with: .color(mint.opacity(0.85 * pulse)), lineWidth: recording ? 9 : 6)
            }
            ctx.stroke(shape, with: .color(recording ? mint : .white.opacity(0.92)), style: StrokeStyle(lineWidth: 2.4, lineJoin: .round))

            // Corner brackets.
            let r = box.insetBy(dx: -18, dy: -18)
            let len = min(30, r.width / 4, r.height / 4)
            var brackets = Path()
            for (c, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                                (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
                brackets.move(to: CGPoint(x: c.x + dx * len, y: c.y)); brackets.addLine(to: c); brackets.addLine(to: CGPoint(x: c.x, y: c.y + dy * len))
            }
            ctx.stroke(brackets, with: .color(recording ? mint : .white), style: StrokeStyle(lineWidth: 3.5, lineCap: .round, lineJoin: .round))

            // ARKit's measured points twinkle on the item.
            for (i, p) in sparkles.enumerated() {
                let tw = 0.5 + 0.5 * sin(time * 7 + Double(i) * 1.9)
                let s = 1.2 + 1.6 * tw
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - s, y: p.y - s, width: 2 * s, height: 2 * s)),
                         with: .color((i % 3 == 0 ? Color.white : mint).opacity(0.35 + 0.65 * tw)))
            }
        }
    }
}

extension Path {
    /// A closed Catmull-Rom curve through the points.
    static func smoothClosed(_ p: [CGPoint]) -> Path {
        var path = Path()
        let n = p.count
        guard n > 2 else { return path }
        path.move(to: p[0])
        for i in 0..<n {
            let p0 = p[(i - 1 + n) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n]
            let c1 = CGPoint(x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6)
            let c2 = CGPoint(x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6)
            path.addCurve(to: p2, control1: c1, control2: c2)
        }
        path.closeSubpath()
        return path
    }
}

// MARK: - The ring: two laps, segment by segment, with the percentage

private struct CaptureRing: View {
    @ObservedObject var session: CaptureSession
    let now: Date

    private var progress: Double {
        switch session.phase {
        case .recording: return Double(session.shownPercent) / 100
        case .saving, .done: return 1
        default: return 0
        }
    }

    var body: some View {
        let p = progress
        ZStack {
            Canvas { ctx, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let mint = Color.brandMint
                let n = CaptureSession.segments
                for lap in 0..<2 {
                    let radius = (lap == 0 ? 0.47 : 0.38) * min(size.width, size.height)
                    let lapP = max(0, min(1, p * 2 - Double(lap)))   // this ring's own 0…1
                    for k in 0..<n {
                        let a0 = -90 + Double(k) * 360 / Double(n) + 2.2
                        let a1 = -90 + Double(k + 1) * 360 / Double(n) - 2.2
                        let fill = max(0, min(1, lapP * Double(n) - Double(k)))   // 0…1 of this segment
                        var base = Path()
                        base.addArc(center: c, radius: radius, startAngle: .degrees(a0), endAngle: .degrees(a1), clockwise: false)
                        ctx.stroke(base, with: .color(.white.opacity(0.16)), style: StrokeStyle(lineWidth: 11, lineCap: .round))
                        if fill > 0 {
                            var lit = Path()
                            lit.addArc(center: c, radius: radius, startAngle: .degrees(a0), endAngle: .degrees(a0 + (a1 - a0) * fill), clockwise: false)
                            ctx.drawLayer { l in
                                l.addFilter(.blur(radius: 5))
                                l.stroke(lit, with: .color(mint.opacity(0.8)), style: StrokeStyle(lineWidth: 13, lineCap: .round))
                            }
                            ctx.stroke(lit, with: .color(mint), style: StrokeStyle(lineWidth: 11, lineCap: .round))
                        }
                    }
                }
            }
            center(p)
        }
        .scaleEffect(session.phase.isDone ? 1.06 : 1)
        .animation(.spring(response: 0.4, dampingFraction: 0.5), value: session.phase.isDone)
    }

    @ViewBuilder private func center(_ p: Double) -> some View {
        switch session.phase {
        case .recording:
            VStack(spacing: 0) {
                Text("\(Int(p * 100))")
                    .font(.system(size: 46, weight: .heavy, design: .rounded)).monospacedDigit()
                    + Text("%").font(.system(size: 22, weight: .bold, design: .rounded))
                Text(p < 0.5 ? "LAP 1" : "LAP 2")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.5)
                    .foregroundStyle(Color.brandMint)
            }
            .foregroundStyle(.white)
        case .saving, .done:
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 54, weight: .bold))
                .foregroundStyle(Color.brandMint)
                .shadow(color: .brandMint.opacity(0.8), radius: 16)
        default:
            ZStack {
                Circle().fill(.white).frame(width: 112, height: 112)
                Text("Scan").font(.system(size: 24, weight: .heavy, design: .rounded)).foregroundStyle(Color.brandStageBg)
            }
            .shadow(color: .brandMint.opacity(0.45), radius: 18)
        }
    }
}

private extension CaptureSession.Phase {
    var isDone: Bool {
        if case .done = self { return true }
        return self == .saving
    }
}

// MARK: - Done: what was captured, and the upload to Supabase

private struct DoneCard: View {
    let summary: VideoRecorder.Summary
    let upload: CaptureSession.Upload
    let retry: () -> Void
    let newScan: () -> Void
    @State private var zipURL: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                thumbnail
                VStack(alignment: .leading, spacing: 4) {
                    Text("Captured").font(.system(.title2, design: .rounded).weight(.heavy))
                    Text(String(format: "%.1f s · %d frames · %.0f MB", summary.seconds, summary.frames, summary.megabytes))
                        .font(.system(.subheadline, design: .rounded)).foregroundStyle(.secondary).monospacedDigit()
                }
                Spacer()
            }
            uploadRow
            HStack(spacing: 12) {
                if let zipURL {
                    ShareLink(item: zipURL) {
                        Label("Share", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity, minHeight: 46)
                    }
                    .buttonStyle(.bordered)
                }
                Button(action: newScan) {
                    Text("New scan").fontWeight(.semibold).frame(maxWidth: .infinity, minHeight: 46)
                }
                .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
            }
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .task {
            let dir = summary.directory, id = summary.scanID
            zipURL = await Task.detached { try? ScanExport.zip(directory: dir, scanID: id) }.value
        }
    }

    @ViewBuilder private var thumbnail: some View {
        if let img = UIImage(contentsOfFile: summary.directory.appendingPathComponent("thumb.jpg").path) {
            Image(uiImage: img).resizable().scaledToFill().frame(width: 64, height: 64)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.brandMint, lineWidth: 2))
        } else {
            RoundedRectangle(cornerRadius: 14).fill(Color.brandMint.opacity(0.25)).frame(width: 64, height: 64)
        }
    }

    @ViewBuilder private var uploadRow: some View {
        switch upload {
        case .sending(let p):
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Sending to Mint").font(.system(.subheadline, design: .rounded).weight(.semibold))
                    Spacer()
                    Text("\(Int(p * 100))%").font(.system(.subheadline, design: .rounded).weight(.bold)).monospacedDigit()
                }
                ProgressView(value: p).tint(.brandMint)
            }
        case .sent(let path):
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Sent to Mint").font(.system(.subheadline, design: .rounded).weight(.semibold))
                    Text(path).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                }
            } icon: {
                Image(systemName: "checkmark.icloud.fill").foregroundStyle(Color.brandMint)
            }
        case .failed(let message):
            HStack {
                Label(message, systemImage: "exclamationmark.icloud").font(.footnote).foregroundStyle(Color.brandAmber).lineLimit(2)
                Spacer()
                Button("Retry", action: retry).font(.subheadline.weight(.semibold))
            }
        case .notConfigured:
            Label("Saved on this phone. Uploads aren't set up yet, so share it instead.", systemImage: "internaldrive")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }
}

enum ScanExport {
    /// Zips a scan folder (NSFileCoordinator's built-in zipping) into Documents/exports/mint-{id}.zip.
    static func zip(directory: URL, scanID: String) throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let exports = docs.appendingPathComponent("exports", isDirectory: true)
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        let dest = exports.appendingPathComponent("mint-\(scanID.prefix(8)).zip")
        try? FileManager.default.removeItem(at: dest)
        var coordError: NSError?
        var copyError: Error?
        NSFileCoordinator().coordinate(readingItemAt: directory, options: .forUploading, error: &coordError) { tmp in
            do { try FileManager.default.copyItem(at: tmp, to: dest) } catch { copyError = error }
        }
        if let e = coordError ?? copyError { throw e }
        return dest
    }
}
