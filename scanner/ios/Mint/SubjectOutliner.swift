import CoreVideo
import CoverageKit
import Vision

/// The item's live outline for the overlay. On a sheet of paper (the demo setup) the item is what
/// the sheet encloses (`ItemOnPaper`); otherwise Vision's subject segmentation. Runs on its own
/// queue and drops frames while busy, so it never slows the camera or the recording.
final class SubjectOutliner {
    /// Outline points, sensor-normalized (0…1, origin top-left of the landscape camera image).
    typealias Outline = [CGPoint]

    private let queue = DispatchQueue(label: "mint.outline", qos: .userInitiated)
    private var busy = false  // touched on the caller's queue only

    /// Call from one queue. `completion` runs on the main queue; then call `markIdle()` on the caller's queue.
    func process(_ pixelBuffer: CVPixelBuffer, completion: @escaping (Outline?) -> Void) {
        guard !busy else { return }
        busy = true
        queue.async {
            let outline = Self.onPaper(pixelBuffer) ?? Self.visionSubject(pixelBuffer)
            DispatchQueue.main.async { completion(outline) }
        }
    }

    func markIdle() { busy = false }

    /// The item on the sheet of paper (the demo setup): what the sheet encloses. Works on the
    /// camera image directly (sensor orientation), downsampled ×6 to 320 × 240.
    static func onPaper(_ pixelBuffer: CVPixelBuffer) -> Outline? {
        guard let grid = grid(pixelBuffer, step: 6), let r = ItemOnPaper.segment(grid),
              let pts = Contours.outline(r.item, width: grid.width, height: grid.height) else { return nil }
        return pts  // already sensor-normalized: the grid is the sensor image
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

    /// No paper: Vision's subject segmentation ("lift subject"), preferring a compact instance near
    /// the middle that doesn't run off the frame (hands, knees and tables usually do).
    static func visionSubject(_ pixelBuffer: CVPixelBuffer) -> Outline? {
        // .right = the camera image as the phone is held (portrait); Vision answers in that upright space.
        let request = VNGenerateForegroundInstanceMaskRequest()
        guard (try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right).perform([request])) != nil,
              let obs = request.results?.first, !obs.allInstances.isEmpty else { return nil }
        let labels = obs.instanceMask
        CVPixelBufferLockBaseAddress(labels, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(labels, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(labels) else { return nil }
        let w = CVPixelBufferGetWidth(labels), h = CVPixelBufferGetHeight(labels), bpr = CVPixelBufferGetBytesPerRow(labels)
        let px = base.assumingMemoryBound(to: UInt8.self)

        var score: [UInt8: Double] = [:], edge: Set<UInt8> = []
        for y in stride(from: 0, to: h, by: 2) {
            for x in stride(from: 0, to: w, by: 2) {
                let l = px[y * bpr + x]
                guard l != 0 else { continue }
                if x < 3 || y < 3 || x >= w - 3 || y >= h - 3 { edge.insert(l) }
                let dx = Double(x) / Double(w) - 0.5, dy = Double(y) / Double(h) - 0.5
                score[l, default: 0] += 1 / (0.05 + dx * dx + dy * dy)
            }
        }
        let candidates = score.filter { !edge.contains($0.key) }
        guard let label = (candidates.isEmpty ? score : candidates).max(by: { $0.value < $1.value })?.key else { return nil }
        var mask = [UInt8](repeating: 0, count: w * h)
        for y in 0..<h { for x in 0..<w where px[y * bpr + x] == label { mask[y * w + x] = 1 } }
        guard let pts = Contours.outline(mask, width: w, height: h) else { return nil }
        // Upright top-left (x′, y′) → sensor (u = y′, v = 1 − x′).
        return pts.map { CGPoint(x: $0.y, y: 1 - $0.x) }
    }
}
