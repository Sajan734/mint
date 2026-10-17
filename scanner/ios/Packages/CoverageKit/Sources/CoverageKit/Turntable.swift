import Foundation
import simd

/// Where a sheet of paper (or any flat rectangle the item sits on) lies on the table.
public struct PaperPose: Equatable, Sendable {
    public let centre: SIMD3<Float>  // on the table, metres (ARKit world)
    /// Direction of the long edges, radians about +Y (0 = +Z, π/2 = +X, same convention as
    /// `Dome.position`). A rectangle looks the same turned 180°, so this is only known mod π
    /// until `Turntable.unwrap` makes it continuous.
    public let yaw: Float
    public let long: Float           // edge lengths, metres
    public let short: Float

    public init(centre: SIMD3<Float>, yaw: Float, long: Float, short: Float) {
        self.centre = centre
        self.yaw = yaw
        self.long = long
        self.short = short
    }
}

/// The turntable method: the item sits on a sheet of paper and the user turns the paper. The
/// app follows the paper's corners, not the item, so it works whatever the item looks like
/// (glossy, plain, clear), and every frame is measured fresh, so nothing drifts.
public enum Turntable {
    /// Paper pose from its four corners on the table (any order). nil if they aren't a plausible
    /// sheet: opposite edges must match, corners must be near-square, and the sheet must be clearly
    /// longer than wide (a square is ambiguous by 90°).
    public static func pose(corners: [SIMD3<Float>], minAspect: Float = 1.12) -> PaperPose? {
        guard corners.count == 4 else { return nil }
        let c = corners.reduce(.zero, +) / 4
        // Order round the centre so consecutive corners share an edge.
        let ordered = corners.sorted { atan2($0.x - c.x, $0.z - c.z) < atan2($1.x - c.x, $1.z - c.z) }
        let e = (0..<4).map { i -> SIMD3<Float> in
            var d = ordered[(i + 1) % 4] - ordered[i]
            d.y = 0
            return d
        }
        let len = e.map(simd_length)
        guard len.allSatisfy({ $0 > 0.03 }) else { return nil }
        // Opposite edges within 12%; corners within ~12° of square.
        guard abs(len[0] - len[2]) <= 0.12 * max(len[0], len[2]),
              abs(len[1] - len[3]) <= 0.12 * max(len[1], len[3]) else { return nil }
        for i in 0..<4 {
            let cosA = abs(simd_dot(simd_normalize(e[i]), simd_normalize(e[(i + 1) % 4])))
            guard cosA < 0.21 else { return nil }
        }
        let a = (len[0] + len[2]) / 2, b = (len[1] + len[3]) / 2
        let longIs02 = a >= b
        guard max(a, b) / min(a, b) >= minAspect else { return nil }
        // Long-edge direction: average the two long edges (one reversed, they run opposite ways).
        let (p, q) = longIs02 ? (e[0], -e[2]) : (e[1], -e[3])
        let dir = simd_normalize(p) + simd_normalize(q)
        var yaw = atan2(dir.x, dir.z)
        yaw = yaw.truncatingRemainder(dividingBy: .pi)
        if yaw < 0 { yaw += .pi }
        return PaperPose(centre: c, yaw: yaw, long: max(a, b), short: min(a, b))
    }

    /// Makes a mod-π yaw continuous: the value ≡ `yaw` (mod π) closest to `previous`.
    /// Correct as long as the paper turns less than 90° between two reads.
    public static func unwrap(_ yaw: Float, near previous: Float) -> Float {
        let k = ((previous - yaw) / .pi).rounded()
        return yaw + k * .pi
    }

    /// World-space motion of the item from the start pose to now: a turn about the vertical through
    /// the paper's centre, plus any slide. Maps where an item point was at the start to where it is now.
    public static func motion(from start: PaperPose, startYaw: Float, to now: PaperPose, nowYaw: Float) -> simd_float4x4 {
        let r = simd_float4x4(simd_quatf(angle: nowYaw - startYaw, axis: [0, 1, 0]))
        var toOrigin = matrix_identity_float4x4
        toOrigin.columns.3 = SIMD4(-start.centre, 1)
        var toNow = matrix_identity_float4x4
        toNow.columns.3 = SIMD4(now.centre, 1)
        return toNow * r * toOrigin
    }

    /// The camera in the item's frame (the item frame = the world at the start of the scan):
    /// undo the item's motion. This is what reconstruction gets as `pose`.
    public static func cameraInItemFrame(camera: simd_float4x4, itemMotion: simd_float4x4) -> simd_float4x4 {
        itemMotion.inverse * camera
    }
}
