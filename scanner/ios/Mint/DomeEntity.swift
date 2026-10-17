import CoverageKit
import RealityKit
import UIKit

/// The AR capture dome: one curved tile per segment, anchored around the item.
/// Tiles are built at unit radius; `radius` scales the whole dome (pinch to resize).
@MainActor
final class DomeEntity {
    let anchor: AnchorEntity
    private let container = Entity()
    private var tiles: [SegmentID: ModelEntity] = [:]
    private var looks: [SegmentID: Look] = [:]

    private enum Look { case empty, filled, emptyNear, filledNear }

    private static let materials: [Look: UnlitMaterial] = [
        .empty: material(.white, opacity: 0.22),
        .filled: material(Brand.mint, opacity: 0.6),
        // Tiles between the camera and the item fade so they don't hide it.
        .emptyNear: material(.white, opacity: 0.06),
        .filledNear: material(Brand.mint, opacity: 0.15),
    ]

    var radius: Float = 0.25 {
        didSet { container.scale = SIMD3(repeating: radius) }
    }

    init(at position: SIMD3<Float>) {
        anchor = AnchorEntity(world: position)
        anchor.addChild(container)
        container.scale = SIMD3(repeating: radius)

        let marker = ModelEntity(mesh: .generateSphere(radius: 0.006), materials: [Self.material(Brand.mint, opacity: 1)])
        anchor.addChild(marker)

        for seg in Dome.allSegments {
            guard let mesh = try? Self.tileMesh(seg) else { continue }
            let tile = ModelEntity(mesh: mesh, materials: [Self.materials[.empty]!])
            tiles[seg] = tile
            looks[seg] = .empty
            container.addChild(tile)
        }
    }

    /// Recolour tiles. `cameraAzimuthDeg` fades the tiles on the camera's side of the item.
    func update(filled: Set<SegmentID>, cameraAzimuthDeg: Float?) {
        for (seg, tile) in tiles {
            let near = cameraAzimuthDeg.map { Self.isNear(seg, azimuthDeg: $0) } ?? false
            let look: Look = filled.contains(seg) ? (near ? .filledNear : .filled) : (near ? .emptyNear : .empty)
            guard looks[seg] != look else { continue }
            looks[seg] = look
            tile.model?.materials = [Self.materials[look]!]
        }
    }

    /// Small pop when a segment fills.
    func pulse(_ seg: SegmentID) {
        guard let tile = tiles[seg] else { return }
        var big = tile.transform
        big.scale = SIMD3(repeating: 1.08)
        tile.move(to: big, relativeTo: container, duration: 0.12)
        Task { @MainActor [container] in
            try? await Task.sleep(nanoseconds: 120_000_000)
            var normal = tile.transform
            normal.scale = SIMD3(repeating: 1)
            tile.move(to: normal, relativeTo: container, duration: 0.18)
        }
    }

    private static func isNear(_ seg: SegmentID, azimuthDeg: Float) -> Bool {
        let centre = Float(seg.az * Dome.azimuthStepDeg + Dome.azimuthStepDeg / 2)
        var d = abs(centre - azimuthDeg).truncatingRemainder(dividingBy: 360)
        if d > 180 { d = 360 - d }
        return d < 40
    }

    private static func material(_ color: UIColor, opacity: Float) -> UnlitMaterial {
        var m = UnlitMaterial(color: color)
        m.blending = .transparent(opacity: .init(floatLiteral: opacity))
        return m
    }

    /// A curved patch of the unit sphere covering one segment, inset so tiles have gaps.
    /// Same azimuth/elevation convention as `Dome.position`: az 0 = +Z, az 90 = +X.
    private static func tileMesh(_ seg: SegmentID) throws -> MeshResource {
        let marginDeg: Float = 2.5
        let band = Dome.bands[seg.el]
        let a0 = Float(seg.az * Dome.azimuthStepDeg) + marginDeg
        let a1 = Float((seg.az + 1) * Dome.azimuthStepDeg) - marginDeg
        let e0 = band.minDeg + marginDeg, e1 = band.maxDeg - marginDeg
        let nu = 6, nv = 4

        var positions: [SIMD3<Float>] = []
        var normals: [SIMD3<Float>] = []
        for j in 0...nv {
            let e = (e0 + (e1 - e0) * Float(j) / Float(nv)) * .pi / 180
            for i in 0...nu {
                let a = (a0 + (a1 - a0) * Float(i) / Float(nu)) * .pi / 180
                let p = SIMD3(cos(e) * sin(a), sin(e), cos(e) * cos(a))
                positions.append(p)
                normals.append(p)
            }
        }
        var indices: [UInt32] = []
        let row = UInt32(nu + 1)
        for j in 0..<UInt32(nv) {
            for i in 0..<UInt32(nu) {
                let a = j * row + i, b = a + 1, c = a + row, d = c + 1
                // Both windings, so the tile shows from outside and inside the dome.
                indices += [a, c, b, b, c, d]
                indices += [a, b, c, b, d, c]
            }
        }
        var desc = MeshDescriptor(name: seg.name)
        desc.positions = MeshBuffers.Positions(positions)
        desc.normals = MeshBuffers.Normals(normals)
        desc.primitives = .triangles(indices)
        return try MeshResource.generate(from: [desc])
    }
}
