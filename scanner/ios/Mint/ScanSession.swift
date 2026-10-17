import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// Owns the AR session and the scan state machine:
/// starting (finding the table) → aim (tap the item) → scanning (dome filling) → complete (≥ 90%).
@MainActor
final class ScanSession: NSObject, ObservableObject {
    enum Phase: Equatable { case starting, aim, scanning, complete }

    @Published private(set) var phase: Phase = .starting
    @Published private(set) var filled: Set<SegmentID> = []
    @Published private(set) var position: DomePosition?
    @Published private(set) var hint: Hint?
    @Published private(set) var issue: CaptureIssue?
    @Published private(set) var cameraLocked = false
    @Published var tapError: String?

    var coveragePct: Int { filled.count * 100 / Dome.segmentCount }

    let arView: ARView
    private let processor = FrameProcessor()
    private var dome: DomeEntity?
    private var issueDebounce = IssueDebounce()
    private let tick = UIImpactFeedbackGenerator(style: .light)
    private let success = UINotificationFeedbackGenerator()

    override init() {
        arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        super.init()
        arView.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disablePersonOcclusion, .disableHDR]
        arView.session.delegate = processor
        arView.session.delegateQueue = processor.queue
        processor.onUpdate = { [weak self] in self?.apply($0) }
        processor.onTrackingChange = { [weak self] state in
            guard let self, self.phase == .starting, case .normal = state else { return }
            self.phase = .aim
        }
    }

    /// Starts (or restarts) tracking. A restart loses the world frame, so any scan in progress is dropped.
    func run() {
        reset()
        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        // Full 4:3 sensor frames (D2): K from ARKit refers to exactly these pixels.
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats
            .first(where: { $0.imageResolution == CGSize(width: 1920, height: 1440) }) {
            config.videoFormat = format
        }
        arView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
        phase = .starting
    }

    func pause() {
        arView.session.pause()
    }

    /// Tap on the item: anchor the dome at the item's base and lock the camera.
    func handleTap(at point: CGPoint) {
        guard phase == .aim else { return }
        guard let hit = arView.raycast(from: point, allowing: .estimatedPlane, alignment: .any).first else {
            tapError = "Couldn't find that spot. Try tapping the item again."
            return
        }
        let base = baseBelow(hit.worldTransform.translation)
        let dome = DomeEntity(at: base)
        arView.scene.addAnchor(dome.anchor)
        self.dome = dome

        cameraLocked = CameraLock.lock()
        processor.start(anchor: base)
        filled = []
        issueDebounce = IssueDebounce()
        tapError = nil
        phase = .scanning
        tick.prepare()
        success.prepare()
        tick.impactOccurred(intensity: 1)
    }

    /// Pinch to fit the dome around bigger or smaller items.
    func scaleDome(by factor: Float) {
        guard let dome else { return }
        dome.radius = min(max(dome.radius * factor, 0.1), 0.8)
    }

    func reset() {
        processor.stop()
        if let dome { arView.scene.removeAnchor(dome.anchor) }
        dome = nil
        CameraLock.unlock()
        cameraLocked = false
        filled = []
        position = nil
        hint = nil
        issue = nil
        phase = .aim
    }

    private func apply(_ u: FrameProcessor.Update) {
        guard phase == .scanning else { return }
        position = u.decision.position
        hint = u.hint
        issue = issueDebounce.feed(u.decision.issue)

        if u.decision.filledNewSegment, let seg = u.decision.segment {
            dome?.pulse(seg)
            tick.impactOccurred()
        }
        filled = u.filled
        dome?.update(filled: u.filled, cameraAzimuthDeg: u.decision.position.azimuthDeg)

        if u.isComplete {
            phase = .complete
            issue = nil
            processor.stop()
            success.notificationOccurred(.success)
        }
    }

    /// The tap usually lands on the item's surface. Drop the anchor straight down onto the table
    /// so elevations are measured from the item's base.
    private func baseBelow(_ p: SIMD3<Float>) -> SIMD3<Float> {
        let query = ARRaycastQuery(origin: p + [0, 0.01, 0], direction: [0, -1, 0],
                                   allowing: .existingPlaneInfinite, alignment: .horizontal)
        guard let floor = arView.session.raycast(query).first else { return p }
        let y = floor.worldTransform.translation.y
        return p.y - y < 1.0 ? SIMD3(p.x, y, p.z) : p
    }
}

/// Stops warnings flickering: an issue must persist ~0.2 s to show and be clear ~0.3 s to hide.
private struct IssueDebounce {
    private var candidate: CaptureIssue?
    private var count = 0
    private var shown: CaptureIssue?
    private var clearCount = 0

    mutating func feed(_ issue: CaptureIssue?) -> CaptureIssue? {
        if let issue {
            clearCount = 0
            count = issue == candidate ? count + 1 : 1
            candidate = issue
            if count >= 6 { shown = issue }
        } else {
            candidate = nil
            count = 0
            clearCount += 1
            if clearCount >= 10 { shown = nil }
        }
        return shown
    }
}
