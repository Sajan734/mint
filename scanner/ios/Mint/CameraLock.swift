import ARKit
import AVFoundation

/// Camera control for a sharp, consistent scan, through the AVCaptureDevice ARKit exposes for its
/// primary camera (iOS 16+).
///
/// - While lining up, autofocus and auto exposure are continuous, on the middle of the frame or on the point
///   the user tapped (`focus(at:holdExposure:)`), like the Camera app.
/// - At scan start, focus, exposure and white balance lock (`lock()`). In a turntable scan the phone stays
///   still and the item turns, so the distance never changes: a locked focus keeps every frame sharp, where
///   continuous autofocus hunts as the item turns, blurs frames (the edges first) and shifts the focal length
///   a little between frames, which the splat cannot model.
/// - A tap during a scan focuses once on that point and holds it there; exposure and white balance stay locked.
enum CameraLock {
    static let centre = CGPoint(x: 0.5, y: 0.5)

    @discardableResult
    static func lock() -> Bool {
        configure { d in
            // Still settling (the scan started mid-refocus): finish focusing, then hold. Otherwise hold where it is.
            if d.isAdjustingFocus, d.isFocusModeSupported(.autoFocus) {
                d.focusMode = .autoFocus
            } else if d.isFocusModeSupported(.locked) {
                d.focusMode = .locked
            }
            if d.isExposureModeSupported(.locked) { d.exposureMode = .locked }
            if d.isWhiteBalanceModeSupported(.locked) { d.whiteBalanceMode = .locked }
        }
    }

    /// Tap to focus. `point` is sensor-normalized (0…1, top-left origin, the camera's landscape orientation),
    /// which is also AVCaptureDevice's point-of-interest space. Before a scan, focus and exposure keep
    /// following that point; during one (`holdExposure`), focus runs once there and holds, and exposure and
    /// white balance stay locked so every frame of the scan has the same brightness.
    @discardableResult
    static func focus(at point: CGPoint, holdExposure: Bool) -> Bool {
        configure { d in
            let mode: AVCaptureDevice.FocusMode = holdExposure ? .autoFocus : .continuousAutoFocus
            if d.isFocusPointOfInterestSupported, d.isFocusModeSupported(mode) {
                d.focusPointOfInterest = point
                d.focusMode = mode
            }
            if !holdExposure, d.isExposurePointOfInterestSupported, d.isExposureModeSupported(.continuousAutoExposure) {
                d.exposurePointOfInterest = point
                d.exposureMode = .continuousAutoExposure
            }
        }
    }

    /// Back to continuous autofocus and exposure. `resetPoint`: on the middle of the frame again (a new item).
    static func unlock(resetPoint: Bool = false) {
        configure { d in
            if resetPoint, d.isFocusPointOfInterestSupported { d.focusPointOfInterest = centre }
            if resetPoint, d.isExposurePointOfInterestSupported { d.exposurePointOfInterest = centre }
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
