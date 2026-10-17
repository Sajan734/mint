import CoreVideo
import CoverageKit
import simd
import Vision

/// Reads the sheet of paper the item sits on (the turntable demo): how far it has turned, how high the
/// camera is above the item, and where the item is in the picture. The item is what the sheet encloses
/// (`ItemOnPaper`); nothing else is ever taken for the item. While the app waits for a product it also
/// reads QR codes (the website's `mint://` links). Runs on its own queue and drops frames while busy,
/// so it never slows the camera or the recording.
final class PaperReader {
    /// What one camera frame shows.
    struct Sight {
        let paper: SheetAngle.Reading?   // nil: no sheet, or its edges weren't clear (a hand over it)
        let elevation: Float?            // the camera above the item, radians
        let itemBox: CGRect?             // the item's bounding box, sensor-normalized (0…1, top-left origin)
        let code: String?                // a QR code's text, when asked to look for one
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
    private var busySince: TimeInterval?  // touched on the caller's queue only

    /// Call from one queue. `completion` runs on the main queue; then call `markIdle()` on the caller's queue.
    /// While looking for codes only the QR code is read: the paper isn't needed then, and the reads come faster.
    func process(_ pixelBuffer: CVPixelBuffer, camera: Camera, lookForCodes: Bool, completion: @escaping (Sight) -> Void) {
        // One read at a time. A read that never came back (it shouldn't happen) frees the reader after 2 s, so
        // the ring and the QR reader can't stop for good.
        if let since = busySince, camera.timestamp - since < 2 { return }
        busySince = camera.timestamp
        queue.async {
            let sight = lookForCodes
                ? Sight(paper: nil, elevation: nil, itemBox: nil, code: Self.qrCode(pixelBuffer), timestamp: camera.timestamp)
                : Self.read(pixelBuffer, camera: camera)
            DispatchQueue.main.async { completion(sight) }
        }
    }

    /// The first QR code in view, if any. The whole frame first; then the middle of it, which Vision reads at a
    /// higher effective resolution, for a code that is small in the frame (a small or far-away screen).
    static func qrCode(_ pixelBuffer: CVPixelBuffer) -> String? {
        for region in [CGRect(x: 0, y: 0, width: 1, height: 1), CGRect(x: 0.2, y: 0.2, width: 0.6, height: 0.6)] {
            let request = VNDetectBarcodesRequest()
            request.symbologies = [.qr]
            request.regionOfInterest = region
            try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right).perform([request])
            if let text = request.results?.compactMap(\.payloadStringValue).first { return text }
        }
        return nil
    }

    func markIdle() { busySince = nil }

    /// The sheet's angle and the camera's elevation above the item, from the camera image (sensor
    /// orientation) downsampled ×6 to 320 × 240.
    static func read(_ pixelBuffer: CVPixelBuffer, camera: Camera) -> Sight {
        let none = Sight(paper: nil, elevation: nil, itemBox: nil, code: nil, timestamp: camera.timestamp)
        guard let grid = grid(pixelBuffer, step: step), let r = ItemOnPaper.segment(grid),
              let frame = SheetAngle.HeadingFrame(cameraRotation: camera.rotation) else { return none }
        let k = SheetAngle.Intrinsics(arkit: camera.intrinsics, step: Float(step))
        let paper = SheetAngle.read(sheet: r.sheet, item: r.item, width: grid.width, height: grid.height, intrinsics: k, frame: frame)
        // Elevation above the item's middle (the mean of its pixels), and its bounding box.
        var sx: Float = 0, sy: Float = 0, n: Float = 0
        var x0 = grid.width, y0 = grid.height, x1 = -1, y1 = -1
        for y in 0..<grid.height {
            for x in 0..<grid.width where r.item[y * grid.width + x] != 0 {
                sx += Float(x); sy += Float(y); n += 1
                x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
            }
        }
        let w = CGFloat(grid.width), h = CGFloat(grid.height)
        let box = x1 >= x0 ? CGRect(x: CGFloat(x0) / w, y: CGFloat(y0) / h, width: CGFloat(x1 - x0 + 1) / w, height: CGFloat(y1 - y0 + 1) / h) : nil
        return Sight(paper: paper, elevation: n > 0 ? frame.elevation(sx / n, sy / n, k) : nil, itemBox: box, code: nil,
                     timestamp: camera.timestamp)
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
