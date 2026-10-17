import CoverageKit
import RealityKit
import UIKit

/// The AR coverage ring: 12 arcs lying on the table around the item's base, one per segment.
/// It never covers the item. While aiming it's a live preview that glides to the measured item
/// and shows the measured surface points; on Start it becomes the scan ring. Arcs are built at unit
/// radius and scaled, so resizing is cheap.
@MainActor
final class DomeEntity {
    let anchor = AnchorEntity(world: .zero)
    private let root = Entity()       // on the table, under the item's middle
    private let container = Entity()  // scaled to the ring radius
    private let pointsRoot = Entity()
    private var arcs: [SegmentID: ModelEntity] = [:]
    private var looks: [SegmentID: Look] = [:]
    private var points: [ModelEntity] = []
    private(set) var base: SIMD3<Float> = .zero
    private(set) var radius: Float = 0.15

    private enum Look { case preview, empty, current, filled }

    private static let materials: [Look: UnlitMaterial] = [
        .preview: material(Brand.mint, opacity: 0.45),
        .empty: material(.white, opacity: 0.35),
        .current: material(.white, opacity: 0.85),  // where the camera is now: hold here
        .filled: material(Brand.mint, opacity: 0.95),
    ]
    private static let pointMaterial = material(Brand.mint, opacity: 0.95)
    private static let ringWidth: Float = 0.22  // relative to the radius
    private static let lift: Float = 0.003      // just above the table, so it doesn't z-fight

    init() {
        anchor.addChild(root)
        root.addChild(container)
        anchor.addChild(pointsRoot)
        for seg in Dome.allSegments {
            guard let mesh = try? Self.arcMesh(seg) else { continue }
            let arc = ModelEntity(mesh: mesh, materials: [Self.materials[.preview]!])
            arcs[seg] = arc
            looks[seg] = .preview
            container.addChild(arc)
        }
        container.scale = SIMD3(repeating: radius)
    }

    /// Ring inner radius that clears an item of this footprint.
    static func radius(for e: ObjectEstimate) -> Float {
        0.5 * (e.width * e.width + e.depth * e.depth).squareRoot() + 0.03
    }

    /// Move/resize to the item. `base` = footprint centre on the table. `animated` glides there.
    func place(base: SIMD3<Float>, radius: Float, animated: Bool) {
        let first = self.base == .zero
        self.base = base
        self.radius = radius
        var t = root.transform
        t.translation = base + SIMD3(0, Self.lift, 0)
        var s = container.transform
        s.scale = SIMD3(repeating: radius)
        if animated && !first {
            root.move(to: t, relativeTo: anchor, duration: 0.25, timingFunction: .easeOut)
            container.move(to: s, relativeTo: root, duration: 0.25, timingFunction: .easeOut)
        } else {
            root.transform = t
            container.transform = s
        }
    }

    func setRadius(_ r: Float) {
        place(base: base, radius: r, animated: false)
    }

    /// Small dots where ARKit measured the item's surface (aiming only).
    func showPoints(_ world: [SIMD3<Float>]) {
        while points.count < world.count {
            let p = ModelEntity(mesh: .generateSphere(radius: 0.0035), materials: [Self.pointMaterial])
            pointsRoot.addChild(p)
            points.append(p)
        }
        for (i, p) in points.enumerated() {
            p.isEnabled = i < world.count
            if i < world.count { p.position = world[i] }
        }
    }

    /// Switch from preview to the scan look.
    func beginScan() {
        showPoints([])
        update(filled: [], current: nil)
    }

    func update(filled: Set<SegmentID>, current: SegmentID?) {
        for (seg, arc) in arcs {
            let look: Look = filled.contains(seg) ? .filled : (seg == current ? .current : .empty)
            guard looks[seg] != look else { continue }
            looks[seg] = look
            arc.model?.materials = [Self.materials[look]!]
        }
    }

    /// Small outward pop when a segment fills.
    func pulse(_ seg: SegmentID) {
        guard let arc = arcs[seg] else { return }
        var big = arc.transform
        big.scale = SIMD3(1.08, 1, 1.08)
        arc.move(to: big, relativeTo: container, duration: 0.12)
        Task { @MainActor [container] in
            try? await Task.sleep(nanoseconds: 120_000_000)
            var normal = arc.transform
            normal.scale = SIMD3(repeating: 1)
            arc.move(to: normal, relativeTo: container, duration: 0.18)
        }
    }

    private static func material(_ color: UIColor, opacity: Float) -> UnlitMaterial {
        var m = UnlitMaterial(color: color)
        m.blending = .transparent(opacity: .init(floatLiteral: opacity))
        return m
    }

    /// A flat arc of the unit annulus [1, 1 + ringWidth] for one segment, with gaps between arcs.
    /// Same azimuth convention as `Dome.position`: az 0 = +Z, az 90 = +X.
    private static func arcMesh(_ seg: SegmentID) throws -> MeshResource {
        let gapDeg: Float = 3
        let a0 = Float(seg.az * Dome.azimuthStepDeg) + gapDeg
        let a1 = Float((seg.az + 1) * Dome.azimuthStepDeg) - gapDeg
        let steps = 10
        var positions: [SIMD3<Float>] = []
        var normals: [SIMD3<Float>] = []
        for i in 0...steps {
            let a = (a0 + (a1 - a0) * Float(i) / Float(steps)) * .pi / 180
            let dir = SIMD3(sin(a), 0, cos(a))
            positions += [dir, dir * (1 + ringWidth)]
            normals += [[0, 1, 0], [0, 1, 0]]
        }
        var indices: [UInt32] = []
        for i in 0..<UInt32(steps) {
            let inner0 = 2 * i, outer0 = inner0 + 1, inner1 = inner0 + 2, outer1 = inner0 + 3
            // Both windings, so it shows from above and below.
            indices += [inner0, outer0, inner1, inner1, outer0, outer1]
            indices += [inner0, inner1, outer0, inner1, outer1, outer0]
        }
        var desc = MeshDescriptor(name: seg.name)
        desc.positions = MeshBuffers.Positions(positions)
        desc.normals = MeshBuffers.Normals(normals)
        desc.primitives = .triangles(indices)
        return try MeshResource.generate(from: [desc])
    }
}
