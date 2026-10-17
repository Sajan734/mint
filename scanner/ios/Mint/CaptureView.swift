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
                            tint: session.tint, tintAxis: session.tintAxis, percent: session.percent,
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

            if session.phase == .review {
                VStack {
                    Spacer()
                    ReviewCard(session: session)
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
                    Text(String(format: "REC  %d:%02d", Int(t) / 60, Int(t) % 60))
                        .font(.system(.subheadline, design: .monospaced).weight(.semibold))
                    if session.nextPass > 1 {
                        Text("PASS \(session.nextPass)").font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                            .foregroundStyle(Color.brandMint)
                    }
                }
                .chip()
            }
        case .ready, .countdown:
            HStack(spacing: 7) {
                Circle().fill(session.outline.isEmpty ? Color.white.opacity(0.5) : Color.brandMint).frame(width: 8, height: 8)
                Text(session.outline.isEmpty ? "LOOKING" : "ITEM FOUND")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                if session.nextPass > 1 {
                    Text("· PASS \(session.nextPass)").font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                        .foregroundStyle(Color.brandMint)
                }
            }
            .chip()
        case .saving, .review:
            Label(session.passes.count > 1 ? "\(session.passes.count) PASSES" : "CAPTURED", systemImage: "checkmark.seal.fill")
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
        case .ready:
            return session.passes.isEmpty
                ? ("Put it on a sheet of paper. Tap Scan.", "viewfinder")
                : ("Pass \(session.nextPass) · flip it or try another angle", "arrow.uturn.down")
        case .countdown: return ("Get ready to turn the paper", "arrow.triangle.2.circlepath")
        case .recording:
            let t = session.recordStart.map { now.timeIntervalSince($0) } ?? 0
            let left = Int((CaptureSession.maxPassSeconds - t).rounded(.up))
            if left <= 8 { return ("Wrapping up in \(left) s", "timer") }
            if session.percent >= 100 { return ("Lap covered · touch up, then tap to finish", "checkmark.seal") }
            if !session.paperSeen { return ("Keep the sheet in view", "viewfinder") }
            return ("Turn the paper · tap the ring when done", "arrow.triangle.2.circlepath")
        case .saving: return ("Saving pass \(session.nextPass)…", "seal")
        case .review: return ("", "")
        case .failed(let message): return (message, "exclamationmark.triangle")
        }
    }
}

// MARK: - The item: live outline with a holographic scan inside it

struct ScanOverlay: View {
    let outline: [CGPoint]
    let sparkles: [CGPoint]
    let recording: Bool
    /// How well each side has been seen, across the silhouette along `tintAxis` (empty: not scanning).
    let tint: [Double]
    let tintAxis: CGVector
    let percent: Int
    let time: Double

    var body: some View {
        Canvas { ctx, _ in
            guard outline.count > 8 else { return }
            let shape = Path.smoothClosed(outline)
            let box = shape.boundingRect
            let mint = Color.brandMint

            // Inside the silhouette: the coverage tint (mintier where that side has been seen), a fine
            // grid, and (recording) a bright band sweeping over it.
            ctx.drawLayer { layer in
                layer.clip(to: shape)
                if tint.count > 1 {
                    // The silhouette's extent along the axis the item's sides run across.
                    let d = outline.map { $0.x * tintAxis.dx + $0.y * tintAxis.dy }
                    let lo = d.min()!, hi = d.max()!
                    let c = CGPoint(x: box.midX, y: box.midY)
                    let off = (lo + hi) / 2 - (c.x * tintAxis.dx + c.y * tintAxis.dy)
                    let mid = CGPoint(x: c.x + tintAxis.dx * off, y: c.y + tintAxis.dy * off)
                    let half = max(1, (hi - lo) / 2)
                    let stops = tint.enumerated().map { i, l in
                        Gradient.Stop(color: Self.coverageColor(l), location: CGFloat(i) / CGFloat(tint.count - 1))
                    }
                    layer.fill(shape, with: .linearGradient(Gradient(stops: stops),
                        startPoint: CGPoint(x: mid.x - tintAxis.dx * half, y: mid.y - tintAxis.dy * half),
                        endPoint: CGPoint(x: mid.x + tintAxis.dx * half, y: mid.y + tintAxis.dy * half)))
                } else {
                    layer.fill(shape, with: .color(mint.opacity(recording ? 0.16 : 0.08)))
                }
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
            ctx.stroke(shape, with: .color(recording || !tint.isEmpty ? Self.coverageColor(0.3 + 0.7 * Double(percent) / 100, alpha: 1) : .white.opacity(0.92)),
                       style: StrokeStyle(lineWidth: 2.4, lineJoin: .round))

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

extension ScanOverlay {
    /// Not seen yet: a faint white veil. Fully seen: solid mint glass.
    static func coverageColor(_ level: Double, alpha: Double? = nil) -> Color {
        let l = max(0, min(1, level))
        let w = 1 - l
        return Color(.sRGB, red: w + l * 0x3D / 255, green: w + l * 0xDC / 255, blue: w + l * 0x97 / 255,
                     opacity: alpha ?? (0.07 + 0.58 * l))
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

// MARK: - The ring: one lap of the item's sides, with the percentage (a guide; tap to finish)

private struct CaptureRing: View {
    @ObservedObject var session: CaptureSession
    let now: Date

    var body: some View {
        ZStack {
            Canvas { ctx, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let mint = Color.brandMint
                let n = CaptureSession.segments
                let radius = 0.45 * min(size.width, size.height)
                let showing = session.isRecording || session.phase.isFinished
                // Each arc is a slice of the item's sides, lit as brightly as it's been seen head-on.
                for k in 0..<n {
                    let a0 = -90 + Double(k) * 360 / Double(n) + 2.2
                    let a1 = -90 + Double(k + 1) * 360 / Double(n) - 2.2
                    var arc = Path()
                    arc.addArc(center: c, radius: radius, startAngle: .degrees(a0), endAngle: .degrees(a1), clockwise: false)
                    ctx.stroke(arc, with: .color(.white.opacity(0.16)), style: StrokeStyle(lineWidth: 12, lineCap: .round))
                    let f = showing ? session.ring[k] : 0
                    guard f > 0.02 else { continue }
                    if f >= 0.98 {
                        ctx.drawLayer { l in
                            l.addFilter(.blur(radius: 5))
                            l.stroke(arc, with: .color(mint.opacity(0.8)), style: StrokeStyle(lineWidth: 14, lineCap: .round))
                        }
                    }
                    ctx.stroke(arc, with: .color(mint.opacity(0.2 + 0.8 * f)), style: StrokeStyle(lineWidth: 12, lineCap: .round))
                }
            }
            center
        }
        .scaleEffect(session.phase.isFinished ? 1.06 : 1)
        .animation(.spring(response: 0.4, dampingFraction: 0.5), value: session.phase.isFinished)
    }

    @ViewBuilder private var center: some View {
        switch session.phase {
        case .recording:
            VStack(spacing: 0) {
                Text("\(session.percent)")
                    .font(.system(size: 46, weight: .heavy, design: .rounded)).monospacedDigit()
                    + Text("%").font(.system(size: 22, weight: .bold, design: .rounded))
                Text(session.percent >= 100 ? "LAP DONE" : "OF A LAP")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.5)
                    .foregroundStyle(Color.brandMint)
                Text("TAP TO FINISH")
                    .font(.system(.caption2, design: .rounded).weight(.semibold)).tracking(1.2)
                    .foregroundStyle(.white.opacity(0.55))
                    .padding(.top, 3)
            }
            .foregroundStyle(.white)
            .contentTransition(.numericText(value: Double(session.percent)))
            .animation(.snappy(duration: 0.2), value: session.percent)
        case .saving, .review:
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 54, weight: .bold))
                .foregroundStyle(Color.brandMint)
                .shadow(color: .brandMint.opacity(0.8), radius: 16)
        default:
            ZStack {
                Circle().fill(.white).frame(width: 112, height: 112)
                VStack(spacing: 0) {
                    Text("Scan").font(.system(size: 24, weight: .heavy, design: .rounded))
                    if session.nextPass > 1 {
                        Text("PASS \(session.nextPass)").font(.system(.caption2, design: .rounded).weight(.bold)).tracking(1.2)
                    }
                }
                .foregroundStyle(Color.brandStageBg)
            }
            .shadow(color: .brandMint.opacity(0.45), radius: 18)
        }
    }
}

// MARK: - Review: the passes so far, another pass or send them all

private struct ReviewCard: View {
    @ObservedObject var session: CaptureSession
    @State private var zipURL: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.passes.count == 1 ? "Captured" : "\(session.passes.count) passes")
                        .font(.system(.title2, design: .rounded).weight(.heavy))
                    if let last = session.passes.last {
                        Text(String(format: "Pass %d · %.0f s · %d frames", last.pass, last.seconds, last.frames))
                            .font(.system(.subheadline, design: .rounded)).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                Spacer()
            }
            passStrip
            switch session.upload {
            case .idle: choices
            default: uploadRow
            }
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .task(id: session.upload) {
            guard session.upload == .notConfigured || isFailed else { return }
            let dir = VideoRecorder.folder(scanID: session.scanID), id = session.scanID
            zipURL = await Task.detached { try? ScanExport.zip(directory: dir, scanID: id) }.value
        }
    }

    private var isFailed: Bool {
        if case .failed = session.upload { return true }
        return false
    }

    /// One thumbnail per pass, numbered.
    private var passStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(session.passes, id: \.pass) { p in
                    ZStack(alignment: .bottomLeading) {
                        thumbnail(p.directory)
                        Text("\(p.pass)")
                            .font(.system(.caption, design: .rounded).weight(.heavy))
                            .foregroundStyle(Color.brandStageBg)
                            .frame(width: 20, height: 20)
                            .background(Color.brandMint, in: Circle())
                            .padding(4)
                    }
                }
            }
        }
    }

    @ViewBuilder private func thumbnail(_ dir: URL) -> some View {
        if let img = UIImage(contentsOfFile: dir.appendingPathComponent("thumb.jpg").path) {
            Image(uiImage: img).resizable().scaledToFill().frame(width: 58, height: 58)
                .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(Color.brandMint, lineWidth: 2))
        } else {
            RoundedRectangle(cornerRadius: 13).fill(Color.brandMint.opacity(0.25)).frame(width: 58, height: 58)
        }
    }

    private var choices: some View {
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                Button(action: session.scanAgain) {
                    Label("Scan again", systemImage: "arrow.triangle.2.circlepath").fontWeight(.semibold)
                        .frame(maxWidth: .infinity, minHeight: 48)
                }
                .buttonStyle(.bordered)
                Button(action: session.finish) {
                    Label(session.passes.count == 1 ? "Done · send" : "Done · send \(session.passes.count)", systemImage: "paperplane.fill")
                        .fontWeight(.semibold).frame(maxWidth: .infinity, minHeight: 48)
                }
                .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
            }
            Button(role: .destructive, action: session.discardLastPass) {
                Text("Discard pass \(session.passes.last?.pass ?? 1)").font(.footnote.weight(.semibold))
            }
        }
    }

    @ViewBuilder private var uploadRow: some View {
        switch session.upload {
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
            VStack(alignment: .leading, spacing: 12) {
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Sent to Mint").font(.system(.subheadline, design: .rounded).weight(.semibold))
                        Text(path).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                    }
                } icon: {
                    Image(systemName: "checkmark.icloud.fill").foregroundStyle(Color.brandMint)
                }
                newItemButton
            }
        case .failed(let message):
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(message, systemImage: "exclamationmark.icloud").font(.footnote).foregroundStyle(Color.brandAmber).lineLimit(3)
                    Spacer()
                    Button("Retry", action: session.retryUpload).font(.subheadline.weight(.semibold))
                }
                HStack(spacing: 12) { shareButton; newItemButton }
            }
        case .notConfigured:
            VStack(alignment: .leading, spacing: 12) {
                Label("Saved on this phone. Uploads aren't set up yet, so share it instead.", systemImage: "internaldrive")
                    .font(.footnote).foregroundStyle(.secondary)
                HStack(spacing: 12) { shareButton; newItemButton }
            }
        case .idle:
            EmptyView()
        }
    }

    @ViewBuilder private var shareButton: some View {
        if let zipURL {
            ShareLink(item: zipURL) {
                Label("Share", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity, minHeight: 46)
            }
            .buttonStyle(.bordered)
        }
    }

    private var newItemButton: some View {
        Button(action: session.newItem) {
            Text("New item").fontWeight(.semibold).frame(maxWidth: .infinity, minHeight: 46)
        }
        .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
    }
}

enum ScanExport {
    /// Zips a scan folder, every pass (NSFileCoordinator's built-in zipping), into Documents/exports/mint-{id}.zip.
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
