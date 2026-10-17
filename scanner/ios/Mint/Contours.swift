import CoreVideo
import Vision

/// Traces the outer outline of a binary mask with Vision's contour detector.
enum Contours {
    /// `mask`: w × h, non-zero = inside, row 0 at the top. Returns the largest outer contour as
    /// points normalized to the mask (0…1, origin top-left), simplified, or nil.
    static func outline(_ mask: [UInt8], width w: Int, height h: Int) -> [CGPoint]? {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(kCFAllocatorDefault, w, h, kCVPixelFormatType_OneComponent8, nil, &buffer)
        guard let buffer else { return nil }
        CVPixelBufferLockBaseAddress(buffer, [])
        if let base = CVPixelBufferGetBaseAddress(buffer) {
            let bpr = CVPixelBufferGetBytesPerRow(buffer)
            let p = base.assumingMemoryBound(to: UInt8.self)
            for y in 0..<h { for x in 0..<w { p[y * bpr + x] = mask[y * w + x] != 0 ? 255 : 0 } }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])

        let request = VNDetectContoursRequest()
        request.detectsDarkOnLight = false   // white shape on black
        request.contrastAdjustment = 1
        request.maximumImageDimension = max(w, h)
        guard (try? VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .up).perform([request])) != nil,
              let result = request.results?.first,
              let outer = result.topLevelContours.max(by: { $0.pointCount < $1.pointCount }),
              outer.pointCount >= 12 else { return nil }
        let shape = (try? outer.polygonApproximation(epsilon: 0.003)) ?? outer
        // Vision's normalized points have their origin at the bottom-left.
        return shape.normalizedPoints.map { CGPoint(x: CGFloat($0.x), y: 1 - CGFloat($0.y)) }
    }
}
