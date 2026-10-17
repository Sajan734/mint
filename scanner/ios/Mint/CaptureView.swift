import ARKit
import RealityKit
import SwiftUI

/// The camera is always live underneath; each phase puts its own screen over it.
struct CaptureView: View {
    @StateObject private var session = CaptureSession()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            // The preview shows the whole 4:3 sensor frame that is recorded, like the Camera app's photo mode.
            // Filling the tall screen instead crops the sides, which looks zoomed in and hides what is in the shot.
            CameraView(session: session)
                .aspectRatio(3.0 / 4.0, contentMode: .fit)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .ignoresSafeArea()

            if session.inScanner {
                ScannerHUD(session: session).transition(.opacity)
            }
            // The full-screen moments are light (paper and ink); the scanner HUD above stays dark over the camera.
            Group {
                switch session.phase {
                case .waiting:
                    WaitingScreen(session: session).transition(.opacity)
                case .sending(let p):
                    SendingScreen(progress: p, passes: session.passes.count).transition(.opacity)
                case .finished:
                    FinishedScreen(session: session).transition(.opacity.combined(with: .scale(scale: 1.04)))
                case .failed(let message):
                    FailedScreen(message: message, session: session).transition(.opacity)
                default:
                    EmptyView()
                }
            }
            .environment(\.colorScheme, .light)
        }
        .animation(.easeInOut(duration: 0.45), value: session.phase.screen)
        .background(Color.black)
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear { session.run() }
        // Coming back from the background goes background → inactive → active, so run again on any .active
        // (resume() is a no-op if the camera is already running). Waiting for background → active missed it,
        // and the preview stayed frozen on its last frame (e.g. after opening the app from the Camera app's QR).
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { session.pause() }
            if phase == .active { session.resume() }
        }
        .onOpenURL { session.open($0) }
    }
}

extension CaptureSession.Phase {
    /// Which screen the phase shows (sending progress doesn't change it).
    var screen: String {
        switch self {
        case .waiting: return "waiting"
        case .ready, .recording, .saving, .review: return "scanner"
        case .sending: return "sending"
        case .finished: return "finished"
        case .failed: return "failed"
        }
    }

    /// Saving or reviewing: the pass is over and its coverage stays on screen.
    var isFinished: Bool { self == .saving || self == .review }

    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }

    /// Read QR codes only while waiting for a product (or on the done / failed screens).
    var readsCodes: Bool { self == .waiting || self == .finished || isFailed }
}

private struct CameraView: UIViewRepresentable {
    let session: CaptureSession
    func makeUIView(context: Context) -> ARView { session.arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

// MARK: - The scanner: brackets on the item while it's being found, and the coverage ring round the scan button

struct ScannerHUD: View {
    @ObservedObject var session: CaptureSession
    @State private var confirmCancel = false

    var body: some View {
        ZStack {
            // Legibility only: the top and bottom edges darken a little; the camera stays wide open.
            LinearGradient(stops: [.init(color: .black.opacity(0.6), location: 0), .init(color: .clear, location: 0.2),
                                   .init(color: .clear, location: 0.66), .init(color: .black.opacity(0.75), location: 1)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
                .allowsHitTesting(false)

            GeometryReader { geo in
                TimelineView(.animation) { ctx in
                    Brackets(session: session, time: ctx.date,
                             offset: CGPoint(x: geo.safeAreaInsets.leading, y: geo.safeAreaInsets.top))
                }
                .ignoresSafeArea()
            }
            .allowsHitTesting(false)

            VStack(spacing: 10) {
                topBar
                jobChip
                Spacer()
                if session.phase == .review {
                    ReviewCard(session: session)
                        .environment(\.colorScheme, .light)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                } else {
                    Caption(session: session)
                    controls
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 10)
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: session.phase)
        .confirmationDialog("Discard this scan?", isPresented: $confirmCancel, titleVisibility: .visible) {
            Button("Discard \(session.passes.count) pass\(session.passes.count == 1 ? "" : "es")", role: .destructive) { session.cancelJob() }
        } message: {
            Text("Nothing will be sent.")
        }
    }

    // Top: the mark, and what the scanner sees (paper locked) or the recording clock.
    private var topBar: some View {
        HStack {
            MintMark(ink: .white)
            Spacer()
            switch session.phase {
            case .recording:
                TimelineView(.periodic(from: .now, by: 0.25)) { ctx in
                    let t = session.recordStart.map { ctx.date.timeIntervalSince($0) } ?? 0
                    HStack(spacing: 8) {
                        Circle().fill(Color.brandRed).frame(width: 9, height: 9).opacity(Int(t * 2) % 2 == 0 ? 1 : 0.35)
                        Text(String(format: "REC %d:%02d", Int(t) / 60, Int(t) % 60))
                            .font(.system(.subheadline, design: .monospaced).weight(.semibold))
                        if session.nextPass > 1 { passTag(session.nextPass) }
                    }
                    .chip()
                }
            case .ready:
                HStack(spacing: 7) {
                    Circle().fill(session.paperSeen ? Color.brandMint : Color.brandAmber).frame(width: 8, height: 8)
                        .shadow(color: session.paperSeen ? .brandMint : .clear, radius: 5)
                    Text(session.paperSeen ? "PAPER LOCKED" : "FINDING PAPER")
                        .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                    if session.nextPass > 1 { passTag(session.nextPass) }
                }
                .chip()
            default:
                Label(session.passes.count > 1 ? "\(session.passes.count) PASSES" : "PASS SAVED", systemImage: "checkmark.seal.fill")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.2)
                    .foregroundStyle(Color.brandMint)
                    .chip()
            }
        }
        .padding(.top, 6)
    }

    private func passTag(_ n: Int) -> some View {
        Text("PASS \(n)").font(.system(.caption, design: .rounded).weight(.heavy)).tracking(1.2).foregroundStyle(Color.brandMint)
    }

    // What this scan is for.
    @ViewBuilder private var jobChip: some View {
        if let job = session.job {
            HStack(spacing: 6) {
                Image(systemName: job.isVerify ? "checkmark.shield.fill" : (job.fromDashboard ? "laptopcomputer" : "bolt.fill"))
                Text(job.isVerify ? "VERIFY · MATCHING THE LISTING"
                     : job.fromDashboard ? (job.title.map { "NEW PRODUCT · \($0.uppercased())" } ?? "NEW PRODUCT") : "QUICK SCAN")
                    .lineLimit(1)
            }
            .font(.system(.caption2, design: .rounded).weight(.bold)).tracking(1.1)
            .foregroundStyle(job.isVerify ? Color.brandMint : .white.opacity(0.8))
        }
    }

    // Bottom: cancel, and the scan button inside the coverage ring.
    private var controls: some View {
        HStack {
            Button {
                if session.passes.isEmpty { session.cancelJob() } else { confirmCancel = true }
            } label: {
                Image(systemName: "xmark").font(.system(size: 17, weight: .bold))
                    .frame(width: 50, height: 50).background(.ultraThinMaterial, in: Circle())
            }
            .opacity(session.phase == .ready ? 1 : 0)
            .disabled(session.phase != .ready)
            .accessibilityLabel("Cancel this scan")
            Spacer()
            TimelineView(.animation) { ctx in
                CoverageRing(session: session, time: ctx.date)
            }
            .frame(width: 214, height: 214)
            .contentShape(Circle())
            .onTapGesture { session.primaryAction() }
            .accessibilityLabel(session.isRecording ? "Stop this pass" : "Start scanning")
            .accessibilityAddTraits(.isButton)
            Spacer()
            Color.clear.frame(width: 50, height: 50)
        }
        .foregroundStyle(.white)
    }
}

/// Corner brackets on the item (what the sheet of paper encloses): they show it's been found, and stay
/// until the lap is about half covered, then fade away for the rest of the pass.
struct Brackets: View {
    @ObservedObject var session: CaptureSession
    let time: Date
    let offset: CGPoint   // view (safe area) → canvas (full screen)

    static let hideAtPercent = 50

    var body: some View {
        let shown = session.phase == .ready || (session.isRecording && session.percent < Self.hideAtPercent)
        Canvas { ctx, _ in
            guard let box = session.itemBox?.offsetBy(dx: offset.x, dy: offset.y) else { return }
            let t = time.timeIntervalSinceReferenceDate
            let vis = session.itemVisible ? 1.0 : 0.3
            let r = box.insetBy(dx: -16, dy: -16)
            let len = min(30, r.width / 3.5, r.height / 3.5)
            var path = Path()
            for (c, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                                (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
                path.move(to: CGPoint(x: c.x + dx * len, y: c.y))
                path.addLine(to: c)
                path.addLine(to: CGPoint(x: c.x, y: c.y + dy * len))
            }
            let colour = session.isRecording ? Color.brandMint : .white
            let pulse = 0.75 + 0.25 * sin(t * (session.isRecording ? 4 : 2))
            ctx.drawLayer { l in
                l.addFilter(.blur(radius: 6))
                l.stroke(path, with: .color(colour.opacity(0.7 * pulse * vis)), style: StrokeStyle(lineWidth: 7, lineCap: .round, lineJoin: .round))
            }
            ctx.stroke(path, with: .color(colour.opacity(vis)), style: StrokeStyle(lineWidth: 3.5, lineCap: .round, lineJoin: .round))
            ctx.draw(Text(session.isRecording ? "SCANNING" : "ITEM").font(.system(size: 11, weight: .heavy, design: .rounded))
                        .foregroundColor(colour.opacity(vis)),
                     at: CGPoint(x: r.minX + 2, y: r.minY - 12), anchor: .leading)
        }
        .opacity(shown ? 1 : 0)
        .animation(.easeOut(duration: 0.6), value: shown)
    }
}

/// The scan button inside the coverage ring: 72 ticks, one per 5° of turn, filling clockwise from the top
/// as the paper turns clockwise (a tick lights mint once the side it stands for has been seen head-on).
/// While recording, a bright spot marks how far the paper has turned. At a full lap the ring stays full and
/// stops changing, whatever the touch-ups do. Tap: start / stop.
private struct CoverageRing: View {
    @ObservedObject var session: CaptureSession
    let time: Date

    var body: some View {
        ZStack {
            Canvas { ctx, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let r = min(size.width, size.height) / 2 - 16
                let t = time.timeIntervalSinceReferenceDate
                let recording = session.isRecording
                let live = recording || session.phase.isFinished
                let done = session.lapCompletedAt != nil
                let mint = Color.brandMint
                let n = CaptureSession.tickCount
                let spotDeg = (session.ringTurn * 180 / .pi).truncatingRemainder(dividingBy: 360)
                let sweep: Double? = session.lapCompletedAt.map { t - $0.timeIntervalSinceReferenceDate }.flatMap { $0 < 1.1 ? $0 / 1.1 * 360 : nil }

                var dim = Path(), lit = Path(), hot = Path()
                for j in 0..<n {
                    let deg = Double(j) * 360 / Double(n)
                    let a = (deg - 90) * .pi / 180
                    // Tick j: the side that faces the camera once the paper has turned j × 5° clockwise.
                    var level = live ? session.ticks[(n - j) % n] : 0
                    if session.phase == .ready { level = 0.22 * max(0, sin(t * 2.2 - Double(j) * 0.17)) }
                    var boost = 0.0
                    if recording && !done && session.paperSeen {
                        let behind = ((spotDeg - deg).truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360)
                        if behind < 30 { boost = 1 - behind / 30 } else if behind > 355 { boost = (behind - 355) / 5 }
                    }
                    if let sweep {
                        let d = abs((deg - sweep).truncatingRemainder(dividingBy: 360))
                        boost = max(boost, max(0, 1 - min(d, 360 - d) / 24))
                    }
                    let len = 8 + 6 * level + 6 * boost
                    let p0 = CGPoint(x: c.x + cos(a) * (r - len / 2), y: c.y + sin(a) * (r - len / 2))
                    let p1 = CGPoint(x: c.x + cos(a) * (r + len / 2), y: c.y + sin(a) * (r + len / 2))
                    var seg = Path()
                    seg.move(to: p0)
                    seg.addLine(to: p1)
                    if boost > 0.4 { hot.addPath(seg) } else if level > 0.85 { lit.addPath(seg) } else if level > 0.03 {
                        ctx.stroke(seg, with: .color(mint.opacity(0.3 + 0.6 * level)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    } else { dim.addPath(seg) }
                }
                ctx.stroke(dim, with: .color(.white.opacity(0.25)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
                ctx.drawLayer { l in
                    l.addFilter(.blur(radius: 5))
                    l.stroke(lit, with: .color(mint.opacity(0.85)), style: StrokeStyle(lineWidth: 5, lineCap: .round))
                    l.stroke(hot, with: .color(.white.opacity(0.8)), style: StrokeStyle(lineWidth: 5, lineCap: .round))
                }
                ctx.stroke(lit, with: .color(mint), style: StrokeStyle(lineWidth: 3.2, lineCap: .round))
                ctx.stroke(hot, with: .color(.white), style: StrokeStyle(lineWidth: 3.4, lineCap: .round))
            }
            centre
        }
        .scaleEffect(session.phase.isFinished ? 1.05 : 1)
        .animation(.spring(response: 0.4, dampingFraction: 0.55), value: session.phase.isFinished)
    }

    @ViewBuilder private var centre: some View {
        switch session.phase {
        case .recording:
            let done = session.percent >= 100
            VStack(spacing: 1) {
                (Text("\(session.percent)").font(.system(size: 48, weight: .heavy, design: .rounded)).monospacedDigit()
                    + Text("%").font(.system(size: 22, weight: .bold, design: .rounded)))
                    .foregroundStyle(done ? Color.brandMint : .white)
                    .shadow(color: done ? .brandMint.opacity(0.6) : .clear, radius: 12)
                    .contentTransition(.numericText(value: Double(session.percent)))
                    .animation(.snappy(duration: 0.25), value: session.percent)
                Text(done ? "FULL LAP" : "OF A LAP")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.5)
                    .foregroundStyle(Color.brandMint)
                HStack(spacing: 5) {
                    RoundedRectangle(cornerRadius: 2.5).fill(Color.brandRed).frame(width: 10, height: 10)
                    Text("TAP TO STOP").font(.system(.caption2, design: .rounded).weight(.bold)).tracking(1.1)
                }
                .foregroundStyle(.white.opacity(0.7))
                .padding(.top, 6)
            }
        case .saving, .review:
            ProgressView().tint(.white).scaleEffect(1.3)
        default:
            ZStack {
                Circle().fill(.white).frame(width: 128, height: 128)
                VStack(spacing: 0) {
                    Text("Scan").font(.system(size: 26, weight: .heavy, design: .rounded))
                    if session.nextPass > 1 {
                        Text("PASS \(session.nextPass)").font(.system(.caption2, design: .rounded).weight(.bold)).tracking(1.2)
                    }
                }
                .foregroundStyle(Color.brandStageBg)
            }
            .shadow(color: .brandMint.opacity(0.5), radius: 18)
        }
    }
}

private struct Caption: View {
    @ObservedObject var session: CaptureSession

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.25)) { ctx in
            let (text, symbol) = content(ctx.date)
            Label(text, systemImage: symbol)
                .font(.system(.headline, design: .rounded))
                .foregroundStyle(.white)
                .padding(.horizontal, 18).padding(.vertical, 11)
                .background(.ultraThinMaterial, in: Capsule())
                .id(text)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
        .animation(.easeOut(duration: 0.25), value: session.phase)
    }

    private func content(_ now: Date) -> (String, String) {
        switch session.phase {
        case .ready:
            if session.passes.isEmpty {
                if session.job?.isVerify == true && !session.itemVisible { return ("Put the item you're buying on the paper", "checkmark.shield") }
                return session.itemVisible ? ("Item found · tap to start", "viewfinder") : ("Put the item on a sheet of paper", "doc")
            }
            return ("Pass \(session.nextPass) · flip it or try another angle", "arrow.uturn.down")
        case .recording:
            let t = session.recordStart.map { now.timeIntervalSince($0) } ?? 0
            let left = Int((CaptureSession.maxPassSeconds - t).rounded(.up))
            if left <= 8 { return ("Wrapping up in \(left) s", "timer") }
            if session.lapCompletedAt != nil { return ("Full lap · touch up, then tap stop", "checkmark.seal") }
            if !session.paperSeen { return ("Keep the paper in view", "viewfinder") }
            return ("Turn the paper clockwise", "arrow.clockwise")
        case .saving: return ("Saving pass \(session.nextPass)…", "seal")
        default: return ("", "")
        }
    }
}

struct MintMark: View {
    var ink: Color = .brandInk  // white over the camera (scanner HUD), ink on the light screens
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(Color.brandMint).frame(width: 10, height: 10).shadow(color: .brandMint, radius: 6)
            Text("mint").font(.system(size: 28, weight: .heavy, design: .rounded)).foregroundStyle(ink)
        }
    }
}

extension View {
    func chip() -> some View {
        padding(.horizontal, 12).padding(.vertical, 8).background(.ultraThinMaterial, in: Capsule())
    }
}
