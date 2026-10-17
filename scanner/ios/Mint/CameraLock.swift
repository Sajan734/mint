import ARKit
import AVFoundation

/// Camera control for a sharp, consistent scan, through the AVCaptureDevice ARKit exposes for its
/// primary camera (iOS 16+).
///
/// - While lining up, autofocus and auto exposure aim at the item (`aim(at:)`), not at whatever is in the
///   middle of the frame (often the table or the wall behind).
/// - At scan start, focus, exposure and white balance lock (`lock()`). In a turntable scan the phone stays
///   still and the item turns, so the distance never changes: a locked focus keeps every frame sharp, where
///   continuous autofocus hunts as the item turns, blurs frames (the edges first) and shifts the focal length
///   a little between frames, which the splat cannot model.
enum CameraLock {
    @discardableResult
    static func lock() -> Bool {
        configure { d in
            if d.isFocusModeSupported(.locked) { d.focusMode = .locked }
            if d.isExposureModeSupported(.locked) { d.exposureMode = .locked }
            if d.isWhiteBalanceModeSupported(.locked) { d.whiteBalanceMode = .locked }
        }
    }

    /// Point autofocus and auto exposure at the item. `point` is sensor-normalized (0…1, top-left origin,
    /// the camera's landscape orientation), which is also AVCaptureDevice's point-of-interest space.
    static func aim(at point: CGPoint) {
        configure { d in
            if d.isFocusPointOfInterestSupported, d.isFocusModeSupported(.continuousAutoFocus) {
                d.focusPointOfInterest = point
                d.focusMode = .continuousAutoFocus
            }
            if d.isExposurePointOfInterestSupported, d.isExposureModeSupported(.continuousAutoExposure) {
                d.exposurePointOfInterest = point
                d.exposureMode = .continuousAutoExposure
            }
        }
    }

    static func unlock() {
        configure { d in
            if d.isFocusModeSupported(.continuousAutoFocus) { d.focusMode = .continuousAutoFocus }
            if d.isExposureModeSupported(.continuousAutoExposure) { d.exposureMode = .continuousAutoExposure }
            if d.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) { d.whiteBalanceMode = .continuousAutoWhiteBalance }
        }
    }

    private static func configure(_ body: (AVCaptureDevice) -> Void) -> Bool {
        guard let device = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else { return false }
        do {
            try device.lockForConfiguration()
            body(device)
            device.unlockForConfiguration()
            return true
        } catch {
            return false
        }
    }
}
