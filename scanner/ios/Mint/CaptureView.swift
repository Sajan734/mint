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
}

private struct CameraView: UIViewRepresentable {
    let session: CaptureSession
    func makeUIView(context: Context) -> ARView { session.arView }
    func updateUIView(_ uiView: ARView, context: Context) {}
}

// MARK: - The scanner: a lens on the item, ringed by the item's sides lighting up as they're seen

struct ScannerHUD: View {
    @ObservedObject var session: CaptureSession
    @State private var confirmCancel = false

    var body: some View {
        GeometryReader { geo in
            let lens = Lens(size: geo.size)
            ZStack {
                TimelineView(.animation) { ctx in
                    // The ring's canvas fills the screen (to dim all of it), so shift the lens by the safe area.
                    LensRing(session: session, lens: lens.offset(by: CGPoint(x: geo.safeAreaInsets.leading, y: geo.safeAreaInsets.top)),
                             time: ctx.date)
                }
                .ignoresSafeArea()
                .allowsHitTesting(false)

                coverageReadout
                    .position(x: lens.centre.x, y: lens.centre.y + lens.radius + 98)

                VStack(spacing: 14) {
                    topBar
                    jobChip
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
        }
        .confirmationDialog("Discard this product?", isPresented: $confirmCancel, titleVisibility: .visible) {
            Button("Discard \(session.passes.count) pass\(session.passes.count == 1 ? "" : "es")", role: .destructive) { session.cancelJob() }
        } message: {
            Text("Nothing will be sent to your dashboard.")
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

    // Which product this is for.
    @ViewBuilder private var jobChip: some View {
        if let job = session.job {
            HStack(spacing: 6) {
                Image(systemName: job.fromDashboard ? "laptopcomputer" : "bolt.fill")
                Text(job.fromDashboard ? (job.title.map { "NEW PRODUCT · \($0.uppercased())" } ?? "NEW PRODUCT · FROM YOUR DASHBOARD") : "QUICK SCAN")
                    .lineLimit(1)
            }
            .font(.system(.caption2, design: .rounded).weight(.bold)).tracking(1.1)
            .foregroundStyle(.white.opacity(0.75))
        }
    }

    // The measured coverage of one lap, under the lens.
    @ViewBuilder private var coverageReadout: some View {
        if session.phase != .ready {
            let done = session.percent >= 100
            VStack(spacing: 2) {
                (Text("\(session.percent)").font(.system(size: 58, weight: .heavy, design: .rounded)).monospacedDigit()
                    + Text("%").font(.system(size: 26, weight: .bold, design: .rounded)))
                    .foregroundStyle(done ? Color.brandMint : .white)
                    .shadow(color: done ? .brandMint.opacity(0.6) : .clear, radius: 14)
                    .contentTransition(.numericText(value: Double(session.percent)))
                    .animation(.snappy(duration: 0.25), value: session.percent)
                Label(done ? "FULL LAP" : "LAP COVERAGE", systemImage: done ? "checkmark.circle.fill" : "rotate.right")
                    .font(.system(.caption, design: .rounded).weight(.bold)).tracking(1.6)
                    .foregroundStyle(done ? Color.brandMint : .white.opacity(0.7))
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
            .accessibilityLabel("Cancel this product")
            Spacer()
            Shutter(phase: session.phase, action: session.primaryAction)
            Spacer()
            Color.clear.frame(width: 50, height: 50)
        }
        .foregroundStyle(.white)
    }
}

/// Where the lens sits on screen.
struct Lens {
    let centre: CGPoint
    let radius: CGFloat
    init(size: CGSize) {
        centre = CGPoint(x: size.width / 2, y: size.height * 0.40)
        radius = min(size.width * 0.38, size.height * 0.24)
    }

    private init(centre: CGPoint, radius: CGFloat) {
        self.centre = centre
        self.radius = radius
    }

    func offset(by d: CGPoint) -> Lens { Lens(centre: CGPoint(x: centre.x + d.x, y: centre.y + d.y), radius: radius) }
}

/// The lens: the camera clear inside, darkened outside, ringed by 72 ticks (the item's sides, clockwise
/// from the top as seen from above). A tick lights mint as its side is seen head-on; a bright comet
/// follows the side facing the camera right now, so it turns with the paper.
struct LensRing: View {
    @ObservedObject var session: CaptureSession
    let lens: Lens
    let time: Date

    var body: some View {
        Canvas { ctx, size in
            let c = lens.centre, r = lens.radius
            let t = time.timeIntervalSinceReferenceDate
            let recording = session.isRecording
            let live = recording || session.phase.isFinished
            let mint = Color.brandMint

            // Everything outside the lens dims, so the eye goes to the item.
            var mask = Path(CGRect(origin: .zero, size: size))
            mask.addEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
            ctx.fill(mask, with: .color(.black.opacity(recording ? 0.62 : 0.5)), style: FillStyle(eoFill: true))
            var rim = Path()
            rim.addEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
            ctx.stroke(rim, with: .color(.white.opacity(0.22)), lineWidth: 1)

            let n = CaptureSession.tickCount
            let facingDeg = session.facingAngle * 180 / .pi
            // The lap-complete flourish: one bright sweep round the ring.
            let sweep: Double? = session.lapCompletedAt.map { t - $0.timeIntervalSinceReferenceDate }.flatMap { $0 < 1.1 ? $0 / 1.1 * 360 : nil }

            var lit = Path(), dim = Path(), hot = Path()
            for i in 0..<n {
                let deg = Double(i) * 360 / Double(n)
                let a = (deg - 90) * .pi / 180
                var level = live ? session.ticks[i] : 0
                var boost = 0.0
                if recording && session.paperSeen {
                    // Comet: brightest at the side facing the camera, trailing behind it (anticlockwise).
                    let behind = (facingDeg - deg).truncatingRemainder(dividingBy: 360)
                    let d = behind < 0 ? behind + 360 : behind
                    if d < 36 { boost = 1 - d / 36 } else if d > 354 { boost = (d - 354) / 6 }
                }
                if let sweep {
                    let d = abs((deg - sweep).truncatingRemainder(dividingBy: 360))
                    boost = max(boost, max(0, 1 - min(d, 360 - d) / 24))
                }
                if session.phase == .ready {
                    // Idle: a slow wave travels clockwise, waiting for the start.
                    level = 0.18 * max(0, sin(t * 2.2 - Double(i) * 0.17))
                }
                let len = 9 + 15 * level + 10 * boost
                let r0 = r + 12
                let p0 = CGPoint(x: c.x + cos(a) * r0, y: c.y + sin(a) * r0)
                let p1 = CGPoint(x: c.x + cos(a) * (r0 + len), y: c.y + sin(a) * (r0 + len))
                var seg = Path()
                seg.move(to: p0)
                seg.addLine(to: p1)
                if boost > 0.35 { hot.addPath(seg) } else if level > 0.85 { lit.addPath(seg) } else { dim.addPath(seg) }
                if level > 0.02 && level <= 0.85 && boost <= 0.35 {
                    ctx.stroke(seg, with: .color(mint.opacity(0.25 + 0.6 * level)), style: StrokeStyle(lineWidth: 3.2, lineCap: .round))
                }
            }
            ctx.stroke(dim, with: .color(.white.opacity(0.22)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
            ctx.drawLayer { l in
                l.addFilter(.blur(radius: 6))
                l.stroke(lit, with: .color(mint.opacity(0.9)), style: StrokeStyle(lineWidth: 5, lineCap: .round))
                l.stroke(hot, with: .color(.white.opacity(0.8)), style: StrokeStyle(lineWidth: 6, lineCap: .round))
            }
            ctx.stroke(lit, with: .color(mint), style: StrokeStyle(lineWidth: 3.4, lineCap: .round))
            ctx.stroke(hot, with: .color(.white), style: StrokeStyle(lineWidth: 3.6, lineCap: .round))

            // A pointer outside the ticks: where the camera is looking round the item now.
            if recording {
                let a = (facingDeg - 90) * .pi / 180
                let rp = r + 48
                let tip = CGPoint(x: c.x + cos(a) * rp, y: c.y + sin(a) * rp)
                let dot = CGRect(x: tip.x - 4.5, y: tip.y - 4.5, width: 9, height: 9)
                ctx.fill(Path(ellipseIn: dot.insetBy(dx: -5, dy: -5)), with: .color(mint.opacity(session.paperSeen ? 0.25 : 0.08)))
                ctx.fill(Path(ellipseIn: dot), with: .color(session.paperSeen ? .white : .white.opacity(0.35)))
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
                return session.paperSeen ? ("Item in the ring · tap to start", "viewfinder") : ("Put the item on the paper, in the ring", "doc")
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
