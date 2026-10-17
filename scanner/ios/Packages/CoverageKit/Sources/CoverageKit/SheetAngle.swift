import Foundation
import simd

/// How far the sheet of paper has turned, read straight off the camera image (the turntable demo:
/// the phone stays still, the paper turns). Needs only the sheet's mask (`ItemOnPaper`) and which
/// way is down (the camera's rotation): no table plane, no item position, no lock.
///
/// The sheet's outline is projected onto a horizontal plane under the camera. The plane's height
/// is unknown, but angles on it don't depend on the height, so the straight edges give the sheet's
/// angle (mod 90°). Angles are measured relative to the camera's heading, so if ARKit's world
/// slowly turns (the turning paper fills much of the view), it cancels out.
public enum SheetAngle {
    public struct Reading: Sendable, Equatable {
        /// Sheet edge direction, radians in [0, π/2), relative to the camera's heading
        /// (0 = pointing straight away from the camera, π/2 = to its right).
        public let angleMod90: Float
        /// Share of the outline that agrees with `angleMod90` (straight edges vs hands, clutter).
        public let confidence: Float
        /// Outline samples used.
        public let samples: Int
    }

    /// Pinhole intrinsics in the mask's own pixel units.
    public struct Intrinsics: Sendable {
        public let fx: Float, fy: Float, cx: Float, cy: Float
        public init(fx: Float, fy: Float, cx: Float, cy: Float) {
            self.fx = fx; self.fy = fy; self.cx = cx; self.cy = cy
        }

        /// ARKit's K (column-major, as `ARCamera.intrinsics`) for an image `step` times larger than the mask.
        public init(arkit k: simd_float3x3, step: Float) {
            self.init(fx: k[0][0] / step, fy: k[1][1] / step, cx: k[2][0] / step, cy: k[2][1] / step)
        }
    }

    /// A horizontal frame that turns with the camera: +Y up (gravity), −Z the camera's heading.
    public struct HeadingFrame: Sendable {
        public let right: SIMD3<Float>, up: SIMD3<Float>, back: SIMD3<Float>
        let rotation: simd_float3x3   // camera → world (ARKit camera axes: +x right, +y up, looks along −z)

        public init?(cameraRotation r: simd_float3x3) {
            let forward = r * SIMD3(0, 0, -1)
            var h = SIMD3(forward.x, 0, forward.z)
            if simd_length(h) < 0.1 {   // looking straight down: the image's top edge gives the heading
                let top = r * SIMD3(0, 1, 0)
                h = SIMD3(top.x, 0, top.z)
            }
            guard simd_length(h) > 1e-4 else { return nil }
            up = SIMD3(0, 1, 0)
            back = -simd_normalize(h)
            right = simd_cross(up, back)
            rotation = r
        }

        /// Image pixel → viewing ray in this frame (x right, y up, z towards the camera's back).
        func ray(_ u: Float, _ v: Float, _ k: Intrinsics) -> SIMD3<Float> {
            let d = rotation * SIMD3((u - k.cx) / k.fx, -(v - k.cy) / k.fy, -1)
            return SIMD3(simd_dot(d, right), simd_dot(d, up), simd_dot(d, back))
        }

        /// Where the ray hits the plane one unit below the camera, as (x, z); nil near the horizon.
        func onPlane(_ u: Float, _ v: Float, _ k: Intrinsics) -> SIMD2<Float>? {
            let d = ray(u, v, k)
            let len = simd_length(d)
            guard d.y < -0.08 * len else { return nil }
            return SIMD2(d.x, d.z) / -d.y
        }

        /// Elevation of the camera above an image point (radians; π/2 = looking straight down at it).
        public func elevation(_ u: Float, _ v: Float, _ k: Intrinsics) -> Float {
            let d = ray(u, v, k)
            return asin(max(-1, min(1, -d.y / simd_length(d))))
        }
    }

    /// Reads the sheet's angle. `sheet` / `item`: w × h masks (1 = inside, `ItemOnPaper.Result`).
    public static func read(sheet: [UInt8], item: [UInt8], width w: Int, height h: Int,
                            intrinsics k: Intrinsics, frame: HeadingFrame) -> Reading? {
        let n = w * h
        guard sheet.count == n, item.count == n, w > 8, h > 8 else { return nil }

        // Soft edges: a thresholded mask is a staircase; blurring twice makes the gradient follow the true edge.
        var m = [Float](repeating: 0, count: n)
        for i in 0..<n where sheet[i] != 0 { m[i] = 1 }
        m = boxBlur(boxBlur(m, w, h), w, h)
        // Edges against the item turn with the paper too, but a boxy item's sides aren't the sheet's angle.
        var nearItem = item
        for _ in 0..<3 { nearItem = ItemOnPaper.dilate(nearItem, w, h) }

        let margin = 4   // the image border cuts the sheet along straight lines that aren't its edges
        var angles: [Float] = []
        angles.reserveCapacity(2048)
        for y in margin..<(h - margin) {
            for x in margin..<(w - margin) {
                let i = y * w + x
                guard m[i] > 0.1, m[i] < 0.9, nearItem[i] == 0 else { continue }
                let gx = (m[i - w + 1] + 2 * m[i + 1] + m[i + w + 1]) - (m[i - w - 1] + 2 * m[i - 1] + m[i + w - 1])
                let gy = (m[i + w - 1] + 2 * m[i + w] + m[i + w + 1]) - (m[i - w - 1] + 2 * m[i - w] + m[i - w + 1])
                let mag = (gx * gx + gy * gy).squareRoot()
                guard mag > 0.5 else { continue }
                // Edge tangent in the image → on the plane.
                let tx = -gy / mag, ty = gx / mag
                let u = Float(x), v = Float(y)
                guard let p0 = frame.onPlane(u - tx, v - ty, k), let p1 = frame.onPlane(u + tx, v + ty, k) else { continue }
                let t = p1 - p0
                guard simd_length(t) > 1e-6 else { continue }
                var a = atan2(t.x, -t.y).truncatingRemainder(dividingBy: .pi / 2)   // 0 = away from the camera
                if a < 0 { a += .pi / 2 }
                angles.append(a)
            }
        }
        guard angles.count >= 40 else { return nil }

        // Peak of a 1° histogram with period 90°, then a circular mean of the samples near it.
        var hist = [Float](repeating: 0, count: 90)
        for a in angles { hist[min(89, Int(a * 180 / .pi))] += 1 }
        var best = 0
        var bestScore: Float = -1
        for b in 0..<90 {
            var s: Float = 0
            for d in -2...2 { s += hist[(b + d + 90) % 90] }
            if s > bestScore { bestScore = s; best = b }
        }
        let peak = (Float(best) + 0.5) * .pi / 180
        let tol: Float = 6 * .pi / 180
        var sum = SIMD2<Float>.zero, agree = 0
        for a in angles where abs(wrap90(a - peak)) < tol {
            sum += SIMD2(cos(4 * a), sin(4 * a))   // period 90° → ×4 on the circle
            agree += 1
        }
        var angle = atan2(sum.y, sum.x) / 4
        if angle < 0 { angle += .pi / 2 }
        return Reading(angleMod90: angle, confidence: Float(agree) / Float(angles.count), samples: angles.count)
    }

    /// The equivalent of `d` in (−45°, 45°].
    public static func wrap90(_ d: Float) -> Float {
        var x = d.truncatingRemainder(dividingBy: .pi / 2)
        if x > .pi / 4 { x -= .pi / 2 }
        if x <= -.pi / 4 { x += .pi / 2 }
        return x
    }

    static func boxBlur(_ m: [Float], _ w: Int, _ h: Int) -> [Float] {
        var out = m
        for y in 1..<(h - 1) {
            for x in 1..<(w - 1) {
                let i = y * w + x
                out[i] = (m[i - w - 1] + m[i - w] + m[i - w + 1] + m[i - 1] + m[i] + m[i + 1] + m[i + w - 1] + m[i + w] + m[i + w + 1]) / 9
            }
        }
        return out
    }
}

/// Follows the sheet's angle through a scan: one reading only knows it mod 90°, so each new one is
/// taken as the equivalent closest to the last (right while the paper turns < 45° between reads;
/// at a 10 s lap and ~8 reads/s it turns ~5°). Readings that disagree with the motion so far are
/// dropped (a hand's edge briefly outvoting the sheet's).
public struct PaperTurn: Sendable {
    public private(set) var angle: Float?      // continuous, radians
    public private(set) var start: Float = 0
    private var lastTime: Double = 0
    private var rejects = 0

    public init() {}

    /// Total turn since `restart()` (or the first reading), radians. Positive = the paper turned
    /// from the camera's heading towards its right, seen from above (clockwise).
    public var turned: Float { (angle ?? start) - start }

    public mutating func restart() { start = angle ?? 0 }

    /// Returns true if the reading was used.
    @discardableResult
    public mutating func update(_ r: SheetAngle.Reading, time: Double, minConfidence: Float = 0.3,
                                maxRate: Float = 2.5 /* rad/s ≈ a lap in 2.5 s, 4× the demo pace */) -> Bool {
        guard r.confidence >= minConfidence else { return false }
        guard let prev = angle else {
            angle = r.angleMod90
            start = r.angleMod90
            lastTime = time
            return true
        }
        let d = SheetAngle.wrap90(r.angleMod90 - prev)
        let dt = Float(max(0, time - lastTime))
        // A few rejections in a row means the paper really moved while we weren't watching: accept.
        guard abs(d) <= maxRate * dt + 0.1 || rejects >= 3 else {
            rejects += 1
            return false
        }
        rejects = 0
        angle = prev + d
        lastTime = time
        return true
    }
}
