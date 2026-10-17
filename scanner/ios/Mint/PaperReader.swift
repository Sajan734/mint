import CoreVideo
import CoverageKit
import simd

/// Reads the sheet of paper the item sits on (the turntable demo): how far it has turned, and how
/// high the camera is above the item. The item is what the sheet encloses (`ItemOnPaper`). Runs on
/// its own queue and drops frames while busy, so it never slows the camera or the recording.
final class PaperReader {
    /// What one camera frame shows.
    struct Sight {
        let paper: SheetAngle.Reading?   // nil: no sheet, or its edges weren't clear (a hand over it)
        let elevation: Float?            // the camera above the item, radians
        let timestamp: TimeInterval
    }

    /// The camera for one frame, copied out of the ARFrame (which mustn't be held).
    struct Camera {
        let rotation: simd_float3x3      // camera → world, ARKit camera axes
        let intrinsics: simd_float3x3    // sensor pixels
        let timestamp: TimeInterval
    }

    static let step = 6   // 1920 × 1440 sensor → 320 × 240 grid

    private let queue = DispatchQueue(label: "mint.paper", qos: .userInitiated)
    private var busy = false  // touched on the caller's queue only

    /// Call from one queue. `completion` runs on the main queue; then call `markIdle()` on the caller's queue.
    func process(_ pixelBuffer: CVPixelBuffer, camera: Camera, completion: @escaping (Sight) -> Void) {
        guard !busy else { return }
        busy = true
        queue.async {
            let sight = Self.read(pixelBuffer, camera: camera)
            DispatchQueue.main.async { completion(sight) }
        }
    }

    func markIdle() { busy = false }

    /// The sheet's angle and the camera's elevation above the item, from the camera image (sensor
    /// orientation) downsampled ×6 to 320 × 240.
    static func read(_ pixelBuffer: CVPixelBuffer, camera: Camera) -> Sight {
        let none = Sight(paper: nil, elevation: nil, timestamp: camera.timestamp)
        guard let grid = grid(pixelBuffer, step: step), let r = ItemOnPaper.segment(grid),
              let frame = SheetAngle.HeadingFrame(cameraRotation: camera.rotation) else { return none }
        let k = SheetAngle.Intrinsics(arkit: camera.intrinsics, step: Float(step))
        let paper = SheetAngle.read(sheet: r.sheet, item: r.item, width: grid.width, height: grid.height, intrinsics: k, frame: frame)
        // Elevation above the item's middle (the mean of its pixels).
        var sx: Float = 0, sy: Float = 0, n: Float = 0
        for y in 0..<grid.height {
            for x in 0..<grid.width where r.item[y * grid.width + x] != 0 { sx += Float(x); sy += Float(y); n += 1 }
        }
        return Sight(paper: paper, elevation: n > 0 ? frame.elevation(sx / n, sy / n, k) : nil, timestamp: camera.timestamp)
    }

    /// Brightness + colour strength from the YCbCr camera image, every `step`-th pixel.
    static func grid(_ buffer: CVPixelBuffer, step: Int) -> ImageGrid? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(buffer) >= 2,
              let yb = CVPixelBufferGetBaseAddressOfPlane(buffer, 0), let cb = CVPixelBufferGetBaseAddressOfPlane(buffer, 1) else { return nil }
        let yp = yb.assumingMemoryBound(to: UInt8.self), cp = cb.assumingMemoryBound(to: UInt8.self)
        let yBpr = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0), cBpr = CVPixelBufferGetBytesPerRowOfPlane(buffer, 1)
        let w = CVPixelBufferGetWidthOfPlane(buffer, 0) / step, h = CVPixelBufferGetHeightOfPlane(buffer, 0) / step
        var luma = [UInt8](repeating: 0, count: w * h), chroma = [UInt8](repeating: 0, count: w * h)
        for gy in 0..<h {
            for gx in 0..<w {
                let x = gx * step, y = gy * step
                let l = Float(yp[y * yBpr + x])
                let ci = (y / 2) * cBpr + (x / 2) * 2
                let u = Float(cp[ci]) - 128, v = Float(cp[ci + 1]) - 128
                let r = l + 1.402 * v, g = l - 0.344 * u - 0.714 * v, b = l + 1.772 * u
                luma[gy * w + gx] = UInt8(max(0, min(255, l)))
                chroma[gy * w + gx] = UInt8(max(0, min(255, max(r, g, b) - min(r, g, b))))
            }
        }
        return ImageGrid(width: w, height: h, luma: luma, chroma: chroma)
    }
}
