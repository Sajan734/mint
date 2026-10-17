import Foundation
import simd

/// A top-down map of the table around the item: the camera image resampled onto the table plane
/// with the ARKit pose. In it a sheet of paper is an undistorted rectangle of its true size, so its
/// angle and position can be read directly, whatever the camera angle.
public struct TableMap: Sendable {
    public let n: Int                 // n × n cells; row = z, column = x
    public let res: Float             // metres per cell
    public let origin: SIMD2<Float>   // (x, z) of cell (0, 0)'s corner
    public var luma: [UInt8]
    public var chroma: [UInt8]        // colour strength: ~0 for white/grey paper, higher for wood, skin
    public var valid: [UInt8]         // 1 = the camera sees this cell

    public init(centre: SIMD2<Float>, halfSize: Float, res: Float) {
        self.res = res
        n = Int((2 * halfSize / res).rounded())
        origin = centre - SIMD2(repeating: halfSize)
        luma = [UInt8](repeating: 0, count: n * n)
        chroma = [UInt8](repeating: 0, count: n * n)
        valid = [UInt8](repeating: 0, count: n * n)
    }

    /// Centre of cell (row, col) on the table, as (x, z).
    @inline(__always) public func cell(_ row: Int, _ col: Int) -> SIMD2<Float> {
        origin + (SIMD2(Float(col), Float(row)) + 0.5) * res
    }

    /// Fill from an image. `sample` gets a world point on the table and returns (luma, chroma), or
    /// nil if the camera doesn't see it.
    public mutating func fill(planeY: Float, sample: (SIMD3<Float>) -> (UInt8, UInt8)?) {
        for r in 0..<n {
            for c in 0..<n {
                let p = cell(r, c)
                let i = r * n + c
                if let (l, ch) = sample(SIMD3(p.x, planeY, p.y)) {
                    luma[i] = l; chroma[i] = ch; valid[i] = 1
                } else {
                    valid[i] = 0
                }
            }
        }
    }
}

/// One reading of the sheet in a `TableMap`.
public struct PaperReading: Sendable {
    /// Edge direction, as a yaw (0 = +Z, π/2 = +X), known only mod π/2 from one reading.
    public let angleMod90: Float
    /// Share of edge strength that agrees with `angleMod90` (straight edges vs hands, clutter).
    public let confidence: Float
    /// Extents of the sheet's boundary along u = angle direction and v = perpendicular: the
    /// outermost edge lines each way, and how many edge cells support each (a hand over one side
    /// cuts that side's support, so the other side + the known size gives the centre).
    public let uMin: Float, uMax: Float, vMin: Float, vMax: Float
    public let uMinSupport: Int, uMaxSupport: Int, vMinSupport: Int, vMaxSupport: Int
    public let areaM2: Float
}

public enum PaperDetector {
    /// Finds the sheet under the item (`near` = the item's (x, z)) and reads its edge angle and
    /// extents. Paper is told from the table by colour strength: on the first real turntable
    /// recording paper was ~2 and the beige table ~51 (HSV saturation); brightness alone lumped
    /// the table in and locked the angle onto the table edge.
    public static func read(_ map: TableMap, near: SIMD2<Float>, chromaMax: UInt8 = 10, lumaMin: UInt8 = 150) -> PaperReading? {
        let n = map.n
        var white = [UInt8](repeating: 0, count: n * n)
        for i in 0..<(n * n) where map.valid[i] != 0 && map.chroma[i] <= chromaMax && map.luma[i] >= lumaMin {
            white[i] = 1
        }
        white = close(white, n)

        // The white component with most cells within 12 cm of the item.
        let labels = components(white, n)
        let nearR2 = (0.12 / map.res) * (0.12 / map.res)
        let cRow = (near.y - map.origin.y) / map.res, cCol = (near.x - map.origin.x) / map.res
        var nearCount: [Int32: Int] = [:]
        for r in 0..<n {
            for c in 0..<n {
                let l = labels[r * n + c]
                guard l > 0 else { continue }
                let dr = Float(r) - cRow, dc = Float(c) - cCol
                if dr * dr + dc * dc < nearR2 { nearCount[l, default: 0] += 1 }
            }
        }
        guard let (label, _) = nearCount.max(by: { $0.value < $1.value }) else { return nil }
        var comp = [Float](repeating: 0, count: n * n)
        var area = 0
        for i in 0..<(n * n) where labels[i] == label { comp[i] = 1; area += 1 }
        let areaM2 = Float(area) * map.res * map.res
        guard areaM2 > 0.012 else { return nil }

        // Edges of the sheet: gradient of the (blurred) component, away from the view's border.
        comp = blur(blur(comp, n), n)
        let inner = erode(map.valid, n, radius: 4)
        var angles: [Float] = [], weights: [Float] = [], cells: [SIMD2<Float>] = [], grads: [SIMD2<Float>] = []
        for r in 1..<(n - 1) {
            for c in 1..<(n - 1) where inner[r * n + c] != 0 {
                let i = r * n + c
                let gx = (comp[i - n + 1] + 2 * comp[i + 1] + comp[i + n + 1]) - (comp[i - n - 1] + 2 * comp[i - 1] + comp[i + n - 1])
                let gz = (comp[i + n - 1] + 2 * comp[i + n] + comp[i + n + 1]) - (comp[i - n - 1] + 2 * comp[i - n] + comp[i - n + 1])
                let mag = (gx * gx + gz * gz).squareRoot()
                guard mag > 0.6 else { continue }
                // Gradient direction (x, z) → yaw (0 = +Z, π/2 = +X) → mod 90°.
                var a = atan2(gx, gz).truncatingRemainder(dividingBy: .pi / 2)
                if a < 0 { a += .pi / 2 }
                angles.append(a); weights.append(mag); cells.append(map.cell(r, c)); grads.append(SIMD2(gx, gz) / mag)
            }
        }
        guard angles.count >= 30 else { return nil }

        // Peak of a 1°-bin histogram (period 90°), smoothed, then a weighted circular mean near it.
        var hist = [Float](repeating: 0, count: 90)
        for (a, w) in zip(angles, weights) { hist[min(89, Int(a * 180 / .pi))] += w }
        var best = 0
        var bestScore: Float = -1
        for b in 0..<90 {
            var s: Float = 0
            for d in -2...2 { s += hist[(b + d + 90) % 90] }
            if s > bestScore { bestScore = s; best = b }
        }
        let peak = (Float(best) + 0.5) * .pi / 180
        func wrap(_ d: Float) -> Float {
            var x = d.truncatingRemainder(dividingBy: .pi / 2)
            if x > .pi / 4 { x -= .pi / 2 }
            if x < -.pi / 4 { x += .pi / 2 }
            return x
        }
        let tol: Float = 6 * .pi / 180
        var sw: Float = 0, sd: Float = 0, total: Float = 0
        for (a, w) in zip(angles, weights) {
            total += w
            let d = wrap(a - peak)
            if abs(d) < tol { sw += w; sd += w * d }
        }
        guard sw > 0 else { return nil }
        var angle = peak + sd / sw
        angle = angle.truncatingRemainder(dividingBy: .pi / 2)
        if angle < 0 { angle += .pi / 2 }

        // Split the edge cells that agree with `angle` into the sheet's four sides. A cell whose
        // gradient points along u lies on a side that bounds the u extent, and vice versa (classify
        // by the raw gradient: the mod-90° angle can't tell u from v).
        func sides(_ angle: Float) -> (u: SIMD2<Float>, v: SIMD2<Float>, pu: [(Float, SIMD2<Float>)], pv: [(Float, SIMD2<Float>)]) {
            let u = SIMD2<Float>(sin(angle), cos(angle))   // (x, z) of yaw `angle`
            let v = SIMD2<Float>(u.y, -u.x)
            var pu: [(Float, SIMD2<Float>)] = [], pv: [(Float, SIMD2<Float>)] = []
            for (k, a) in angles.enumerated() where abs(wrap(a - angle)) < tol {
                let p = cells[k], g = grads[k]
                if abs(simd_dot(g, u)) > abs(simd_dot(g, v)) { pu.append((simd_dot(p, u), p)) } else { pv.append((simd_dot(p, v), p)) }
            }
            return (u, v, pu, pv)
        }
        func edges(_ p: [(Float, SIMD2<Float>)]) -> (lo: Float, hi: Float, loPts: [SIMD2<Float>], hiPts: [SIMD2<Float>]) {
            let s = p.map(\.0).sorted()
            let lo = s[Int(Float(s.count - 1) * 0.02)], hi = s[Int(Float(s.count - 1) * 0.98)]
            let band = 2.5 * map.res
            return (lo, hi, p.filter { abs($0.0 - lo) < band }.map(\.1), p.filter { abs($0.0 - hi) < band }.map(\.1))
        }

        // Refine: fit a straight line through each side. Thresholded edges at a slight angle are
        // staircases whose flat steps bias the histogram (up to ~5° in tests); a line through a
        // whole side averages the staircase out.
        var sd0 = sides(angle)
        guard sd0.pu.count >= 6, sd0.pv.count >= 6 else { return nil }
        // Each side's band is chosen with the current angle, so a slightly wrong angle cuts the band
        // obliquely and pulls the fit back; a few rounds converge.
        for _ in 0..<4 {
            var sum = SIMD2<Float>.zero  // directions on a circle with period 90° (angle × 4)
            for group in [edges(sd0.pu).loPts, edges(sd0.pu).hiPts, edges(sd0.pv).loPts, edges(sd0.pv).hiPts] where group.count >= 12 {
                guard let dir = principalDirection(group) else { continue }
                var a = atan2(dir.x, dir.y).truncatingRemainder(dividingBy: .pi / 2)
                if a < 0 { a += .pi / 2 }
                sum += Float(group.count) * SIMD2(cos(4 * a), sin(4 * a))
            }
            guard simd_length(sum) > 0 else { break }
            var refined = atan2(sum.y, sum.x) / 4
            if refined < 0 { refined += .pi / 2 }
            guard abs(wrap(refined - angle)) < tol else { break }
            let moved = abs(wrap(refined - angle))
            angle = refined
            sd0 = sides(angle)
            guard sd0.pu.count >= 6, sd0.pv.count >= 6 else { return nil }
            if moved < 0.0005 { break }
        }
        guard sd0.pu.count >= 6, sd0.pv.count >= 6 else { return nil }
        let eu = edges(sd0.pu), ev = edges(sd0.pv)
        let eu2 = (lo: eu.lo, hi: eu.hi, loN: eu.loPts.count, hiN: eu.hiPts.count)
        let ev2 = (lo: ev.lo, hi: ev.hi, loN: ev.loPts.count, hiN: ev.hiPts.count)
        return PaperReading(angleMod90: angle, confidence: sw / total,
                            uMin: eu2.lo, uMax: eu2.hi, vMin: ev2.lo, vMax: ev2.hi,
                            uMinSupport: eu2.loN, uMaxSupport: eu2.hiN, vMinSupport: ev2.loN, vMaxSupport: ev2.hiN,
                            areaM2: areaM2)
    }

    /// Direction of the best-fit line through points (principal axis), or nil if degenerate.
    static func principalDirection(_ pts: [SIMD2<Float>]) -> SIMD2<Float>? {
        let n = Float(pts.count)
        let m = pts.reduce(.zero, +) / n
        var sxx: Float = 0, syy: Float = 0, sxy: Float = 0
        for p in pts { let d = p - m; sxx += d.x * d.x; syy += d.y * d.y; sxy += d.x * d.y }
        guard sxx + syy > 0 else { return nil }
        let t = 0.5 * atan2(2 * sxy, sxx - syy)
        return SIMD2(cos(t), sin(t))
    }

    // MARK: - Small image ops on n × n grids

    static func close(_ m: [UInt8], _ n: Int) -> [UInt8] { erodeBinary(dilate(m, n), n) }

    static func dilate(_ m: [UInt8], _ n: Int) -> [UInt8] {
        var out = m
        for r in 1..<(n - 1) {
            for c in 1..<(n - 1) where m[r * n + c] == 0 {
                if m[r * n + c - 1] != 0 || m[r * n + c + 1] != 0 || m[(r - 1) * n + c] != 0 || m[(r + 1) * n + c] != 0 {
                    out[r * n + c] = 1
                }
            }
        }
        return out
    }

    static func erodeBinary(_ m: [UInt8], _ n: Int) -> [UInt8] {
        var out = m
        for r in 1..<(n - 1) {
            for c in 1..<(n - 1) where m[r * n + c] != 0 {
                if m[r * n + c - 1] == 0 || m[r * n + c + 1] == 0 || m[(r - 1) * n + c] == 0 || m[(r + 1) * n + c] == 0 {
                    out[r * n + c] = 0
                }
            }
        }
        return out
    }

    static func erode(_ m: [UInt8], _ n: Int, radius: Int) -> [UInt8] {
        var out = m
        for _ in 0..<radius { out = erodeBinary(out, n) }
        return out
    }

    static func blur(_ m: [Float], _ n: Int) -> [Float] {
        var out = m
        for r in 1..<(n - 1) {
            for c in 1..<(n - 1) {
                let i = r * n + c
                out[i] = (m[i - n - 1] + m[i - n] + m[i - n + 1] + m[i - 1] + m[i] + m[i + 1] + m[i + n - 1] + m[i + n] + m[i + n + 1]) / 9
            }
        }
        return out
    }

    /// 4-connected component labels (0 = background).
    static func components(_ m: [UInt8], _ n: Int) -> [Int32] {
        var labels = [Int32](repeating: 0, count: n * n)
        var next: Int32 = 0
        var stack: [Int] = []
        for s in 0..<(n * n) where m[s] != 0 && labels[s] == 0 {
            next += 1
            labels[s] = next
            stack.append(s)
            while let i = stack.popLast() {
                let r = i / n, c = i % n
                if r > 0, m[i - n] != 0, labels[i - n] == 0 { labels[i - n] = next; stack.append(i - n) }
                if r < n - 1, m[i + n] != 0, labels[i + n] == 0 { labels[i + n] = next; stack.append(i + n) }
                if c > 0, m[i - 1] != 0, labels[i - 1] == 0 { labels[i - 1] = next; stack.append(i - 1) }
                if c < n - 1, m[i + 1] != 0, labels[i + 1] == 0 { labels[i + 1] = next; stack.append(i + 1) }
            }
        }
        return labels
    }
}

/// Follows the sheet through a scan: makes the angle continuous (one reading only knows it mod 90°),
/// learns which edges are the long ones, learns the sheet's size, and gives its pose every reading.
public struct PaperFollower: Sendable {
    public private(set) var yaw: Float?           // continuous, long-edge direction
    public private(set) var long: Float = 0, short: Float = 0
    public private(set) var start: PaperPose?
    public private(set) var startYaw: Float = 0
    public private(set) var current: PaperPose?

    public init() {}

    public var isTracking: Bool { yaw != nil }

    /// Keep what's known about the sheet (size, which edges are long, continuous angle) but make the
    /// next reading the new start: the scan's item frame begins at Start, not when aiming began.
    public mutating func restart() {
        start = nil
        current = nil
    }

    /// Total turn since the start, radians.
    public var turned: Float { (yaw ?? startYaw) - startYaw }

    /// Takes a reading; returns the sheet's pose (centre at y = 0), or nil if the reading isn't trustworthy.
    @discardableResult
    public mutating func update(_ r: PaperReading, minConfidence: Float = 0.3) -> PaperPose? {
        guard r.confidence >= minConfidence else { return nil }
        let eu = r.uMax - r.uMin, ev = r.vMax - r.vMin
        if yaw == nil {
            // The first reading must show the whole sheet clearly: both sizes plausible and distinct.
            guard min(eu, ev) > 0.1, max(eu, ev) < 0.5, max(eu, ev) / min(eu, ev) > 1.12 else { return nil }
            yaw = eu >= ev ? r.angleMod90 : r.angleMod90 + .pi / 2
            long = max(eu, ev); short = min(eu, ev)
        } else {
            // The value ≡ angle (mod 90°) closest to the last one: right while the sheet turns < 45° per reading.
            let k = ((yaw! - r.angleMod90) / (.pi / 2)).rounded()
            yaw = r.angleMod90 + k * (.pi / 2)
        }
        // Is the long edge along u (the reading's angle) or v? Depends on how many quarter turns away.
        let quarter = Int(((yaw! - r.angleMod90) / (.pi / 2)).rounded())
        let longAlongU = quarter % 2 == 0
        let (lenU, lenV) = longAlongU ? (long, short) : (short, long)
        // Centre along each axis: midpoint if both edges are seen; else the better-supported edge
        // plus half the known size (a hand over one side).
        func mid(_ lo: Float, _ hi: Float, _ loN: Int, _ hiN: Int, _ len: Float) -> Float {
            if abs((hi - lo) - len) < 0.015 { return (lo + hi) / 2 }
            return loN >= hiN ? lo + len / 2 : hi - len / 2
        }
        let cu = mid(r.uMin, r.uMax, r.uMinSupport, r.uMaxSupport, lenU)
        let cv = mid(r.vMin, r.vMax, r.vMinSupport, r.vMaxSupport, lenV)
        let u = SIMD2<Float>(sin(r.angleMod90), cos(r.angleMod90)), v = SIMD2<Float>(u.y, -u.x)
        let c2 = u * cu + v * cv
        // Refine the size slowly from clean, fully visible readings.
        if abs(eu - lenU) < 0.015 && abs(ev - lenV) < 0.015 {
            if longAlongU {
                long += (eu - long) * 0.1; short += (ev - short) * 0.1
            } else {
                long += (ev - long) * 0.1; short += (eu - short) * 0.1
            }
        }
        let pose = PaperPose(centre: SIMD3(c2.x, 0, c2.y), yaw: yaw!, long: long, short: short)
        if start == nil { start = pose; startYaw = yaw! }
        current = pose
        return pose
    }

    /// The item's world motion since the start (see `Turntable.motion`), at table height `planeY`.
    public func motion(planeY: Float) -> simd_float4x4? {
        guard let s = start, let c = current, let y = yaw else { return nil }
        let s3 = PaperPose(centre: SIMD3(s.centre.x, planeY, s.centre.z), yaw: s.yaw, long: s.long, short: s.short)
        let c3 = PaperPose(centre: SIMD3(c.centre.x, planeY, c.centre.z), yaw: c.yaw, long: c.long, short: c.short)
        return Turntable.motion(from: s3, startYaw: startYaw, to: c3, nowYaw: y)
    }
}
