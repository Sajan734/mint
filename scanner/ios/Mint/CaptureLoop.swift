import ARKit
import CoverageKit

/// The ARSession delegate, on its own serial queue: keeps the paper's angle fresh for the coverage
/// ring (~8 Hz) and, while recording, hands every frame (30 fps) to the recorder. Never holds an ARFrame.
final class CaptureLoop: NSObject, ARSessionDelegate {
    let queue = DispatchQueue(label: "mint.capture", qos: .userInteractive)
    /// Set once before the session runs; called on the main actor.
    var onSight: (@MainActor (PaperReader.Sight) -> Void)?
    /// Read QR codes too (while the app waits for a product). Set from the main actor; a stale read is harmless.
    var lookForCodes = false

    // Touched only on `queue`.
    private var recorder: VideoRecorder?
    private let reader = PaperReader()
    private var lastRecorded: TimeInterval = 0
    private var lastRead: TimeInterval = 0
    private var sensorSize = CGSize(width: 1920, height: 1440)

    private static let recordInterval = 1.0 / 30
    private static let readInterval = 0.12

    func startRecording(_ recorder: VideoRecorder) {
        queue.async {
            self.recorder = recorder
            self.lastRecorded = 0
        }
    }

    /// Stops recording and hands the recorder back on the capture queue (where `finish` must run).
    func stopRecording(_ body: @escaping (VideoRecorder?, CGSize) -> Void) {
        queue.async {
            let r = self.recorder
            self.recorder = nil
            body(r, self.sensorSize)
        }
    }

    func cancel() {
        queue.async {
            self.recorder?.cancel()
            self.recorder = nil
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        sensorSize = frame.camera.imageResolution
        if frame.timestamp - lastRead >= Self.readInterval {
            lastRead = frame.timestamp
            let t = frame.camera.transform
            let camera = PaperReader.Camera(
                rotation: simd_float3x3(SIMD3(t.columns.0.x, t.columns.0.y, t.columns.0.z),
                                        SIMD3(t.columns.1.x, t.columns.1.y, t.columns.1.z),
                                        SIMD3(t.columns.2.x, t.columns.2.y, t.columns.2.z)),
                intrinsics: frame.camera.intrinsics,
                timestamp: frame.timestamp)
            reader.process(frame.capturedImage, camera: camera, lookForCodes: lookForCodes) { sight in
                MainActor.assumeIsolated { self.onSight?(sight) }
                self.queue.async { self.reader.markIdle() }
            }
        }
        guard let recorder, frame.timestamp - lastRecorded >= Self.recordInterval - 0.004 else { return }
        lastRecorded = frame.timestamp

        let tracking: String
        switch frame.camera.trackingState {
        case .normal: tracking = "normal"
        case .limited: tracking = "limited"
        case .notAvailable: tracking = "not_available"
        }
        recorder.append(pixelBuffer: frame.capturedImage, timestamp: frame.timestamp, sensorSize: sensorSize, meta: .init(
            cameraTransform: frame.camera.transform,
            intrinsics: frame.camera.intrinsics,
            tracking: tracking,
            sharpness: Self.sharpness(frame.capturedImage)
        ))
    }

    /// Per-frame sharpness for reconstruction to pick the crispest frames (Accelerate, ~1 ms).
    private static func sharpness(_ buffer: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return 0 }
        return FastSharpness.measure(
            base: base,
            width: CVPixelBufferGetWidthOfPlane(buffer, 0),
            height: CVPixelBufferGetHeightOfPlane(buffer, 0),
            bytesPerRow: CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        )?.sharpness ?? 0
    }
}
