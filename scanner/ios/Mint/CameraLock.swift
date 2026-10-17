import ARKit
import AVFoundation

/// Locks exposure, focus and white balance at scan start so every frame of the splat sees the same
/// colours (M1). Uses the AVCaptureDevice ARKit exposes for its primary camera (iOS 16+).
enum CameraLock {
    @discardableResult
    static func lock() -> Bool {
        configure { d in
            if d.isFocusModeSupported(.locked) { d.focusMode = .locked }
            if d.isExposureModeSupported(.locked) { d.exposureMode = .locked }
            if d.isWhiteBalanceModeSupported(.locked) { d.whiteBalanceMode = .locked }
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
