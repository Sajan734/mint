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
            VStack(spacing: 12) {
                topBar
                Spacer()
                guidance
                if session.phase == .scanning || session.phase == .complete {
                    CoverageRingView(filled: session.filled, cameraAzimuthDeg: session.position?.azimuthDeg,
                                     pct: session.coveragePct)
                        .frame(width: 168, height: 168)
                }
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
    }

    private var topBar: some View {
        HStack {
            if session.phase != .starting && session.phase != .aim {
                Button(action: session.reset) {
                    Image(systemName: "xmark").font(.headline).padding(12).background(.ultraThinMaterial, in: Circle())
                }
                .accessibilityLabel("Start over")
            }
            Spacer()
            if session.phase == .scanning {
                Label(session.cameraLocked ? "Exposure locked" : "Exposure not locked",
                      systemImage: session.cameraLocked ? "lock.fill" : "lock.open")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(.ultraThinMaterial, in: Capsule())
                    .foregroundStyle(session.cameraLocked ? Color.brandMint : Color.brandAmber)
            }
        }
    }

    @ViewBuilder private var guidance: some View {
        switch session.phase {
        case .starting:
            pill(Copy.finding, symbol: "viewfinder")
        case .aim:
            pill(session.tapError ?? Copy.aim, symbol: "hand.tap.fill",
                 tint: session.tapError == nil ? .white : .brandAmber)
        case .scanning:
            if let issue = session.issue {
                pill(Copy.issue(issue), symbol: "exclamationmark.triangle.fill", tint: .brandAmber)
            } else if let hint = session.hint {
                let h = Copy.hint(hint)
                pill(h.text, symbol: h.symbol)
            }
        case .complete:
            pill(Copy.complete, symbol: "checkmark.seal.fill", tint: .brandMint)
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
