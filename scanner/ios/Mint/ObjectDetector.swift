import ARKit
import CoverageKit
import Vision

/// Finds the item in view with Vision's subject segmentation and turns its mask into camera rays
/// (world space) for `ObjectSizing`. Runs on its own queue and drops requests while busy, so it
/// never stalls the AR frame loop.
final class ObjectDetector {
    struct Input {
        let pixelBuffer: CVPixelBuffer
        let cameraTransform: simd_float4x4
        let intrinsics: simd_float3x3
        let imageSize: CGSize           // sensor pixels, landscape (1920×1440)
        let preferredPoint: CGPoint     // upright (portrait) normalized image point to pick the instance at
        let cloud: [SIMD3<Float>]       // ARKit feature points (world), accumulated while aiming
    }

    struct Result {
        /// Item bounds in upright (portrait) normalized image coordinates, origin top-left.
        let boundsUpright: CGRect
        let camera: SIMD3<Float>
        let contactRays: [Ray]
        let silhouetteRays: [Ray]
        /// ARKit feature points that project inside the item's mask (not on its edge), in front of
        /// the camera: ARKit's own 3D measurements of the item (plus some table bleed).
        let objectPoints: [SIMD3<Float>]
        let cloudSize: Int
        /// Share of the image the item covers.
        let areaFraction: Double
    }

    private let queue = DispatchQueue(label: "mint.detect", qos: .userInitiated)
    private var busy = false  // touched on the caller's queue only

    /// Call from one queue (the frame queue). `completion` runs on the main queue; afterwards the
    /// caller must call `markIdle()` on its own queue to let the next request through.
    func detect(_ input: Input, completion: @escaping (Result?) -> Void) {
        guard !busy else { return }
        busy = true
        queue.async {
            let result = Self.run(input)
            DispatchQueue.main.async { completion(result) }
        }
    }

    func markIdle() { busy = false }

    private static func run(_ input: Input) -> Result? {
        // .right = the capturedImage rotated for a portrait phone. Vision then reports the mask in
        // upright space; mapping back to sensor pixels is u = v′, v = 1 − u′ (checked on macOS).
        let request = VNGenerateForegroundInstanceMaskRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: input.pixelBuffer, orientation: .right)
        guard (try? handler.perform([request])) != nil,
              let obs = request.results?.first, !obs.allInstances.isEmpty else { return nil }

        let mask = obs.instanceMask
        CVPixelBufferLockBaseAddress(mask, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(mask, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(mask) else { return nil }
        let mw = CVPixelBufferGetWidth(mask), mh = CVPixelBufferGetHeight(mask)
        let bpr = CVPixelBufferGetBytesPerRow(mask)
        let px = base.assumingMemoryBound(to: UInt8.self)

        guard let label = pickInstance(px, mw, mh, bpr, preferred: input.preferredPoint) else { return nil }

        // One pass over the mask: bounds, a sparse sample of silhouette pixels, the lowest pixel per column.
        var minX = mw, maxX = -1, minY = mh, maxY = -1, count = 0
        var lowestInColumn = [Int](repeating: -1, count: mw)
        var samples: [(Int, Int)] = []
        for y in 0..<mh {
            let row = px + y * bpr
            for x in 0..<mw where row[x] == label {
                count += 1
                minX = min(minX, x); maxX = max(maxX, x)
                minY = min(minY, y); maxY = max(maxY, y)
                if y > lowestInColumn[x] { lowestInColumn[x] = y }
                if x % 3 == 0 && y % 3 == 0 { samples.append((x, y)) }
            }
        }
        guard count > 50 else { return nil }

        let toRay = rayMaker(input, maskWidth: mw, maskHeight: mh)
        let contact = lowestInColumn.enumerated().compactMap { x, y in y >= 0 && x % 2 == 0 ? toRay(x, y) : nil }
        let silhouette = samples.map { toRay($0.0, $0.1) }

        // ARKit's points that land inside the mask, at least 2 mask pixels from its edge.
        func on(_ x: Int, _ y: Int) -> Bool { x >= 0 && y >= 0 && x < mw && y < mh && px[y * bpr + x] == label }
        let worldToCamera = input.cameraTransform.inverse
        let k = input.intrinsics
        let sw = Float(input.imageSize.width), sh = Float(input.imageSize.height)
        let objectPoints = input.cloud.filter { p in
            let c = worldToCamera * SIMD4(p, 1)
            guard c.z < -0.02 else { return false }  // in front of the camera (ARKit looks down −z)
            let u = k[0][0] * c.x / -c.z + k[2][0]    // sensor pixels
            let v = k[1][1] * -c.y / -c.z + k[2][1]
            // sensor → upright normalized (inverse of u = v′·W, v = (1 − u′)·H) → mask pixel
            let mx = Int((1 - v / sh) * Float(mw)), my = Int(u / sw * Float(mh))
            return on(mx, my) && on(mx - 2, my) && on(mx + 2, my) && on(mx, my - 2) && on(mx, my + 2)
        }

        return Result(
            boundsUpright: CGRect(x: Double(minX) / Double(mw), y: Double(minY) / Double(mh),
                                  width: Double(maxX - minX + 1) / Double(mw), height: Double(maxY - minY + 1) / Double(mh)),
            camera: input.cameraTransform.translation,
            contactRays: contact,
            silhouetteRays: silhouette,
            objectPoints: objectPoints,
            cloudSize: input.cloud.count,
            areaFraction: Double(count) / Double(mw * mh)
        )
    }

    /// The instance under the preferred point, else the biggest one nearest it.
    private static func pickInstance(_ px: UnsafeMutablePointer<UInt8>, _ w: Int, _ h: Int, _ bpr: Int,
                                     preferred: CGPoint) -> UInt8? {
        let px0 = min(w - 1, max(0, Int(preferred.x * Double(w))))
        let py0 = min(h - 1, max(0, Int(preferred.y * Double(h))))
        let under = px[py0 * bpr + px0]
        if under != 0 { return under }

        var score: [UInt8: Double] = [:]
        for y in stride(from: 0, to: h, by: 4) {
            for x in stride(from: 0, to: w, by: 4) {
                let l = px[y * bpr + x]
                guard l != 0 else { continue }
                let dx = Double(x) / Double(w) - preferred.x, dy = Double(y) / Double(h) - preferred.y
                score[l, default: 0] += 1 / (0.05 + dx * dx + dy * dy)  // area, weighted towards the point
            }
        }
        return score.max { $0.value < $1.value }?.key
    }

    /// Mask pixel (upright space) → world ray through that pixel's centre.
    private static func rayMaker(_ input: Input, maskWidth mw: Int, maskHeight mh: Int) -> (Int, Int) -> Ray {
        let k = input.intrinsics
        let fx = k[0][0], fy = k[1][1], cx = k[2][0], cy = k[2][1]
        let sw = Float(input.imageSize.width), sh = Float(input.imageSize.height)
        let t = input.cameraTransform
        let r = simd_float3x3(SIMD3(t.columns.0.x, t.columns.0.y, t.columns.0.z),
                              SIMD3(t.columns.1.x, t.columns.1.y, t.columns.1.z),
                              SIMD3(t.columns.2.x, t.columns.2.y, t.columns.2.z))
        let origin = t.translation
        return { x, y in
            let u1 = (Float(x) + 0.5) / Float(mw), v1 = (Float(y) + 0.5) / Float(mh)  // upright normalized
            let u = v1 * sw, v = (1 - u1) * sh                                          // sensor pixels
            // ARKit camera axes: +x right, +y up, looking down −z.
            let d = SIMD3((u - cx) / fx, -(v - cy) / fy, -1)
            return Ray(origin: origin, direction: r * d)
        }
    }
}
