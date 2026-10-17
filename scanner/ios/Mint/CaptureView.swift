import ARKit
import RealityKit
import SwiftUI

/// The camera is always live underneath; each phase puts its own screen over it.
struct CaptureView: View {
    @StateObject private var session = CaptureSession()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            CameraView(session: session).ignoresSafeArea()

            if session.inScanner {
                ScannerHUD(session: session).transition(.opacity)
            }
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
        .animation(.easeInOut(duration: 0.45), value: session.phase.screen)
        .background(Color.black)
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear { session.run() }
        .onChange(of: scenePhase) { old, phase in
            if phase == .background { session.pause() }
            if phase == .active && old == .background { session.run() }
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
}

private struct CameraView: UIViewRepresentable {
    let session: CaptureSession
    func makeUIView(context: Context) -> ARView { session.arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

// MARK: - The scanner: brackets on the item, and a wide ring on the table around it that turns with the paper

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
                    ScanCanvas(session: session, time: ctx.date,
                               offset: CGPoint(x: geo.safeAreaInsets.leading, y: geo.safeAreaInsets.top))
                }
                .ignoresSafeArea()
            }
            .allowsHitTesting(false)

            VStack(spacing: 10) {
                topBar
                jobChip
                coverageReadout.padding(.top, 4)
                Spacer()
                if session.phase == .review {
                    ReviewCard(session: session)
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
            MintMark()
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

    // The measured coverage of one lap.
    @ViewBuilder private var coverageReadout: some View {
        if session.phase != .ready {
            let done = session.percent >= 100
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                (Text("\(session.percent)").font(.system(size: 52, weight: .heavy, design: .rounded)).monospacedDigit()
                    + Text("%").font(.system(size: 24, weight: .bold, design: .rounded)))
                    .foregroundStyle(done ? Color.brandMint : .white)
                    .shadow(color: done ? .brandMint.opacity(0.6) : .black.opacity(0.4), radius: 12)
                    .contentTransition(.numericText(value: Double(session.percent)))
                    .animation(.snappy(duration: 0.25), value: session.percent)
                Label(done ? "FULL LAP" : "LAP COVERAGE", systemImage: done ? "checkmark.circle.fill" : "arrow.clockwise")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.4)
                    .foregroundStyle(done ? Color.brandMint : .white.opacity(0.75))
            }
            .transition(.opacity.combined(with: .scale(scale: 0.9)))
        }
    }

    // Bottom: cancel, and the shutter (start / stop).
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
            Shutter(phase: session.phase, action: session.primaryAction)
            Spacer()
            Color.clear.frame(width: 50, height: 50)
        }
        .foregroundStyle(.white)
    }
}

/// Draws, over the camera: corner brackets on the item (what the paper encloses), and a wide ring lying
/// flat on the table around it, seen in perspective (flatter the lower the camera). The ring is 72 ticks,
/// one per 5° of the item's sides, and it turns with the paper: a side's tick lights mint once that side
/// has been seen head-on, and the bright spot at the front of the ring is where the camera is looking now.
struct ScanCanvas: View {
    @ObservedObject var session: CaptureSession
    let time: Date
    let offset: CGPoint   // view (safe area) → canvas (full screen)

    var body: some View {
        Canvas { ctx, size in
            let t = time.timeIntervalSinceReferenceDate
            let recording = session.isRecording
            let live = recording || session.phase.isFinished
            let mint = Color.brandMint
            let box = session.itemBox?.offsetBy(dx: offset.x, dy: offset.y)

            // The ring: centred under the item (or mid-screen until it's found), nearly as wide as the screen.
            let a = size.width * 0.46
            let b = a * max(0.28, min(0.85, sin(session.elevation)))
            let centre = box.map { CGPoint(x: $0.midX, y: $0.maxY - min($0.height * 0.35, b * 0.6)) }
                ?? CGPoint(x: size.width / 2, y: size.height * 0.56)
            let n = CaptureSession.tickCount
            let sweep: Double? = session.lapCompletedAt.map { t - $0.timeIntervalSinceReferenceDate }.flatMap { $0 < 1.2 ? $0 / 1.2 : nil }

            // Back half first (behind the item), then the front half.
            for front in [false, true] {
                var dim = Path(), lit = Path(), hot = Path()
                var partial: [(Path, Double, Double)] = []
                for i in 0..<n {
                    // Where side i is now, round the item: 0 = facing the camera (front), clockwise from above.
                    let alpha = Double(i) / Double(n) * 2 * .pi + session.ringTurn
                    let depth = (cos(alpha) + 1) / 2          // 1 = front, 0 = back
                    guard (depth >= 0.5) == front else { continue }
                    var level = live ? session.ticks[i] : 0
                    if session.phase == .ready {
                        // Idle: a slow wave runs round the ring, waiting for the start.
                        level = 0.22 * max(0, sin(t * 2.0 + alpha * 3))
                    }
                    // The camera's view: brightest at the front of the ring.
                    let frontness = recording && session.paperSeen ? max(0, 1 - abs(atan2(sin(alpha), cos(alpha))) / 0.45) : 0
                    var boost = frontness
                    if let sweep {
                        let d = abs(atan2(sin(alpha - sweep * 2 * .pi), cos(alpha - sweep * 2 * .pi)))
                        boost = max(boost, max(0, 1 - d / 0.4))
                    }
                    let scale = 0.55 + 0.45 * depth           // nearer ticks are bigger
                    let len = (10 + 16 * level + 12 * boost) * scale
                    // On the ellipse: front = bottom, clockwise from above = to the left along the front.
                    let ux = -sin(alpha), uy = cos(alpha)
                    let p0 = CGPoint(x: centre.x + ux * a, y: centre.y + uy * b)
                    let p1 = CGPoint(x: centre.x + ux * (a + len), y: centre.y + uy * (b + len * b / a))
                    var seg = Path()
                    seg.move(to: p0)
                    seg.addLine(to: p1)
                    if boost > 0.4 { hot.addPath(seg) } else if level > 0.85 { lit.addPath(seg) } else if level > 0.03 {
                        partial.append((seg, level, scale))
                    } else { dim.addPath(seg) }
                }
                let fade = front ? 1.0 : 0.45
                ctx.stroke(dim, with: .color(.white.opacity(0.3 * fade)), style: StrokeStyle(lineWidth: front ? 3 : 2, lineCap: .round))
                for (seg, level, scale) in partial {
                    ctx.stroke(seg, with: .color(mint.opacity((0.3 + 0.6 * level) * fade)), style: StrokeStyle(lineWidth: 3.2 * scale, lineCap: .round))
                }
                ctx.drawLayer { l in
                    l.addFilter(.blur(radius: front ? 6 : 4))
                    l.stroke(lit, with: .color(mint.opacity(0.85 * fade)), style: StrokeStyle(lineWidth: 5, lineCap: .round))
                    l.stroke(hot, with: .color(.white.opacity(0.8 * fade)), style: StrokeStyle(lineWidth: 6, lineCap: .round))
                }
                ctx.stroke(lit, with: .color(mint.opacity(fade)), style: StrokeStyle(lineWidth: front ? 3.6 : 2.4, lineCap: .round))
                ctx.stroke(hot, with: .color(.white.opacity(fade)), style: StrokeStyle(lineWidth: 3.8, lineCap: .round))
            }

            // Brackets: the item, found. They fade when it's out of sight.
            if let box {
                let vis = session.itemVisible ? 1.0 : 0.25
                let r = box.insetBy(dx: -16, dy: -16)
                let len = min(30, r.width / 3.5, r.height / 3.5)
                var brackets = Path()
                for (c, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                                    (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
                    brackets.move(to: CGPoint(x: c.x + dx * len, y: c.y))
                    brackets.addLine(to: c)
                    brackets.addLine(to: CGPoint(x: c.x, y: c.y + dy * len))
                }
                let colour = recording || live ? mint : Color.white
                let pulse = 0.75 + 0.25 * sin(t * (recording ? 4 : 2))
                ctx.drawLayer { l in
                    l.addFilter(.blur(radius: 6))
                    l.stroke(brackets, with: .color(colour.opacity(0.7 * pulse * vis)), style: StrokeStyle(lineWidth: 7, lineCap: .round, lineJoin: .round))
                }
                ctx.stroke(brackets, with: .color(colour.opacity(vis)), style: StrokeStyle(lineWidth: 3.5, lineCap: .round, lineJoin: .round))
                // A small tag on the top-left bracket.
                let tag = Text(recording ? "SCANNING" : "ITEM")
                    .font(.system(size: 11, weight: .heavy, design: .rounded))
                    .foregroundColor(colour.opacity(vis))
                ctx.draw(tag, at: CGPoint(x: r.minX + 2, y: r.minY - 12), anchor: .leading)
            }
        }
    }
}

/// Start (white disc in a mint ring) → stop (red square) → saving (spinner).
private struct Shutter: View {
    let phase: CaptureSession.Phase
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().stroke(phase == .recording ? Color.white : Color.brandMint, lineWidth: 4).frame(width: 86, height: 86)
                switch phase {
                case .recording:
                    RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.brandRed).frame(width: 34, height: 34)
                case .saving:
                    ProgressView().tint(.white)
                default:
                    Circle().fill(.white).frame(width: 70, height: 70)
                }
            }
            .frame(width: 92, height: 92)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(phase == .saving)
        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: phase)
        .accessibilityLabel(phase == .recording ? "Stop this pass" : "Start scanning")
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
            if session.lapCompletedAt != nil { return ("Full lap · touch up, then stop", "checkmark.seal") }
            if !session.paperSeen { return ("Keep the paper in view", "viewfinder") }
            return ("Turn the paper clockwise", "arrow.clockwise")
        case .saving: return ("Saving pass \(session.nextPass)…", "seal")
        default: return ("", "")
        }
    }
}

struct MintMark: View {
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(Color.brandMint).frame(width: 10, height: 10).shadow(color: .brandMint, radius: 6)
            Text("mint").font(.system(size: 28, weight: .heavy, design: .rounded)).foregroundStyle(.white)
        }
    }
}

extension View {
    func chip() -> some View {
        padding(.horizontal, 12).padding(.vertical, 8).background(.ultraThinMaterial, in: Capsule())
    }
}
