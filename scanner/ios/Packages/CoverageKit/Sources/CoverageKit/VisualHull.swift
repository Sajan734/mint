import Foundation
import simd

/// One view of the item: the camera (exact, from ARKit) and the item's segmentation mask.
/// The mask is in **upright (portrait)** orientation, as Vision returns it for a `.right` image:
/// sensor pixel (u, v) ↔ mask (x = (1 − v/H)·mw, y = (u/W)·mh).
public struct SilhouetteView: Sendable {
    public let worldToCamera: simd_float4x4  // inverse of ARKit camera.transform
    public let cameraPosition: SIMD3<Float>
    public let fx: Float, fy: Float, cx: Float, cy: Float  // sensor pixels
    public let sensorWidth: Float, sensorHeight: Float
    public let mask: [UInt8]                 // non-zero = item
    public let maskWidth: Int, maskHeight: Int

    public init(cameraTransform: simd_float4x4, intrinsics k: simd_float3x3, sensorWidth: Float, sensorHeight: Float,
                mask: [UInt8], maskWidth: Int, maskHeight: Int) {
        worldToCamera = cameraTransform.inverse
        cameraPosition = cameraTransform.translation
        fx = k[0][0]; fy = k[1][1]; cx = k[2][0]; cy = k[2][1]
        self.sensorWidth = sensorWidth
        self.sensorHeight = sensorHeight
        self.mask = mask
        self.maskWidth = maskWidth
        self.maskHeight = maskHeight
    }

    /// Where a world point lands in mask pixels (upright), or nil if behind the camera / off the image.
    public func maskPoint(_ p: SIMD3<Float>) -> SIMD2<Float>? {
        let c = worldToCamera * SIMD4(p, 1)
        guard c.z < -0.01 else { return nil }  // ARKit cameras look down −z
        let u = fx * c.x / -c.z + cx
        let v = fy * -c.y / -c.z + cy
        guard u >= 0, v >= 0, u < sensorWidth, v < sensorHeight else { return nil }
        return SIMD2((1 - v / sensorHeight) * Float(maskWidth), u / sensorWidth * Float(maskHeight))
    }

    /// Whether a world point projects onto the item. nil = behind the camera or outside the image
    /// (the view says nothing about it).
    public func inside(_ p: SIMD3<Float>) -> Bool? {
        guard let m = maskPoint(p) else { return nil }
        let mx = min(maskWidth - 1, Int(m.x)), my = min(maskHeight - 1, Int(m.y))
        return mask[my * maskWidth + mx] != 0
    }

    /// Extent of the mask's item pixels (mask pixel units, pixel centres), and whether it touches the image edge.
    public func maskExtent() -> (minX: Float, maxX: Float, minY: Float, maxY: Float, touchesEdge: Bool)? {
        var x0 = maskWidth, x1 = -1, y0 = maskHeight, y1 = -1
        for y in 0..<maskHeight {
            let row = y * maskWidth
            for x in 0..<maskWidth where mask[row + x] != 0 {
                x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
            }
        }
        guard x1 >= 0 else { return nil }
        let edge = x0 <= 1 || y0 <= 1 || x1 >= maskWidth - 2 || y1 >= maskHeight - 2
        return (Float(x0) + 0.5, Float(x1) + 0.5, Float(y0) + 0.5, Float(y1) + 0.5, edge)
    }
}

/// Tracks the item through a scan from recent views only. ARKit's world drifts as the camera
/// moves round (a real lap round a mouse: ~3.5–4 cm), so a hull from *all* views shrinks and the
/// ring slides off the item. Instead: keep the last views, rebuild a hull from the newest ones that
/// together span ≥ `minSpread`, and follow it. Old views age out, so drift can't accumulate, and a
/// bad mask only affects a short window.
public struct ItemTracker: Sendable {
    public private(set) var estimate: ObjectEstimate
    public let planeY: Float
    public private(set) var updates = 0  // times the estimate was refined from views
    private var views: [SilhouetteView] = []
    private let maxViews: Int
    private let minViews: Int
    private let minSpread: Float

    public init(start: ObjectEstimate, planeY: Float, maxViews: Int = 12, minViews: Int = 4, minSpread: Float = 60) {
        estimate = start
        self.planeY = planeY
        self.maxViews = maxViews
        self.minViews = minViews
        self.minSpread = minSpread
        // Until the first hull: a box the size of the first estimate, so the per-view nudge can
        // centre the item from the very first view (sideways at once; depth as the camera moves).
        let s = (0...6).map { Float($0) / 6 - 0.5 }
        shape = s.flatMap { a in s.flatMap { b in s.map { c in
            SIMD3(a * start.width, (c + 0.5) * start.height, b * start.depth)
        } } }
    }

    /// Share of sample points in the core of the current estimate (middle of the footprint, lower
    /// half) that `view`'s mask covers. A view of the right item covers its core; a wrong instance
    /// (a hand, a laptop) doesn't. nil when the core isn't in view.
    public func coverage(of view: SilhouetteView) -> Float? {
        let e = estimate
        let r = 0.3 * min(e.width, e.depth)
        var inside = 0, visible = 0
        for a in stride(from: Float(0), to: 2 * .pi, by: .pi / 4) {
            for rr in [Float(0), 0.5, 1] {
                for hf in [Float(0.15), 0.35, 0.55] {
                    let p = e.footprintCentre + SIMD3(rr * r * cos(a), hf * e.height, rr * r * sin(a))
                    guard let isIn = view.inside(p) else { continue }
                    visible += 1
                    if isIn { inside += 1 }
                }
            }
        }
        return visible >= 6 ? Float(inside) / Float(visible) : nil
    }

    /// The item's shape from the latest hull: occupied voxel centres relative to the footprint centre.
    public private(set) var shape: [SIMD3<Float>] = []

    /// Adds a view. Returns true if the estimate moved (refined from the window, or nudged).
    @discardableResult
    public mutating func add(_ view: SilhouetteView) -> Bool {
        // Once the estimate comes from views, refuse masks that don't cover its core. Before that
        // the starting guess can be centimetres off, so every view is let in.
        if updates > 0, let c = coverage(of: view), c < 0.6 { return false }
        views.append(view)
        if views.count > maxViews { views.removeFirst(views.count - maxViews) }

        // Newest views until they span enough angle to pin down depth.
        var hull = VisualHull(around: estimate, planeY: planeY)
        for (n, v) in views.reversed().enumerated() {
            hull.carve(v)
            if n + 1 >= minViews && hull.spreadDegrees >= minSpread { break }
        }
        var moved = false
        if hull.views >= minViews, hull.spreadDegrees >= minSpread, let e = hull.estimate() {
            // Follow the position directly (that's the drift); smooth the size, which should not change.
            let a: Float = updates == 0 ? 1 : 0.35
            func mix(_ x: Float, _ y: Float) -> Float { x + (y - x) * a }
            estimate = ObjectEstimate(footprintCentre: e.footprintCentre,
                                      width: mix(estimate.width, e.width), height: mix(estimate.height, e.height),
                                      depth: mix(estimate.depth, e.depth))
            shape = hull.occupiedPoints(limit: 400).map { $0 - e.footprintCentre }
            updates += 1
            moved = true
        }
        // The window hull lags drift by up to `minSpread` of camera motion. This view shows where the
        // item is *now*: nudge the estimate so the shape's projection is centred on the mask.
        if !shape.isEmpty, let d = nudge(for: view) {
            estimate = ObjectEstimate(footprintCentre: estimate.footprintCentre + d,
                                      width: estimate.width, height: estimate.height, depth: estimate.depth)
            moved = true
        }
        return moved
    }

    /// Horizontal world shift that centres the projected shape on `view`'s mask, scaled by `gain`.
    /// nil if the item touches the image edge (its mask centroid would be biased) or too little is visible.
    public func nudge(for view: SilhouetteView, gain: Float = 0.6, cap: Float = 0.05) -> SIMD3<Float>? {
        // Compare like with like: the centre of the projected shape's extent vs the centre of the
        // mask's extent. (Comparing a volume centroid with an area centroid is biased for angled
        // shapes: 8 mm in the drift test.)
        guard let box = view.maskExtent(), !box.touchesEdge else { return nil }
        var xs: [Float] = [], ys: [Float] = []
        for o in shape {
            guard let m = view.maskPoint(estimate.footprintCentre + o) else { continue }
            xs.append(m.x); ys.append(m.y)
        }
        guard xs.count >= 20 else { return nil }
        let maskCentre = (x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2)
        let sx = (xs.min()! + xs.max()!) / 2, sy = (ys.min()! + ys.max()!) / 2
        let dmx = maskCentre.x - sx, dmy = maskCentre.y - sy  // mask pixels (upright)
        // Mask (upright) → sensor pixels: u = my·W/mh, v = (1 − mx/mw)·H.
        let du = dmy * view.sensorWidth / Float(view.maskHeight)
        let dv = -dmx * view.sensorHeight / Float(view.maskWidth)
        let c = view.worldToCamera * SIMD4(estimate.centre, 1)
        let z = -c.z
        guard z > 0.02 else { return nil }
        let camDelta = SIMD3(du * z / view.fx, -dv * z / view.fy, 0)  // ARKit camera axes
        let r = view.worldToCamera.inverse
        var d = simd_float3x3(SIMD3(r.columns.0.x, r.columns.0.y, r.columns.0.z),
                              SIMD3(r.columns.1.x, r.columns.1.y, r.columns.1.z),
                              SIMD3(r.columns.2.x, r.columns.2.y, r.columns.2.z)) * camDelta
        d.y = 0  // the item stays on the table
        let len = simd_length(d)
        if len > cap { d *= cap / len }
        return d * gain
    }
}

/// Space carving: a voxel grid around the item, resting on the table. Each view votes on whether
/// each voxel projects inside the item's silhouette; voxels inside (nearly) every view that sees
/// them are the item. With exact ARKit poses this pins down the footprint and height far better
/// than any single view, and keeps improving as the camera moves round.
public struct VisualHull: Sendable {
    public let planeY: Float
    public let origin: SIMD3<Float>  // min corner of the grid
    public let voxel: SIMD3<Float>   // voxel size
    public let nx: Int, ny: Int, nz: Int
    private var insideVotes: [UInt16]
    private var seenVotes: [UInt16]
    private var viewDirections: [SIMD2<Float>] = []  // horizontal unit vectors item → camera
    public private(set) var views = 0

    /// A grid comfortably larger than the first estimate (which can be centimetres off).
    public init(around e: ObjectEstimate, planeY: Float, lateralCells: Int = 44, verticalCells: Int = 22) {
        self.planeY = planeY
        let half = max(0.08, 1.5 * 0.5 * max(e.width, e.depth) + 0.04)
        let height = max(0.06, 1.8 * e.height + 0.03)
        origin = SIMD3(e.footprintCentre.x - half, planeY, e.footprintCentre.z - half)
        nx = lateralCells; nz = lateralCells; ny = verticalCells
        voxel = SIMD3(2 * half / Float(nx), height / Float(ny), 2 * half / Float(nz))
        insideVotes = [UInt16](repeating: 0, count: nx * ny * nz)
        seenVotes = [UInt16](repeating: 0, count: nx * ny * nz)
    }

    @inline(__always) private func centre(_ i: Int, _ j: Int, _ k: Int) -> SIMD3<Float> {
        origin + (SIMD3(Float(i), Float(j), Float(k)) + 0.5) * voxel
    }

    /// Share of the hull's **core** (occupied voxels near the middle of the footprint, lower part)
    /// that this view's mask covers. A correct view always covers the core, even while it carves
    /// excess off the edges (the hull is a superset of the item); a wrong mask doesn't.
    /// nil until there's an estimate to check against.
    public func coreAgreement(with view: SilhouetteView) -> Float? {
        guard let e = estimate() else { return nil }
        let coreRadius = 0.35 * min(e.width, e.depth)
        let coreTop = planeY + 0.6 * e.height
        var agree = 0, visible = 0
        for k in 0..<nz {
            for j in 0..<ny {
                for i in 0..<nx {
                    let c = centre(i, j, k)
                    guard c.y <= coreTop,
                          simd_length(SIMD2(c.x - e.footprintCentre.x, c.z - e.footprintCentre.z)) <= coreRadius,
                          isOccupied((k * ny + j) * nx + i),
                          let isIn = view.inside(c) else { continue }
                    visible += 1
                    if isIn { agree += 1 }
                }
            }
        }
        return visible >= 4 ? Float(agree) / Float(visible) : nil
    }

    /// Carves with `view` unless its mask contradicts an established hull: a wrong instance (a hand,
    /// a sleeve, the laptop) would otherwise carve away real voxels. Gating starts only once ≥ 4
    /// views span ≥ 60°; before that the hull is still a long cone and correct new angles must be
    /// free to cut it down. Returns whether the view was used. Real scan: without a gate the width
    /// collapsed from 8.1 to 5.8 cm once a sweater came into view.
    @discardableResult
    public mutating func carveIfConsistent(_ view: SilhouetteView, minAgreement: Float = 0.75) -> Bool {
        if views >= 4, spreadDegrees >= 60, let a = coreAgreement(with: view), a < minAgreement { return false }
        carve(view)
        return true
    }

    private func isOccupied(_ idx: Int, minSeen: Int = 3, ratio: Float = 0.85) -> Bool {
        let s = seenVotes[idx]
        return s >= minSeen && Float(insideVotes[idx]) >= ratio * Float(s)
    }

    public mutating func carve(_ view: SilhouetteView) {
        for k in 0..<nz {
            for j in 0..<ny {
                for i in 0..<nx {
                    guard let isIn = view.inside(centre(i, j, k)) else { continue }
                    let idx = (k * ny + j) * nx + i
                    seenVotes[idx] &+= 1
                    if isIn { insideVotes[idx] &+= 1 }
                }
            }
        }
        views += 1
        let mid = origin + SIMD3(Float(nx), 0, Float(nz)) * voxel / 2
        let d = view.cameraPosition - mid
        let h = SIMD2(d.x, d.z)
        if simd_length(h) > 1e-3 { viewDirections.append(simd_normalize(h)) }
    }

    /// Centres of occupied voxels (evenly subsampled to at most `limit`).
    public func occupiedPoints(limit: Int) -> [SIMD3<Float>] {
        var pts: [SIMD3<Float>] = []
        for k in 0..<nz {
            for j in 0..<ny {
                for i in 0..<nx where isOccupied((k * ny + j) * nx + i) {
                    pts.append(centre(i, j, k))
                }
            }
        }
        guard pts.count > limit else { return pts }
        let step = Double(pts.count) / Double(limit)
        return (0..<limit).map { pts[Int(Double($0) * step)] }
    }

    /// Widest horizontal angle between any two views, in degrees: how well depth is pinned down.
    public var spreadDegrees: Float {
        var best: Float = 0
        for a in 0..<viewDirections.count {
            for b in (a + 1)..<viewDirections.count {
                best = max(best, acos(max(-1, min(1, simd_dot(viewDirections[a], viewDirections[b])))))
            }
        }
        return best * 180 / .pi
    }

    /// The item's footprint and height from voxels that are inside the silhouette in at least
    /// `ratio` of the (≥ `minSeen`) views that see them. The footprint is tight once views span
    /// ~45°+; height is an upper bound when every view looks down on the item.
    public func estimate(minSeen: Int = 3, ratio: Float = 0.85) -> ObjectEstimate? {
        var xs: [Float] = [], zs: [Float] = [], tops: [Float] = []
        for k in 0..<nz {
            for j in 0..<ny {
                for i in 0..<nx {
                    let idx = (k * ny + j) * nx + i
                    let s = seenVotes[idx]
                    guard s >= minSeen, Float(insideVotes[idx]) >= ratio * Float(s) else { continue }
                    let c = centre(i, j, k)
                    xs.append(c.x); zs.append(c.z); tops.append(c.y + voxel.y / 2)
                }
            }
        }
        guard xs.count >= 4 else { return nil }
        // Footprint: principal axes of the occupied voxels, robust extents along each.
        let n = Float(xs.count)
        let mx = xs.reduce(0, +) / n, mz = zs.reduce(0, +) / n
        var sxx: Float = 0, szz: Float = 0, sxz: Float = 0
        for (x, z) in zip(xs, zs) {
            sxx += (x - mx) * (x - mx); szz += (z - mz) * (z - mz); sxz += (x - mx) * (z - mz)
        }
        let angle = 0.5 * atan2(2 * sxz, sxx - szz)
        let a = SIMD2<Float>(cos(angle), sin(angle)), b = SIMD2<Float>(-sin(angle), cos(angle))
        let pa = zip(xs, zs).map { simd_dot(SIMD2($0 - mx, $1 - mz), a) }
        let pb = zip(xs, zs).map { simd_dot(SIMD2($0 - mx, $1 - mz), b) }
        let (a0, a1) = (ObjectSizing.percentile(pa, 0.02), ObjectSizing.percentile(pa, 0.98))
        let (b0, b1) = (ObjectSizing.percentile(pb, 0.02), ObjectSizing.percentile(pb, 0.98))
        let mid = SIMD2(mx, mz) + a * (a0 + a1) / 2 + b * (b0 + b1) / 2
        let height = ObjectSizing.percentile(tops, 0.99) - planeY
        return ObjectEstimate(
            footprintCentre: SIMD3(mid.x, planeY, mid.y),
            width: (a1 - a0) + voxel.x, height: max(height, voxel.y), depth: (b1 - b0) + voxel.z
        )
    }
}
