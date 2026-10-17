import Foundation
import simd

/// One cell of the capture dome: an azimuth bin × an elevation band around the tap anchor.
public struct SegmentID: Hashable, Comparable, Sendable {
    public let az: Int  // 0 ..< Dome.azimuthCount
    public let el: Int  // 0 ..< Dome.bands.count

    public init(az: Int, el: Int) {
        self.az = az
        self.el = el
    }

    /// Contract name, e.g. "az090_el20": azimuth bin start in degrees, band centre in degrees.
    public var name: String {
        String(format: "az%03d_el%02d", az * Dome.azimuthStepDeg, Dome.bands[el].centreDeg)
    }

    public static func < (a: SegmentID, b: SegmentID) -> Bool {
        (a.el, a.az) < (b.el, b.az)
    }
}

/// Where the camera is relative to the anchor, in dome terms.
public struct DomePosition: Equatable, Sendable {
    public let azimuthDeg: Float    // [0, 360), 0 = ARKit world +Z, increases when the user walks to their right
    public let elevationDeg: Float  // 0 = level with the anchor, 90 = straight above
    public let distanceM: Float
}

public enum Dome {
    public struct Band: Sendable {
        public let minDeg: Float
        public let maxDeg: Float
        public let centreDeg: Int
    }

    public static let azimuthCount = 12
    public static let azimuthStepDeg = 360 / azimuthCount
    /// Two heights (ARCHITECTURE.md §3 step 1): low ring ~20°, high ring ~50°.
    public static let bands: [Band] = [
        Band(minDeg: 5, maxDeg: 35, centreDeg: 20),
        Band(minDeg: 35, maxDeg: 70, centreDeg: 50),
    ]
    public static var segmentCount: Int { azimuthCount * bands.count }
    public static var allSegments: [SegmentID] {
        bands.indices.flatMap { el in (0..<azimuthCount).map { SegmentID(az: $0, el: el) } }
    }

    /// ≥ 90% coverage finishes the scan: 22 of 24 segments.
    public static let completeFraction: Double = 0.9
    public static var segmentsToComplete: Int { Int((Double(segmentCount) * completeFraction).rounded(.up)) }

    /// Camera position (ARKit world) relative to the anchor (ARKit world, +Y up).
    public static func position(camera: SIMD3<Float>, anchor: SIMD3<Float>) -> DomePosition {
        let d = camera - anchor
        let horizontal = (d.x * d.x + d.z * d.z).squareRoot()
        var az = atan2(d.x, d.z) * 180 / .pi
        if az < 0 { az += 360 }
        if az >= 360 { az -= 360 }
        let el = atan2(d.y, horizontal) * 180 / .pi
        return DomePosition(azimuthDeg: az, elevationDeg: el, distanceM: simd_length(d))
    }

    /// The segment the camera is looking from, or nil if it's outside both bands.
    public static func segment(for p: DomePosition) -> SegmentID? {
        guard let el = bands.firstIndex(where: { p.elevationDeg >= $0.minDeg && p.elevationDeg < $0.maxDeg }) else {
            return nil
        }
        let az = min(Int(p.azimuthDeg) / azimuthStepDeg, azimuthCount - 1)
        return SegmentID(az: az, el: el)
    }
}
