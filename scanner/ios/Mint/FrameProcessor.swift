import ARKit
import CoverageKit

/// The ARSession delegate, on its own serial queue. While aiming it runs the item detector a few
/// times a second (and looks for the sheet of paper under the item); while scanning it scores each
/// frame for coverage and hands it to the recorder. In turntable mode it reads the paper every frame
/// and works in the item's frame (the item turns, the phone stays still). Never holds on to an ARFrame.
final class FrameProcessor: NSObject, ARSessionDelegate {
    struct Update {
        let decision: FrameDecision
        let filled: Set<SegmentID>
        let isComplete: Bool
        let hint: Hint
        /// Turntable: the item's motion since Start (nil = not turntable, or the paper wasn't read).
        let itemMotion: simd_float4x4?
        let paperLost: Bool
    }

    private enum Mode { case idle, aiming, scanning }

    let queue = DispatchQueue(label: "mint.frames", qos: .userInteractive)
    /// Set once before the session runs; called on the main actor.
    var onUpdate: (@MainActor (Update) -> Void)?
    var onTrackingChange: (@MainActor (ARCamera.TrackingState) -> Void)?
    var onDetection: (@MainActor (ObjectDetector.Result?) -> Void)?
    /// While aiming: the sheet under the item, or nil if none is seen.
    var onPaper: (@MainActor (PaperPose?) -> Void)?

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
    private var sticky: SIMD3<Float>?       // tracked item centre (detection sticks to it)
    private var tableY: Float?
    // Turntable: where to look for the paper (the item's (x, z) on the table), and the follower.
    private var paperTarget: (near: SIMD2<Float>, planeY: Float)?
    private var aimPaper = PaperFollower()
    private var lastPaperRead: TimeInterval = 0
    private var turntable: (follower: PaperFollower, centre: SIMD3<Float>, base: SIMD3<Float>, planeY: Float)?

    private static let scanInterval = 1.0 / 30     // video + coverage at 30 fps
    private static let detectInterval = 0.25       // item detection at ~4 Hz while aiming
    private static let trackInterval = 0.2         // and ~5 Hz while scanning (keeps the ring on the item)
    private static let cloudMemory = 4.0           // seconds a feature point is kept after last seen
    private static let paperAimInterval = 0.15     // looking for the paper while aiming (~7 Hz)

    func startAiming() {
        queue.async {
            self.mode = .aiming
            self.tracker = nil
            self.cloud.removeAll()
            self.sticky = nil
            self.tableY = nil
            self.paperTarget = nil
            self.aimPaper = PaperFollower()
            self.turntable = nil
        }
    }

    /// While aiming: look for a sheet of paper under the item at (x, z) on the table at `planeY`.
    func setPaperTarget(near: SIMD2<Float>?, planeY: Float?) {
        queue.async {
            if let near, let planeY { self.paperTarget = (near, planeY) } else { self.paperTarget = nil }
        }
    }

    /// Upright (portrait) normalized image point the user tapped: pick the item under it.
    func setPreferredPoint(_ p: CGPoint) {
        queue.async { self.preferredPoint = p }
    }

    /// The tracked item (detection sticks to it) and the table height (flat instances are skipped).
    func setTarget(sticky: SIMD3<Float>?, tableY: Float?) {
        queue.async {
            self.sticky = sticky
            self.tableY = tableY
        }
    }

    /// The tracked item centre moved: coverage angles are measured from it.
    func updateAnchor(_ centre: SIMD3<Float>) {
        queue.async {
            self.sticky = centre
            self.tracker?.anchor = centre
        }
    }

    /// `turntable`: the item sits on a sheet that the user turns; coverage and poses are in the item's frame.
    func startScanning(item: ObjectEstimate, recorder: Recorder?, turntable: Bool, planeY: Float) {
        var config = CoverageConfig()
        // Keep the item big in the frame (sharper splat): a ~6 cm-radius mouse wants 15–42 cm,
        // a ~16 cm-radius bottle 35 cm–1.1 m. The first one-lap scan had the mouse at ~3% of the image.
        let r = 0.5 * (item.width * item.width + item.height * item.height + item.depth * item.depth).squareRoot()
        config.minDistanceM = max(0.15, r * 2.2)
        // On a turntable the whole sheet (~28 cm) must stay in view, which needs ~40–50 cm; the first
        // turntable recording sat at 40 cm. Walking: keep the item big in the frame.
        config.maxDistanceM = turntable ? max(0.55, r * 7) : max(0.3, r * 7)
        queue.async {
            self.tracker = CoverageTracker(anchor: item.centre, config: config)
            self.recorder = recorder
            self.lastProcessed = 0
            // Seed with what aiming learnt about the sheet, so a hand on a corner at Start is fine.
            var follower = self.aimPaper.isTracking ? self.aimPaper : PaperFollower()
            follower.restart()
            self.turntable = turntable ? (follower, item.centre, item.footprintCentre, planeY) : nil
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
        if let target = paperTarget, frame.timestamp - lastPaperRead >= Self.paperAimInterval {
            lastPaperRead = frame.timestamp
            let pose = Self.readPaper(frame, near: target.near, planeY: target.planeY).flatMap { aimPaper.update($0) }
            if pose == nil { aimPaper = PaperFollower() }
            DispatchQueue.main.async { MainActor.assumeIsolated { self.onPaper?(pose) } }
        }
        guard frame.timestamp - lastDetect >= Self.detectInterval else { return }
        cloud = cloud.filter { frame.timestamp - $0.value.seen < Self.cloudMemory }
        runDetection(frame, cloud: cloud.values.map(\.point))
    }

    private func runDetection(_ frame: ARFrame, cloud: [SIMD3<Float>]) {
        guard case .normal = frame.camera.trackingState else { return }
        lastDetect = frame.timestamp
        detector.detect(.init(
            pixelBuffer: frame.capturedImage,
            cameraTransform: frame.camera.transform,
            intrinsics: frame.camera.intrinsics,
            imageSize: frame.camera.imageResolution,
            preferredPoint: preferredPoint,
            cloud: cloud,
            sticky: sticky,
            tableY: tableY
        )) { result in
            MainActor.assumeIsolated { self.onDetection?(result) }
            self.queue.async { self.detector.markIdle() }
        }
    }

    private func scan(_ frame: ARFrame) {
        // Walking mode keeps the ring on the item with masks; in turntable mode the paper does that.
        if turntable == nil, frame.timestamp - lastDetect >= Self.trackInterval { runDetection(frame, cloud: []) }
        guard var tracker, frame.timestamp - lastProcessed >= Self.scanInterval - 0.004 else { return }
        lastProcessed = frame.timestamp

        // Turntable: read the paper → the item's motion since Start → the camera in the item's frame.
        var cameraInItem = frame.camera.transform
        var itemMotion: simd_float4x4?
        var itemCentreNow = tracker.anchor
        var paperLost = false
        if var tt = turntable {
            let near = SIMD2(tt.follower.current.map { $0.centre.x } ?? tt.base.x, tt.follower.current.map { $0.centre.z } ?? tt.base.z)
            if let reading = Self.readPaper(frame, near: near, planeY: tt.planeY), tt.follower.update(reading) != nil,
               let m = tt.follower.motion(planeY: tt.planeY) {
                itemMotion = m
                cameraInItem = Turntable.cameraInItemFrame(camera: frame.camera.transform, itemMotion: m)
                let c = m * SIMD4(tt.centre, 1)
                itemCentreNow = SIMD3(c.x, c.y, c.z)
            } else {
                paperLost = true
            }
            turntable = tt
        }

        let measured = Self.measure(frame.capturedImage)
        let tracking: String
        switch frame.camera.trackingState {
        case .normal: tracking = "normal"
        case .limited: tracking = "limited"
        case .notAvailable: tracking = "not_available"
        }
        let sharpness = measured?.sharpness ?? 0

        // A frame where the paper wasn't read has no trustworthy item pose: record it, don't score it.
        let decision: FrameDecision? = paperLost ? nil : tracker.observe(FrameObservation(
            cameraTransform: cameraInItem,
            timestamp: frame.timestamp,
            trackingNormal: tracking == "normal",
            sharpness: sharpness,
            meanLuma: measured?.meanLuma ?? 0
        ))
        self.tracker = tracker

        // Walking: the item doesn't move, so camera-to-item = camera-to-world (item_centre records
        // where ARKit's drifting world puts it). Turntable: camera-to-item undoes the paper's turn.
        recorder?.append(pixelBuffer: frame.capturedImage, timestamp: frame.timestamp, sensorSize: sensorSize, meta: .init(
            cameraTransform: frame.camera.transform,
            itemPose: paperLost ? nil : cameraInItem,
            intrinsics: frame.camera.intrinsics,
            tracking: tracking,
            state: paperLost ? "paper_lost" : "scanning",
            sharpness: sharpness,
            segment: decision?.segment,
            isBestForSegment: decision?.isBestForSegment ?? false,
            itemCentre: itemCentreNow
        ))

        guard let decision else {
            let lost = Update(decision: FrameDecision(position: Dome.position(camera: cameraInItem.translation, anchor: tracker.anchor),
                                                      segment: nil, issue: .trackingLimited, filledNewSegment: false, isBestForSegment: false),
                              filled: tracker.filled, isComplete: tracker.isComplete, hint: .holdHere, itemMotion: nil, paperLost: true)
            DispatchQueue.main.async { MainActor.assumeIsolated { self.onUpdate?(lost) } }
            return
        }
        let update = Update(
            decision: decision,
            filled: tracker.filled,
            isComplete: tracker.isComplete,
            hint: Guidance.hint(position: decision.position, filled: tracker.filled),
            itemMotion: itemMotion,
            paperLost: false
        )
        DispatchQueue.main.async { MainActor.assumeIsolated { self.onUpdate?(update) } }
    }

    /// Reads the sheet of paper around `near` (x, z) on the table: the camera image resampled onto a
    /// top-down 50 × 50 cm map (2.5 mm cells, the settings validated on the first turntable recording:
    /// paper found in 565/566 frames, 0.5° median from an independent detector).
    private static func readPaper(_ frame: ARFrame, near: SIMD2<Float>, planeY: Float) -> PaperReading? {
        let buffer = frame.capturedImage
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buffer) >= 2,
              let yBase = CVPixelBufferGetBaseAddressOfPlane(buffer, 0),
              let cBase = CVPixelBufferGetBaseAddressOfPlane(buffer, 1) else { return nil }
        let yp = yBase.assumingMemoryBound(to: UInt8.self), cp = cBase.assumingMemoryBound(to: UInt8.self)
        let w = CVPixelBufferGetWidthOfPlane(buffer, 0), h = CVPixelBufferGetHeightOfPlane(buffer, 0)
        let yBpr = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0), cBpr = CVPixelBufferGetBytesPerRowOfPlane(buffer, 1)
        let w2c = frame.camera.transform.inverse
        let k = frame.camera.intrinsics
        let fx = k[0][0], fy = k[1][1], cx = k[2][0], cy = k[2][1]

        var map = TableMap(centre: near, halfSize: 0.25, res: 0.0025)
        map.fill(planeY: planeY) { p in
            let c = w2c * SIMD4(p, 1)
            guard c.z < -0.02 else { return nil }
            let u = Int(fx * c.x / -c.z + cx), v = Int(fy * -c.y / -c.z + cy)
            guard u >= 0, v >= 0, u < w, v < h else { return nil }
            // Full-range YCbCr → RGB, then chroma = max − min (paper ≈ 2, beige table ≈ 43).
            let y = Float(yp[v * yBpr + u])
            let ci = (v / 2) * cBpr + (u / 2) * 2
            let cb = Float(cp[ci]) - 128, cr = Float(cp[ci + 1]) - 128
            let r = y + 1.402 * cr, g = y - 0.344 * cb - 0.714 * cr, b = y + 1.772 * cb
            let chroma = max(0, min(255, max(r, g, b) - min(r, g, b)))
            return (UInt8(min(255, max(0, y))), UInt8(chroma))
        }
        return PaperDetector.read(map, near: near)
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
