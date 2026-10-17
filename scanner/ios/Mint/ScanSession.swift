import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// Owns the AR session and the scan state machine:
/// starting (finding the table) → aiming (item found + sized) → scanning (dome filling, recording)
/// → saving → done (files ready to share).
@MainActor
final class ScanSession: NSObject, ObservableObject {
    enum Phase: Equatable {
        case starting, aiming, scanning, saving
        case done(ScanSummary)
        case failed(String)
    }

    /// What the aiming bracket shows.
    struct Found: Equatable {
        let boundsInView: CGRect
        let estimate: ObjectEstimate?
        let planeY: Float?
    }

    @Published private(set) var phase: Phase = .starting
    @Published private(set) var found: Found?
    @Published private(set) var filled: Set<SegmentID> = []
    @Published private(set) var position: DomePosition?
    @Published private(set) var hint: Hint?
    @Published private(set) var issue: CaptureIssue?
    @Published private(set) var cameraLocked = false
    @Published private(set) var scanStart: Date?

    var coveragePct: Int { filled.count * 100 / Dome.segmentCount }
    var isComplete: Bool { filled.count >= Dome.segmentsToComplete }

    let arView: ARView
    private let processor = FrameProcessor()
    private var dome: DomeEntity?
    private var item: (estimate: ObjectEstimate, planeY: Float)?
    private var smoother = EstimateSmoother()
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
        processor.onDetection = { [weak self] in self?.applyDetection($0) }
        processor.onTrackingChange = { [weak self] state in
            guard let self, self.phase == .starting, case .normal = state else { return }
            self.phase = .aiming
            self.processor.startAiming()
        }
    }

    /// Starts (or restarts) tracking. A restart loses the world frame, so any scan in progress is dropped.
    func run() {
        reset()
        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        // Full 4:3 sensor frames (D2): ARKit's K refers to exactly these pixels.
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats
            .filter({ $0.imageResolution == CGSize(width: 1920, height: 1440) })
            .max(by: { $0.framesPerSecond < $1.framesPerSecond }) {
            config.videoFormat = format
        }
        arView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
        phase = .starting
    }

    func pause() {
        processor.cancel()
        arView.session.pause()
    }

    /// While aiming: tap picks which item to scan.
    func handleTap(at point: CGPoint) {
        guard phase == .aiming, let frame = arView.session.currentFrame else { return }
        let size = arView.bounds.size
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        let sensor = CGPoint(x: point.x / size.width, y: point.y / size.height).applying(toView.inverted())
        processor.setPreferredPoint(CGPoint(x: 1 - sensor.y, y: sensor.x))  // sensor → upright
        smoother = EstimateSmoother()
        tick.impactOccurred(intensity: 0.6)
    }

    var canStart: Bool { phase == .aiming && found?.estimate != nil }

    func start() {
        guard canStart, let est = found?.estimate, let planeY = found?.planeY else { return }
        item = (est, planeY)
        let dome = DomeEntity(at: est.centre)
        dome.radius = est.domeRadius
        arView.scene.addAnchor(dome.anchor)
        self.dome = dome

        cameraLocked = CameraLock.lock()
        let recorder: Recorder?
        do {
            recorder = try Recorder()
        } catch {
            phase = .failed("Couldn't start recording: \(error.localizedDescription)")
            return
        }
        processor.startScanning(item: est, recorder: recorder)
        filled = []
        issueDebounce = IssueDebounce()
        found = nil
        scanStart = Date()
        phase = .scanning
        tick.prepare()
        success.prepare()
        tick.impactOccurred(intensity: 1)
    }

    /// Finish now (auto at 90%, or the Finish button).
    func finish() {
        guard phase == .scanning, let item else { return }
        phase = .saving
        let coverage = coveragePct, segments = filled, locked = cameraLocked
        processor.finish { recorder, sensorSize in
            guard let recorder else {
                DispatchQueue.main.async { MainActor.assumeIsolated { self.phase = .failed("Nothing was recorded.") } }
                return
            }
            recorder.finish(item: item.estimate, planeY: item.planeY, coveragePct: coverage, filled: segments,
                            sensorSize: sensorSize, exposureLocked: locked) { [weak self] result in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    CameraLock.unlock()
                    self.cameraLocked = false
                    switch result {
                    case .success(let s):
                        self.phase = .done(ScanSummary(s))
                    case .failure(let e):
                        self.phase = .failed("Couldn't save the scan: \(e.localizedDescription)")
                    }
                }
            }
        }
    }

    /// Pinch to fit the dome around bigger or smaller items.
    func scaleDome(by factor: Float) {
        guard let dome else { return }
        dome.radius = min(max(dome.radius * factor, 0.06), 1.5)
    }

    /// Back to aiming; drops any scan in progress.
    func reset() {
        processor.cancel()
        if let dome { arView.scene.removeAnchor(dome.anchor) }
        dome = nil
        item = nil
        CameraLock.unlock()
        cameraLocked = false
        filled = []
        position = nil
        hint = nil
        issue = nil
        found = nil
        scanStart = nil
        smoother = EstimateSmoother()
        if phase != .starting {
            phase = .aiming
            processor.startAiming()
        }
    }

    private func applyDetection(_ result: ObjectDetector.Result?) {
        guard phase == .aiming else { return }
        guard let result, result.areaFraction > 0.003,
              let frame = arView.session.currentFrame else {
            found = nil
            return
        }
        let size = arView.bounds.size
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        let b = result.boundsUpright
        // Upright normalized → sensor normalized (u = v′, v = 1 − u′) → view.
        let corners = [CGPoint(x: b.minX, y: b.minY), CGPoint(x: b.maxX, y: b.minY),
                       CGPoint(x: b.minX, y: b.maxY), CGPoint(x: b.maxX, y: b.maxY)]
            .map { CGPoint(x: $0.y, y: 1 - $0.x).applying(toView) }
            .map { CGPoint(x: $0.x * size.width, y: $0.y * size.height) }
        let xs = corners.map(\.x), ys = corners.map(\.y)
        let rect = CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)

        let planeY = tablePlaneY(below: result)
        let raw = planeY.flatMap {
            ObjectSizing.estimate(camera: result.camera, contactRays: result.contactRays,
                                  silhouetteRays: result.silhouetteRays, planeY: $0)
        }
        found = Found(boundsInView: rect, estimate: raw.map { smoother.feed($0) }, planeY: planeY)
    }

    /// The table: an ARKit plane hit along the middle contact ray (where the item touches the surface).
    private func tablePlaneY(below result: ObjectDetector.Result) -> Float? {
        guard !result.contactRays.isEmpty else { return nil }
        let mid = result.contactRays[result.contactRays.count / 2]
        for target in [ARRaycastQuery.Target.existingPlaneInfinite, .estimatedPlane] {
            let q = ARRaycastQuery(origin: mid.origin, direction: mid.direction, allowing: target, alignment: .horizontal)
            if let hit = arView.session.raycast(q).first {
                return hit.worldTransform.translation.y
            }
        }
        return nil
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
            issue = nil
            success.notificationOccurred(.success)
            finish()
        }
    }
}

/// What the done screen shows.
struct ScanSummary: Equatable {
    let directory: URL
    let scanID: String
    let seconds: Double
    let videoFrames: Int
    let keyframes: Int
    let megabytes: Double
    let coveragePct: Int

    init(_ s: Recorder.Summary) {
        directory = s.directory
        scanID = s.scanID
        seconds = Double(s.durationMs) / 1000
        videoFrames = s.videoFrames
        keyframes = s.keyframes
        megabytes = Double(s.bytes) / 1_000_000
        coveragePct = s.coveragePct
    }
}

/// Steadies the size readout while aiming: averages estimates of the same item, resets when it jumps.
private struct EstimateSmoother {
    private var current: ObjectEstimate?
    private var n = 0

    mutating func feed(_ e: ObjectEstimate) -> ObjectEstimate {
        guard let c = current, simd_distance(c.footprintCentre, e.footprintCentre) < 0.05 else {
            current = e
            n = 1
            return e
        }
        n = min(n + 1, 8)
        let a = 1 / Float(n)
        func mix(_ x: Float, _ y: Float) -> Float { x + (y - x) * a }
        let next = ObjectEstimate(footprintCentre: c.footprintCentre + (e.footprintCentre - c.footprintCentre) * a,
                                  width: mix(c.width, e.width), height: mix(c.height, e.height), depth: mix(c.depth, e.depth))
        current = next
        return next
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
