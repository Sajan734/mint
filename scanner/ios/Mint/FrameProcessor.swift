import ARKit
import CoverageKit

/// Runs on its own serial queue as the ARSession delegate: reduces each frame to a thumbnail,
/// scores sharpness and feeds the coverage tracker. Never holds on to an ARFrame.
final class FrameProcessor: NSObject, ARSessionDelegate {
    struct Update {
        let decision: FrameDecision
        let filled: Set<SegmentID>
        let isComplete: Bool
        let hint: Hint
    }

    let queue = DispatchQueue(label: "mint.frames", qos: .userInteractive)
    /// Set once before the session runs; called on the main actor.
    var onUpdate: (@MainActor (Update) -> Void)?
    var onTrackingChange: (@MainActor (ARCamera.TrackingState) -> Void)?

    private var tracker: CoverageTracker?  // touched only on `queue`
    private var frameCount = 0
    private static let thumbnailFactor = 4      // 1920×1440 → 480×360
    private static let processEveryNthFrame = 2 // 60 fps camera → 30 Hz coverage updates

    func start(anchor: SIMD3<Float>) {
        queue.async {
            self.tracker = CoverageTracker(anchor: anchor)
            self.frameCount = 0
        }
    }

    func stop() {
        queue.async { self.tracker = nil }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        frameCount += 1
        guard var tracker, frameCount % Self.processEveryNthFrame == 0 else { return }

        let thumb = Self.thumbnail(frame.capturedImage)
        var trackingNormal = false
        if case .normal = frame.camera.trackingState { trackingNormal = true }

        let decision = tracker.observe(FrameObservation(
            cameraTransform: frame.camera.transform,
            timestamp: frame.timestamp,
            trackingNormal: trackingNormal,
            sharpness: thumb.map(Sharpness.laplacianVariance) ?? 0,
            meanLuma: thumb.map(Sharpness.meanLuma) ?? 0
        ))
        self.tracker = tracker

        let update = Update(
            decision: decision,
            filled: tracker.filled,
            isComplete: tracker.isComplete,
            hint: Guidance.hint(position: decision.position, filled: tracker.filled)
        )
        DispatchQueue.main.async { MainActor.assumeIsolated { self.onUpdate?(update) } }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let state = camera.trackingState
        DispatchQueue.main.async { MainActor.assumeIsolated { self.onTrackingChange?(state) } }
    }

    /// Downsampled luma (Y plane of the bi-planar YCbCr capturedImage).
    private static func thumbnail(_ buffer: CVPixelBuffer) -> GrayImage? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buffer) >= 1,
              let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return nil }
        return Sharpness.downsample(
            base: base.assumingMemoryBound(to: UInt8.self),
            width: CVPixelBufferGetWidthOfPlane(buffer, 0),
            height: CVPixelBufferGetHeightOfPlane(buffer, 0),
            bytesPerRow: CVPixelBufferGetBytesPerRowOfPlane(buffer, 0),
            factor: thumbnailFactor
        )
    }
}
