import Foundation
import simd

/// A camera ray in ARKit world space.
public struct Ray: Sendable {
    public let origin: SIMD3<Float>
    public let direction: SIMD3<Float>  // unit length

    public init(origin: SIMD3<Float>, direction: SIMD3<Float>) {
        self.origin = origin
        self.direction = simd_normalize(direction)
    }

    /// Hit point with the horizontal plane y = `planeY`, if it's in front of the camera.
    public func hitHorizontalPlane(y planeY: Float) -> SIMD3<Float>? {
        guard abs(direction.y) > 1e-4 else { return nil }
        let t = (planeY - origin.y) / direction.y
        return t > 0 ? origin + t * direction : nil
    }

    /// Hit point with the plane through `point` with normal `normal`.
    public func hit(planeThrough point: SIMD3<Float>, normal: SIMD3<Float>) -> SIMD3<Float>? {
        let denom = simd_dot(direction, normal)
        guard abs(denom) > 1e-4 else { return nil }
        let t = simd_dot(point - origin, normal) / denom
        return t > 0 ? origin + t * direction : nil
    }
}

/// Where the item is and how big, in metres (ARKit world).
public struct ObjectEstimate: Equatable, Sendable {
    public let footprintCentre: SIMD3<Float>  // on the table, under the item's middle
    public let width: Float
    public let height: Float
    public let depth: Float

    public init(footprintCentre: SIMD3<Float>, width: Float, height: Float, depth: Float) {
        self.footprintCentre = footprintCentre
        self.width = width
        self.height = height
        self.depth = depth
    }

    /// Dome centre: half-way up the item, so the two rings look at its sides.
    public var centre: SIMD3<Float> { footprintCentre + SIMD3(0, height / 2, 0) }
    /// Bounding-sphere radius plus a little air, so the dome sits just outside the item.
    public var domeRadius: Float {
        max(0.08, 0.5 * (width * width + height * height + depth * depth).squareRoot() * 1.15 + 0.02)
    }
}

/// Sizes an item from one view: rays through its silhouette (from a segmentation mask) plus the
/// table plane it rests on. Depth can't be seen from one view, so the footprint is assumed square;
/// that only affects the dome's size and centre, not what gets captured.
public enum ObjectSizing {
    /// - Parameters:
    ///   - camera: camera position.
    ///   - contactRays: per mask column, the ray through the lowest mask pixel (where the item meets the table).
    ///   - silhouetteRays: rays through a sample of all mask pixels.
    ///   - planeY: height of the supporting horizontal plane.
    public static func estimate(
        camera: SIMD3<Float>, contactRays: [Ray], silhouetteRays: [Ray], planeY: Float
    ) -> ObjectEstimate? {
        let contacts = contactRays.compactMap { $0.hitHorizontalPlane(y: planeY) }
            .filter { simd_distance($0, camera) < 4 }
        guard contacts.count >= 3, silhouetteRays.count >= 10 else { return nil }

        let up = SIMD3<Float>(0, 1, 0)
        let front = SIMD3(median(contacts.map(\.x)), planeY, median(contacts.map(\.z)))
        var view = front - camera
        view.y = 0
        guard simd_length(view) > 1e-3 else { return nil }  // camera straight above: no horizontal view
        view = simd_normalize(view)
        let lateral = simd_normalize(simd_cross(view, up))

        // First pass: width from the contact edge, centre half a (square) footprint behind it.
        let contactLat = contacts.map { simd_dot($0 - front, lateral) }
        var width = percentile(contactLat, 0.95) - percentile(contactLat, 0.05)
        var centre = front + view * (width / 2)

        // Second pass: the silhouette on the vertical plane through that centre gives width and height.
        let pts = silhouetteRays.compactMap { $0.hit(planeThrough: centre, normal: view) }
        guard pts.count >= 10 else { return nil }
        let lat = pts.map { simd_dot($0 - centre, lateral) }
        let heights = pts.map { $0.y - planeY }
        let lo = percentile(lat, 0.03), hi = percentile(lat, 0.97)
        width = max(width, hi - lo, 0.02)
        let height = max(percentile(heights, 0.98), 0.02)
        centre += lateral * ((lo + hi) / 2)
        // Re-seat the centre half a footprint behind the front edge, using the final width.
        centre = SIMD3(centre.x, planeY, centre.z) + view * (width / 2 - simd_dot(centre - front, view))

        return ObjectEstimate(footprintCentre: centre, width: width, height: height, depth: width)
    }

    static func median(_ v: [Float]) -> Float { percentile(v, 0.5) }

    static func percentile(_ v: [Float], _ p: Float) -> Float {
        let s = v.sorted()
        let i = min(s.count - 1, max(0, Int((Float(s.count - 1) * p).rounded())))
        return s[i]
    }
}
