import ARKit
import CoverageKit

/// The ARSession delegate, on its own serial queue. While aiming it runs the item detector a few
/// times a second; while scanning it scores each frame for coverage and hands it to the recorder.
/// Never holds on to an ARFrame.
final class FrameProcessor: NSObject, ARSessionDelegate {
    struct Update {
        let decision: FrameDecision
        let filled: Set<SegmentID>
        let isComplete: Bool
        let hint: Hint
    }

    private enum Mode { case idle, aiming, scanning }

    let queue = DispatchQueue(label: "mint.frames", qos: .userInteractive)
    /// Set once before the session runs; called on the main actor.
    var onUpdate: (@MainActor (Update) -> Void)?
    var onTrackingChange: (@MainActor (ARCamera.TrackingState) -> Void)?
    var onDetection: (@MainActor (ObjectDetector.Result?) -> Void)?

    // Everything below is touched only on `queue`.
    private var mode = Mode.idle
    private var tracker: CoverageTracker?
    private var recorder: Recorder?
    private let detector = ObjectDetector()
    private var preferredPoint = CGPoint(x: 0.5, y: 0.5)
    private var lastProcessed: TimeInterval = 0
    private var lastDetect: TimeInterval = 0
    private var sensorSize = CGSize(width: 1920, height: 1440)
    /// ARKit's triangulated feature points (world), by identifier, with when each was last seen.
    private var cloud: [UInt64: (point: SIMD3<Float>, seen: TimeInterval)] = [:]

    private static let scanInterval = 1.0 / 30     // video + coverage at 30 fps
    private static let detectInterval = 0.25       // item detection at ~4 Hz
    private static let cloudMemory = 4.0           // seconds a feature point is kept after last seen

    func startAiming() {
        queue.async {
            self.mode = .aiming
            self.tracker = nil
            self.cloud.removeAll()
        }
    }

    /// Upright (portrait) normalized image point the user tapped: pick the item under it.
    func setPreferredPoint(_ p: CGPoint) {
        queue.async { self.preferredPoint = p }
    }

    func startScanning(item: ObjectEstimate, recorder: Recorder?) {
        var config = CoverageConfig()
        // Keep the item big in the frame (sharper splat): a ~6 cm-radius mouse wants 15–42 cm,
        // a ~16 cm-radius bottle 35 cm–1.1 m. The first one-lap scan had the mouse at ~3% of the image.
        let r = 0.5 * (item.width * item.width + item.height * item.height + item.depth * item.depth).squareRoot()
        config.minDistanceM = max(0.15, r * 2.2)
        config.maxDistanceM = max(0.3, r * 7)
        queue.async {
            self.tracker = CoverageTracker(anchor: item.centre, config: config)
            self.recorder = recorder
            self.lastProcessed = 0
            self.mode = .scanning
        }
    }

    /// Stops scanning and hands the recorder back on the frame queue (where `Recorder.finish` must run).
    func finish(_ body: @escaping (Recorder?, CGSize) -> Void) {
        queue.async {
            self.mode = .idle
            self.tracker = nil
            let r = self.recorder
            self.recorder = nil
            body(r, self.sensorSize)
        }
    }

    func cancel() {
        queue.async {
            self.recorder?.cancel()
            self.recorder = nil
            self.tracker = nil
            self.mode = .idle
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        sensorSize = frame.camera.imageResolution
        switch mode {
        case .idle:
            return
        case .aiming:
            detect(frame)
        case .scanning:
            scan(frame)
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let state = camera.trackingState
        DispatchQueue.main.async { MainActor.assumeIsolated { self.onTrackingChange?(state) } }
    }

    private func detect(_ frame: ARFrame) {
        // Every frame: remember ARKit's 3D feature points (cheap; they're what measures the item).
        if let pc = frame.rawFeaturePoints {
            for (i, id) in pc.identifiers.enumerated() { cloud[id] = (pc.points[i], frame.timestamp) }
        }
        guard frame.timestamp - lastDetect >= Self.detectInterval else { return }
        guard case .normal = frame.camera.trackingState else { return }
        lastDetect = frame.timestamp
        cloud = cloud.filter { frame.timestamp - $0.value.seen < Self.cloudMemory }
        detector.detect(.init(
            pixelBuffer: frame.capturedImage,
            cameraTransform: frame.camera.transform,
            intrinsics: frame.camera.intrinsics,
            imageSize: frame.camera.imageResolution,
            preferredPoint: preferredPoint,
            cloud: cloud.values.map(\.point)
        )) { result in
            MainActor.assumeIsolated { self.onDetection?(result) }
            self.queue.async { self.detector.markIdle() }
        }
    }

    private func scan(_ frame: ARFrame) {
        guard var tracker, frame.timestamp - lastProcessed >= Self.scanInterval - 0.004 else { return }
        lastProcessed = frame.timestamp

        let measured = Self.measure(frame.capturedImage)
        let tracking: String
        switch frame.camera.trackingState {
        case .normal: tracking = "normal"
        case .limited: tracking = "limited"
        case .notAvailable: tracking = "not_available"
        }
        let sharpness = measured?.sharpness ?? 0

        let decision = tracker.observe(FrameObservation(
            cameraTransform: frame.camera.transform,
            timestamp: frame.timestamp,
            trackingNormal: tracking == "normal",
            sharpness: sharpness,
            meanLuma: measured?.meanLuma ?? 0
        ))
        self.tracker = tracker

        // The item hasn't moved yet (no hand-turn tracking), so camera-to-item = camera-to-world.
        recorder?.append(pixelBuffer: frame.capturedImage, timestamp: frame.timestamp, sensorSize: sensorSize, meta: .init(
            cameraTransform: frame.camera.transform,
            itemPose: frame.camera.transform,
            intrinsics: frame.camera.intrinsics,
            tracking: tracking,
            state: "scanning",
            sharpness: sharpness,
            segment: decision.segment,
            isBestForSegment: decision.isBestForSegment
        ))

        let update = Update(
            decision: decision,
            filled: tracker.filled,
            isComplete: tracker.isComplete,
            hint: Guidance.hint(position: decision.position, filled: tracker.filled)
        )
        DispatchQueue.main.async { MainActor.assumeIsolated { self.onUpdate?(update) } }
    }

    /// Sharpness + brightness of the luma (Y) plane, via Accelerate (~1 ms; the plain-Swift version
    /// took ~50 ms in Debug builds and capped capture at ~14 fps).
    private static func measure(_ buffer: CVPixelBuffer) -> FastSharpness.Result? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buffer) >= 1,
              let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return nil }
        return FastSharpness.measure(
            base: base,
            width: CVPixelBufferGetWidthOfPlane(buffer, 0),
            height: CVPixelBufferGetHeightOfPlane(buffer, 0),
            bytesPerRow: CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        )
    }
}
