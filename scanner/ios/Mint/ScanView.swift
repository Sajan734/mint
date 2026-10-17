import ARKit
import CoverageKit
import RealityKit
import SwiftUI

struct ScanView: View {
    @StateObject private var session = ScanSession()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            ARViewContainer(session: session).ignoresSafeArea()

            if session.phase == .aiming, let found = session.found {
                FoundBracket(found: found)
                    .allowsHitTesting(false)
                    .ignoresSafeArea()
            }

            VStack(spacing: 12) {
                topBar
                Spacer()
                guidance
                bottom
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 20)
        }
        .background(Color.brandStageBg)
        .onAppear { session.run() }
        .onChange(of: scenePhase) { old, phase in
            // Only a real trip to the background restarts; Control Centre etc. (.inactive) doesn't.
            if phase == .background { session.pause() }
            if phase == .active && old == .background { session.run() }
        }
        .sheet(item: doneBinding) { summary in
            DoneSheet(summary: summary) { session.reset() }
                .presentationDetents([.medium])
                .interactiveDismissDisabled()
        }
    }

    private var doneBinding: Binding<ScanSummary?> {
        Binding(
            get: { if case .done(let s) = session.phase { return s } else { return nil } },
            set: { if $0 == nil { session.reset() } }
        )
    }

    private var topBar: some View {
        HStack {
            if session.phase == .scanning {
                Button(action: session.reset) {
                    Image(systemName: "xmark").font(.headline).padding(12).background(.ultraThinMaterial, in: Circle())
                }
                .accessibilityLabel("Cancel scan")
                Spacer()
                if let start = session.scanStart {
                    TimelineView(.periodic(from: start, by: 0.1)) { ctx in
                        Text(String(format: "%.0f s", ctx.date.timeIntervalSince(start)))
                            .font(.system(.headline, design: .rounded)).monospacedDigit()
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(.ultraThinMaterial, in: Capsule())
                    }
                }
                Spacer()
                Image(systemName: session.cameraLocked ? "lock.fill" : "lock.open")
                    .font(.headline)
                    .foregroundStyle(session.cameraLocked ? Color.brandMint : Color.brandAmber)
                    .padding(12).background(.ultraThinMaterial, in: Circle())
                    .accessibilityLabel(session.cameraLocked ? "Exposure locked" : "Exposure not locked")
            }
        }
    }

    @ViewBuilder private var guidance: some View {
        switch session.phase {
        case .starting:
            pill(Copy.finding, symbol: "viewfinder")
        case .aiming:
            if let found = session.found {
                if found.estimate != nil {
                    pill(Copy.found(locked: found.locked), symbol: found.locked ? "lock.fill" : "scope",
                         tint: found.locked ? .brandMint : .white)
                } else {
                    pill(found.planeY == nil ? Copy.findingTable : Copy.needMotion, symbol: "scope")
                }
            } else {
                pill(Copy.aim, symbol: "scope")
            }
        case .scanning:
            if let issue = session.issue {
                pill(Copy.issue(issue), symbol: "exclamationmark.triangle.fill", tint: .brandAmber)
            } else if let hint = session.hint {
                let h = Copy.hint(hint)
                pill(h.text, symbol: h.symbol)
            }
        case .saving:
            pill(Copy.saving, symbol: "arrow.down.doc.fill", tint: .brandMint)
        case .done:
            EmptyView()
        case .failed(let message):
            pill(message, symbol: "xmark.octagon.fill", tint: .brandAmber)
        }
    }

    @ViewBuilder private var bottom: some View {
        switch session.phase {
        case .aiming:
            Button(action: session.start) {
                Text("Start scan")
                    .font(.title3.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 56)
            }
            .buttonStyle(.borderedProminent)
            .tint(.brandMint)
            .foregroundStyle(Color.brandStageBg)
            .disabled(!session.canStart)
            if session.showStartAnyway {
                Button("Start anyway", action: session.startAnyway)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.top, 2)
            }
        case .scanning, .saving:
            HStack(alignment: .bottom) {
                Spacer().frame(width: 64)
                Spacer()
                CoverageRingView(filled: session.filled, cameraAzimuthDeg: session.position?.azimuthDeg,
                                 pct: session.coveragePct)
                    .frame(width: 168, height: 168)
                Spacer()
                Button(action: session.finish) {
                    Image(systemName: "stop.fill").font(.title2).frame(width: 64, height: 64)
                        .background(.ultraThinMaterial, in: Circle())
                }
                .disabled(session.phase != .scanning)
                .accessibilityLabel("Finish scan now")
            }
        case .failed:
            Button("Try again", action: session.reset).buttonStyle(.borderedProminent).tint(.brandMint)
        case .starting, .done:
            EmptyView()
        }
    }

    private func pill(_ text: String, symbol: String, tint: Color = .white) -> some View {
        Label(text, systemImage: symbol)
            .font(.headline)
            .foregroundStyle(tint)
            .padding(.horizontal, 16).padding(.vertical, 12)
            .background(.ultraThinMaterial, in: Capsule())
            .animation(.easeOut(duration: 0.2), value: text)
            .accessibilityAddTraits(.updatesFrequently)
    }
}

extension ScanSummary: Identifiable {
    var id: String { scanID }
}

/// Corner brackets that glide to the detected item.
private struct FoundBracket: View {
    let found: ScanSession.Found

    var body: some View {
        let r = found.boundsInView.insetBy(dx: -10, dy: -10)
        let len = min(28, r.width / 3, r.height / 3)
        Path { p in
            for (corner, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                                     (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
                p.move(to: CGPoint(x: corner.x + dx * len, y: corner.y))
                p.addLine(to: corner)
                p.addLine(to: CGPoint(x: corner.x, y: corner.y + dy * len))
            }
        }
        .stroke(found.locked ? Color.brandMint : Color.white, style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
        .shadow(color: .black.opacity(0.4), radius: 4)
        .animation(.spring(response: 0.3, dampingFraction: 0.85), value: found.boundsInView)
    }
}

/// Hosts the RealityKit ARView, the plane-finding coaching overlay, and tap/pinch gestures.
private struct ARViewContainer: UIViewRepresentable {
    let session: ScanSession

    func makeCoordinator() -> Coordinator { Coordinator(session: session) }

    func makeUIView(context: Context) -> ARView {
        let view = session.arView
        let coaching = ARCoachingOverlayView()
        coaching.session = view.session
        coaching.goal = .horizontalPlane
        coaching.activatesAutomatically = true
        coaching.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(coaching)

        view.addGestureRecognizer(UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tap(_:))))
        view.addGestureRecognizer(UIPinchGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.pinch(_:))))
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {}

    @MainActor final class Coordinator: NSObject {
        let session: ScanSession
        init(session: ScanSession) { self.session = session }

        @objc func tap(_ g: UITapGestureRecognizer) {
            session.handleTap(at: g.location(in: g.view))
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            guard g.state == .changed else { return }
            session.scaleDome(by: Float(g.scale))
            g.scale = 1
        }
    }
}
