import Foundation
import simd

public enum Geometry {
    /// Angle (radians) between the rotation parts of two camera-to-world transforms.
    public static func rotationAngle(_ a: simd_float4x4, _ b: simd_float4x4) -> Float {
        let ra = simd_float3x3(a.columns.0.xyz, a.columns.1.xyz, a.columns.2.xyz)
        let rb = simd_float3x3(b.columns.0.xyz, b.columns.1.xyz, b.columns.2.xyz)
        let rel = ra.transpose * rb
        let trace = rel.columns.0.x + rel.columns.1.y + rel.columns.2.z
        return acos(max(-1, min(1, (trace - 1) / 2)))
    }

    /// Camera angular speed in rad/s between two poses `dt` seconds apart.
    public static func angularSpeed(from a: simd_float4x4, to b: simd_float4x4, dt: Double) -> Float {
        guard dt > 0 else { return 0 }
        return rotationAngle(a, b) / Float(dt)
    }

    /// Row-major nested arrays (the contract's mat4). simd is column-major, so this transposes.
    public static func rowMajor(_ m: simd_float4x4) -> [[Double]] {
        (0..<4).map { r in (0..<4).map { c in Double(m[c][r]) } }
    }

    public static func rowMajor(_ m: simd_float3x3) -> [[Double]] {
        (0..<3).map { r in (0..<3).map { c in Double(m[c][r]) } }
    }

    /// Scale pinhole intrinsics to a resized image (D2: K must match the saved pixels).
    /// Uses the pixel-corner convention ARKit uses, so cx, cy scale linearly with the image.
    public static func scaleIntrinsics(_ k: simd_float3x3, sx: Float, sy: Float) -> simd_float3x3 {
        var out = k
        out[0][0] *= sx  // fx
        out[1][1] *= sy  // fy
        out[2][0] *= sx  // cx
        out[2][1] *= sy  // cy
        return out
    }
}

extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
}

extension simd_float4x4 {
    public var translation: SIMD3<Float> { columns.3.xyz }
}
