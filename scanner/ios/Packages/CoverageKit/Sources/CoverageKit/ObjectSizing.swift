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

    /// Sizes an item from **measured** surface points (ARKit raycast hits inside its mask) plus its
    /// silhouette rays and the table height. The hits fix the distance, so width and height are
    /// real measurements rather than inferences.
    /// - Parameters:
    ///   - surfaceHits: world points where rays through the mask interior hit a surface.
    ///   - silhouetteRays: rays through a sample of all mask pixels.
    ///   - planeY: table height (must be below the item; see `tablePlane`).
    public static func measure(
        camera: SIMD3<Float>, surfaceHits: [SIMD3<Float>], silhouetteRays: [Ray], planeY: Float
    ) -> ObjectEstimate? {
        // Hits on the item: above the table, at a consistent distance (drops hits that slipped
        // past the silhouette onto the wall or table behind).
        let above = surfaceHits.filter { $0.y > planeY + 0.006 }
        guard above.count >= 4 else { return nil }
        let dists = above.map { simd_distance($0, camera) }
        let dMed = median(dists)
        let hits = above.filter { let d = simd_distance($0, camera); return d > dMed * 0.7 && d < dMed * 1.3 }
        guard hits.count >= 4, silhouetteRays.count >= 10 else { return nil }

        let up = SIMD3<Float>(0, 1, 0)
        let a = SIMD3(median(hits.map(\.x)), median(hits.map(\.y)), median(hits.map(\.z)))
        var view = a - camera
        view.y = 0
        guard simd_length(view) > 1e-3 else { return nil }
        view = simd_normalize(view)
        let lateral = simd_normalize(simd_cross(view, up))

        func extents(through p: SIMD3<Float>) -> (lo: Float, hi: Float, top: Float)? {
            let pts = silhouetteRays.compactMap { $0.hit(planeThrough: p, normal: view) }
            guard pts.count >= 10 else { return nil }
            let lat = pts.map { simd_dot($0 - p, lateral) }
            return (percentile(lat, 0.03), percentile(lat, 0.97), percentile(pts.map(\.y), 0.98))
        }

        // Pass 1: width at the measured surface. The hits sit on the visible front/top, so the
        // middle is about half a (square) footprint further back, less so when looking from above.
        guard let e1 = extents(through: a) else { return nil }
        var width = max(e1.hi - e1.lo, 0.02)
        let horizontal = simd_length(SIMD2(a.x - camera.x, a.z - camera.z))
        let cosEl = horizontal / max(simd_distance(a, camera), 1e-3)
        var centre = a + lateral * ((e1.lo + e1.hi) / 2) + view * (width / 2 * cosEl)
        centre.y = planeY

        // Pass 2: re-measure on the vertical plane through the centre.
        guard let e2 = extents(through: centre) else { return nil }
        width = max(e2.hi - e2.lo, 0.02)
        centre += lateral * ((e2.lo + e2.hi) / 2)

        // Height: the silhouette's top edge is the item's *back* top edge when the camera is above
        // the item and its *front* top edge when it's below, so measure it on that plane.
        var top = e2.top
        let half = width / 2
        if let e3 = extents(through: centre + view * (camera.y > top ? half : -half)) { top = e3.top }
        top = max(top, percentile(hits.map(\.y), 0.95))
        let height = max(top - planeY, 0.02)

        return ObjectEstimate(footprintCentre: centre, width: width, height: height, depth: width)
    }

    /// Picks the table under the item from candidate horizontal plane heights: the highest plane at
    /// or below the *bottom* of the item's points (10th percentile + 1 cm). Works for low items
    /// (a mouse, a wallet) whose points sit within a centimetre or two of the table, and ignores
    /// planes ARKit found on top of the item.
    public static func tablePlane(candidates: [Float], surfaceHits: [SIMD3<Float>]) -> Float? {
        guard !surfaceHits.isEmpty else { return candidates.max() }
        let bottom = percentile(surfaceHits.map(\.y), 0.1)
        return candidates.filter { $0 <= bottom + 0.01 && $0 > bottom - 1.0 }.max()
    }

    /// Fits the item to ARKit's own triangulated feature points that fall inside its mask
    /// (accumulated over a second or two of aiming), plus its silhouette for the parts the points
    /// miss. Points on the table (mask bleed) and far-away strays (background seen through gaps)
    /// are dropped first.
    public static func fromPoints(
        camera: SIMD3<Float>, points: [SIMD3<Float>], silhouetteRays: [Ray], planeY: Float
    ) -> ObjectEstimate? {
        let above = points.filter { $0.y > planeY + 0.004 }
        guard above.count >= 8, silhouetteRays.count >= 10 else { return nil }
        let dists = above.map { simd_distance($0, camera) }
        let dMed = median(dists)
        let band = max(0.1, 0.35 * dMed)
        let pts = above.filter { abs(simd_distance($0, camera) - dMed) < band }
        guard pts.count >= 8 else { return nil }

        let up = SIMD3<Float>(0, 1, 0)
        let m = SIMD3(median(pts.map(\.x)), median(pts.map(\.y)), median(pts.map(\.z)))
        var view = m - camera
        view.y = 0
        guard simd_length(view) > 1e-3 else { return nil }
        view = simd_normalize(view)
        let lateral = simd_normalize(simd_cross(view, up))

        func silhouette(through p: SIMD3<Float>) -> (lo: Float, hi: Float, top: Float)? {
            let hits = silhouetteRays.compactMap { $0.hit(planeThrough: p, normal: view) }
            guard hits.count >= 10 else { return nil }
            let lat = hits.map { simd_dot($0 - p, lateral) }
            return (percentile(lat, 0.03), percentile(lat, 0.97), percentile(hits.map(\.y), 0.98))
        }

        // Width and lateral centre from the silhouette at the points' distance (points are sparse
        // at the edges); depth from how far back the points reach (at least 80% of the width,
        // since the back is hidden).
        guard let s1 = silhouette(through: m) else { return nil }
        let width = max(s1.hi - s1.lo, 0.02)
        let along = pts.map { simd_dot($0 - m, view) }
        let front = percentile(along, 0.05), back = percentile(along, 0.95)
        let depth = max(back - front, 0.8 * width)
        var centre = m + lateral * ((s1.lo + s1.hi) / 2) + view * (front + depth / 2)
        centre.y = planeY

        // Height: points' top, or the silhouette top measured on the plane it actually comes from
        // (back top edge when looking down at the item, front top edge when looking up at it).
        var top = percentile(pts.map(\.y), 0.97)
        let probeTop = max(top, s1.top)
        if let s2 = silhouette(through: centre + view * (camera.y > probeTop ? depth / 2 : -depth / 2)) {
            top = max(top, s2.top)
        }
        let height = max(top - planeY, 0.02)
        return ObjectEstimate(footprintCentre: centre, width: width, height: height, depth: depth)
    }

    static func median(_ v: [Float]) -> Float { percentile(v, 0.5) }

    static func percentile(_ v: [Float], _ p: Float) -> Float {
        let s = v.sorted()
        let i = min(s.count - 1, max(0, Int((Float(s.count - 1) * p).rounded())))
        return s[i]
    }
}
