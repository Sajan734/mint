import XCTest
import simd
@testable import CoverageKit

/// Camera pose at a dome position around the origin (rotation only matters for angular speed).
private func cameraPose(azDeg: Float, elDeg: Float, dist: Float = 0.5, yawDeg: Float = 0) -> simd_float4x4 {
    let az = azDeg * .pi / 180, el = elDeg * .pi / 180
    var m = simd_float4x4(simd_quatf(angle: yawDeg * .pi / 180, axis: [0, 1, 0]))
    m.columns.3 = SIMD4(dist * cos(el) * sin(az), dist * sin(el), dist * cos(el) * cos(az), 1)
    return m
}

private func obs(_ m: simd_float4x4, t: Double, sharp: Double = 100, luma: Double = 120, tracking: Bool = true) -> FrameObservation {
    FrameObservation(cameraTransform: m, timestamp: t, trackingNormal: tracking, sharpness: sharp, meanLuma: luma)
}

final class DomeTests: XCTestCase {
    func testSegmentNames() {
        let cases: [(SegmentID, String)] = [
            (SegmentID(az: 0, el: 0), "az000_el28"),
            (SegmentID(az: 3, el: 0), "az090_el28"),
            (SegmentID(az: 11, el: 1), "az330_el60"),
        ]
        for (seg, name) in cases { XCTAssertEqual(seg.name, name) }
        XCTAssertEqual(Dome.segmentCount, 24)
        XCTAssertEqual(Dome.segmentsToComplete, 22)
        XCTAssertEqual(Set(Dome.allSegments.map(\.name)).count, 24)
    }

    func testPositionToSegment() {
        let cases: [(SIMD3<Float>, SegmentID?)] = [
            ([0, 0.2, 1], SegmentID(az: 0, el: 0)),       // +Z, ~11°
            ([1, 0.5, 0], SegmentID(az: 3, el: 0)),       // +X = 90°, ~27°
            ([0, 1.2, -1], SegmentID(az: 6, el: 1)),      // 180°, ~50°
            ([-1, 3, 0], SegmentID(az: 9, el: 1)),        // 270°, ~72°
            ([-0.001, 0.5, 1], SegmentID(az: 11, el: 0)), // just under 360°
            ([0, 8, 1], nil),                             // ~83°, too high
            ([0, 0.1, 1], nil),                           // ~6°, too low
        ]
        let anchor: SIMD3<Float> = [0.2, 0.3, -0.1]
        for (cam, expected) in cases {
            let p = Dome.position(camera: cam + anchor, anchor: anchor)
            XCTAssertEqual(Dome.segment(for: p), expected, "camera \(cam) → az \(p.azimuthDeg) el \(p.elevationDeg)")
        }
    }
}

final class GeometryTests: XCTestCase {
    func testRowMajorPutsTranslationInLastColumn() {
        var m = matrix_identity_float4x4
        m.columns.3 = [1, 2, 3, 1]
        let r = Geometry.rowMajor(m)
        XCTAssertEqual(r[0][3], 1)
        XCTAssertEqual(r[1][3], 2)
        XCTAssertEqual(r[2][3], 3)
        XCTAssertEqual(r[3], [0, 0, 0, 1])
    }

    func testScaleIntrinsics() {
        // ARKit-like K for 1920×1440 → 960×720.
        let k = simd_float3x3(columns: ([1500, 0, 0], [0, 1500, 0], [960, 720, 1]))
        let s = Geometry.rowMajor(Geometry.scaleIntrinsics(k, sx: 0.5, sy: 0.5))
        XCTAssertEqual(s, [[750, 0, 480], [0, 750, 360], [0, 0, 1]])
    }

    func testAngularSpeed() {
        let a = cameraPose(azDeg: 0, elDeg: 20, yawDeg: 0)
        let b = cameraPose(azDeg: 0, elDeg: 20, yawDeg: 90)
        XCTAssertEqual(Geometry.rotationAngle(a, b), .pi / 2, accuracy: 1e-3)
        XCTAssertEqual(Geometry.angularSpeed(from: a, to: b, dt: 0.5), .pi, accuracy: 1e-2)
        XCTAssertEqual(Geometry.angularSpeed(from: a, to: b, dt: 0), 0)
    }
}

final class SharpnessTests: XCTestCase {
    func testLaplacianVariance() {
        let flat = GrayImage(width: 16, height: 16, pixels: .init(repeating: 128, count: 256))
        let checker = GrayImage(width: 16, height: 16, pixels: (0..<256).map { ($0 % 16 + $0 / 16) % 2 == 0 ? 0 : 255 })
        let ramp = GrayImage(width: 16, height: 16, pixels: (0..<256).map { UInt8(($0 % 16) * 16) })
        XCTAssertEqual(Sharpness.laplacianVariance(flat), 0)
        XCTAssertEqual(Sharpness.laplacianVariance(ramp), 0, accuracy: 1e-9)  // smooth gradient = no detail
        XCTAssertGreaterThan(Sharpness.laplacianVariance(checker), 1000)
    }

    func testDownsampleHonoursBytesPerRow() {
        // 4×2 image stored with 2 bytes of row padding.
        let bytes: [UInt8] = [10, 10, 50, 50, 0, 0,
                              10, 10, 50, 50, 0, 0]
        let img = bytes.withUnsafeBufferPointer {
            Sharpness.downsample(base: $0.baseAddress!, width: 4, height: 2, bytesPerRow: 6, factor: 2)
        }
        XCTAssertEqual(img.width, 2)
        XCTAssertEqual(img.height, 1)
        XCTAssertEqual(img.pixels, [10, 50])
    }

    func testGate() {
        var gate = SharpnessGate(absoluteMin: 20, relativeToRecent: 0.7, window: 10)
        XCTAssertFalse(gate.accept(10))  // under the floor
        XCTAssertTrue(gate.accept(100))
        XCTAssertTrue(gate.accept(90))
        XCTAssertFalse(gate.accept(40))  // much blurrier than recent frames
        XCTAssertTrue(gate.accept(75))
    }
}

final class TrackerTests: XCTestCase {
    func testFillsAndRejects() {
        var t = CoverageTracker(anchor: .zero)
        let d1 = t.observe(obs(cameraPose(azDeg: 100, elDeg: 20), t: 0))
        XCTAssertNil(d1.issue)
        XCTAssertTrue(d1.filledNewSegment)
        XCTAssertEqual(d1.segment, SegmentID(az: 3, el: 0))

        // Same segment again, not sharper: no new fill, not a better keyframe.
        let d2 = t.observe(obs(cameraPose(azDeg: 105, elDeg: 20), t: 0.1))
        XCTAssertFalse(d2.filledNewSegment)
        XCTAssertFalse(d2.isBestForSegment)

        // 90° of rotation in 0.1 s is too fast.
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 0.2)).issue, .tooFast)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 20, dist: 3, yawDeg: 90), t: 1.0)).issue, .tooFar)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 20, dist: 0.05, yawDeg: 90), t: 1.5)).issue, .tooClose)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 85, yawDeg: 90), t: 2.0)).issue, .tooHigh)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 1, yawDeg: 90), t: 2.5)).issue, .tooLow)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 3.0, luma: 10)).issue, .tooDark)
        XCTAssertEqual(t.observe(obs(cameraPose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 3.5, tracking: false)).issue, .trackingLimited)
        XCTAssertEqual(t.coveragePct, 4)  // 1 of 24
    }

    func testCompletesAt22Segments() {
        var t = CoverageTracker(anchor: .zero)
        var time = 0.0
        for seg in Dome.allSegments.prefix(21) {
            time += 1
            let az = Float(seg.az * Dome.azimuthStepDeg) + 15
            _ = t.observe(obs(cameraPose(azDeg: az, elDeg: Float(Dome.bands[seg.el].centreDeg)), t: time))
        }
        XCTAssertEqual(t.filled.count, 21)
        XCTAssertFalse(t.isComplete)
        _ = t.observe(obs(cameraPose(azDeg: 15 + 30 * 9, elDeg: 60), t: time + 1))
        XCTAssertTrue(t.isComplete)
        XCTAssertEqual(t.coveragePct, 91)
    }
}

final class GuidanceTests: XCTestCase {
    private func at(_ az: Float, _ el: Float) -> DomePosition {
        Dome.position(camera: cameraPose(azDeg: az, elDeg: el).translation, anchor: .zero)
    }

    func testHints() {
        let lowRing = Set((0..<12).map { SegmentID(az: $0, el: 0) })
        let highRing = Set((0..<12).map { SegmentID(az: $0, el: 1) })
        let lowMissing2And9 = lowRing.subtracting([SegmentID(az: 2, el: 0), SegmentID(az: 9, el: 0)])
        let cases: [(DomePosition, Set<SegmentID>, Hint)] = [
            (at(15, 25), [], .holdHere),
            (at(15, 25), [SegmentID(az: 0, el: 0)], .walkRight(segments: 1)),  // tie between bins 11 and 1 → right
            (at(15, 25), lowMissing2And9, .walkRight(segments: 2)),
            (at(255, 25), lowMissing2And9, .walkRight(segments: 1)),           // bin 8 → bin 9
            (at(345, 25), lowMissing2And9, .walkLeft(segments: 2)),            // bin 11: bin 9 is 2 left, bin 2 is 3 right
            (at(15, 25), lowRing, .raise),
            (at(15, 60), highRing, .lower),
            (at(15, 5), [], .raise),
            (at(15, 85), [], .lower),
            (at(15, 25), Set(Dome.allSegments.prefix(22)), .done),
        ]
        for (i, (p, filled, expected)) in cases.enumerated() {
            XCTAssertEqual(Guidance.hint(position: p, filled: filled), expected, "case \(i)")
        }
    }
}

final class ObjectSizingTests: XCTestCase {
    /// A 20 × 30 × 20 cm box standing on the table at the origin, seen from 80 cm away, 35 cm up.
    func testBoxFromOneView() {
        let cam = SIMD3<Float>(0.05, 0.35, 0.8)
        func ray(to p: SIMD3<Float>) -> Ray { Ray(origin: cam, direction: p - cam) }
        let steps = (0...20).map { Float($0) / 20 }
        let contact = steps.map { ray(to: [-0.1 + 0.2 * $0, 0, 0.1]) }
        let frontFace = steps.flatMap { u in steps.map { v in ray(to: [-0.1 + 0.2 * u, 0.3 * v, 0.1]) } }
        let topFace = steps.flatMap { u in steps.map { v in ray(to: [-0.1 + 0.2 * u, 0.3, 0.1 - 0.2 * v]) } }

        let e = ObjectSizing.estimate(camera: cam, contactRays: contact, silhouetteRays: frontFace + topFace, planeY: 0)!
        XCTAssertEqual(e.width, 0.2, accuracy: 0.02)
        XCTAssertEqual(e.height, 0.3, accuracy: 0.02)
        XCTAssertEqual(e.footprintCentre.x, 0, accuracy: 0.02)
        XCTAssertEqual(e.footprintCentre.y, 0, accuracy: 1e-5)
        XCTAssertEqual(e.footprintCentre.z, 0, accuracy: 0.03)
        XCTAssertEqual(e.centre.y, e.height / 2, accuracy: 1e-5)
        XCTAssertGreaterThan(e.domeRadius, 0.5 * (0.2 * 0.2 + 0.3 * 0.3 + 0.2 * 0.2).squareRoot())
    }

    func testRejectsTooLittleData() {
        let cam = SIMD3<Float>(0, 0.3, 0.5)
        let r = Ray(origin: cam, direction: [0, -0.3, -0.5])
        XCTAssertNil(ObjectSizing.estimate(camera: cam, contactRays: [r], silhouetteRays: [r], planeY: 0))
    }
}

final class CaptureFilesTests: XCTestCase {
    func testManifestShape() throws {
        let m = CaptureManifest(
            scan_id: "s", item_id: "i", batch_id: "b", kind: "listing",
            frames: [.init(index: 7, path: "scans/s/f00007.jpg", t_ms: 233, pose: Geometry.rowMajor(matrix_identity_float4x4),
                           intrinsics: [[1, 0, 2], [0, 1, 3], [0, 0, 1]], sharpness: 12.5, segment: "az090_el20")],
            anchor: [0, 0.1, 0], coverage_pct: 91, width: 1440, height: 1080, device: "iPhone", created_at: "2026-10-17T00:00:00Z")
        let json = try JSONSerialization.jsonObject(with: CaptureJSON.encode(m)) as! [String: Any]
        XCTAssertEqual(json["v"] as? Int, 3)
        XCTAssertNil(json["deal_id"])  // optional fields are omitted, not null
        XCTAssertEqual(Set(json.keys), ["v", "scan_id", "item_id", "batch_id", "kind", "frames", "anchor",
                                        "coverage_pct", "width", "height", "device", "created_at"])
        let frame = (json["frames"] as! [[String: Any]])[0]
        XCTAssertNil(frame["sha256"])
        XCTAssertEqual(frame["path"] as? String, "scans/s/f00007.jpg")
    }

    func testPoseRecordIsOneLine() throws {
        let r = PoseRecord(frame: 0, t_ms: 0, pose_world: Geometry.rowMajor(matrix_identity_float4x4), pose: nil,
                           intrinsics: [[1, 0, 0], [0, 1, 0], [0, 0, 1]], tracking: "normal", state: "handling",
                           sharpness: 0, segment: nil, counted: false)
        let line = String(decoding: try CaptureJSON.encode(r), as: UTF8.self)
        XCTAssertFalse(line.contains("\n"))
        XCTAssertFalse(line.contains("\"pose\""))  // absent while handling
    }
}

final class ObjectMeasureTests: XCTestCase {
    /// Same 20 × 30 × 20 cm box at the origin. Hits = points on the faces the camera can see.
    private func box(camera cam: SIMD3<Float>) -> (hits: [SIMD3<Float>], silhouette: [Ray]) {
        let s = (0...10).map { Float($0) / 10 }
        let front = s.flatMap { u in s.map { v in SIMD3<Float>(-0.1 + 0.2 * u, 0.3 * v, 0.1) } }
        let top = s.flatMap { u in s.map { v in SIMD3<Float>(-0.1 + 0.2 * u, 0.3, 0.1 - 0.2 * v) } }
        let silhouette = (front + top).map { Ray(origin: cam, direction: $0 - cam) }
        let hits = stride(from: 0, to: front.count, by: 3).map { front[$0] } + stride(from: 0, to: top.count, by: 5).map { top[$0] }
        return (hits, silhouette)
    }

    func testMeasuresBoxFromSideAndAbove() {
        for cam in [SIMD3<Float>(0.05, 0.35, 0.8), SIMD3<Float>(-0.1, 0.7, 0.45)] {
            let b = box(camera: cam)
            let e = ObjectSizing.measure(camera: cam, surfaceHits: b.hits, silhouetteRays: b.silhouette, planeY: 0)!
            XCTAssertEqual(e.width, 0.2, accuracy: 0.03, "camera \(cam)")
            XCTAssertEqual(e.height, 0.3, accuracy: 0.02, "camera \(cam)")
            XCTAssertEqual(e.footprintCentre.x, 0, accuracy: 0.03, "camera \(cam)")
            XCTAssertEqual(e.footprintCentre.z, 0, accuracy: 0.04, "camera \(cam)")
        }
    }

    func testIgnoresHitsOnTheWallBehind() {
        let cam = SIMD3<Float>(0.05, 0.35, 0.8)
        var b = box(camera: cam)
        b.hits += [[0.3, 0.2, -1.5], [0.2, 0.25, -1.6], [-0.3, 0.1, -1.4]]  // slipped past the edge
        let e = ObjectSizing.measure(camera: cam, surfaceHits: b.hits, silhouetteRays: b.silhouette, planeY: 0)!
        XCTAssertEqual(e.footprintCentre.z, 0, accuracy: 0.04)
    }

    func testTablePlaneIgnoresPlaneOnTopOfTheItem() {
        let hits: [SIMD3<Float>] = [[0, 0.05, 0], [0, 0.15, 0], [0, 0.29, 0], [0, 0.2, 0.1], [0, 0.1, 0]]
        // ARKit found the table (0), the box lid (0.3), and the floor (−0.75).
        XCTAssertEqual(ObjectSizing.tablePlane(candidates: [0.3, 0, -0.75], surfaceHits: hits), 0)
        XCTAssertNil(ObjectSizing.tablePlane(candidates: [0.3], surfaceHits: hits))
    }

    /// The bug from the cluttered-table test: a low item (a mouse, ~3.5 cm) whose points sit
    /// within a couple of centimetres of the table. The table must still win over the floor.
    func testTablePlaneForLowItem() {
        // Most points bled onto the table around the item; a few are on the item itself.
        let table: [SIMD3<Float>] = (0..<12).map { i in [Float(i) * 0.01, 0.001 + Float(i % 3) * 0.001, 0] }
        let item: [SIMD3<Float>] = (0..<8).map { i in [Float(i) * 0.01, 0.01 + Float(i) * 0.003, 0.02] }
        XCTAssertEqual(ObjectSizing.tablePlane(candidates: [0, -0.75], surfaceHits: table + item), 0)
    }
}

final class FastSharpnessTests: XCTestCase {
    /// The Accelerate path must agree with the plain-Swift reference definition.
    func testMatchesReference() {
        var seed: UInt32 = 12345
        let noisy = GrayImage(width: 64, height: 48, pixels: (0..<(64 * 48)).map { i in
            seed = seed &* 1_103_515_245 &+ 12345
            return UInt8(truncatingIfNeeded: (i % 64) * 3 + Int(seed >> 26))
        })
        let checker = GrayImage(width: 16, height: 16, pixels: (0..<256).map { ($0 % 16 + $0 / 16) % 2 == 0 ? 0 : 255 })
        for img in [noisy, checker] {
            let fast = FastSharpness.measure(img)!
            XCTAssertEqual(fast.sharpness, Sharpness.laplacianVariance(img), accuracy: 1e-3 * max(1, Sharpness.laplacianVariance(img)))
            XCTAssertEqual(fast.meanLuma, Sharpness.meanLuma(img), accuracy: 1e-3)
        }
    }

    func testScalesAPaddedPlane() {
        // 8×4 plane with 4 bytes of row padding, scaled to 4×2: sharpness of a flat image is 0.
        var bytes = [UInt8](repeating: 0, count: 12 * 4)
        for y in 0..<4 { for x in 0..<8 { bytes[y * 12 + x] = 100 } }
        let r = bytes.withUnsafeMutableBytes {
            FastSharpness.measure(base: $0.baseAddress!, width: 8, height: 4, bytesPerRow: 12, thumbWidth: 4, thumbHeight: 3)
        }!
        XCTAssertEqual(r.sharpness, 0, accuracy: 1e-6)
        XCTAssertEqual(r.meanLuma, 100, accuracy: 0.5)
    }
}

final class ObjectFromPointsTests: XCTestCase {
    /// ARKit-style feature points on a 20 × 30 × 20 cm box (front and top faces), plus mask bleed
    /// on the table and a few background strays; silhouette rays as before.
    private func scene(camera cam: SIMD3<Float>) -> (points: [SIMD3<Float>], silhouette: [Ray]) {
        let s = (0...10).map { Float($0) / 10 }
        let front = s.flatMap { u in s.map { v in SIMD3<Float>(-0.1 + 0.2 * u, 0.3 * v, 0.1) } }
        let top = s.flatMap { u in s.map { v in SIMD3<Float>(-0.1 + 0.2 * u, 0.3, 0.1 - 0.2 * v) } }
        let silhouette = (front + top).map { Ray(origin: cam, direction: $0 - cam) }
        var pts = stride(from: 0, to: front.count, by: 4).map { front[$0] } + stride(from: 0, to: top.count, by: 4).map { top[$0] }
        pts += [[-0.05, 0.001, 0.12], [0.06, 0.002, 0.13], [0.0, 0.0, 0.11]]   // table, just in front
        pts += [[0.4, 0.5, -2.0], [-0.3, 0.6, -2.2]]                            // wall far behind
        return (pts, silhouette)
    }

    func testFitsBoxFromSideAndAbove() {
        for cam in [SIMD3<Float>(0.05, 0.35, 0.8), SIMD3<Float>(-0.1, 0.7, 0.45)] {
            let sc = scene(camera: cam)
            let e = ObjectSizing.fromPoints(camera: cam, points: sc.points, silhouetteRays: sc.silhouette, planeY: 0)!
            XCTAssertEqual(e.width, 0.2, accuracy: 0.03, "camera \(cam)")
            XCTAssertEqual(e.height, 0.3, accuracy: 0.02, "camera \(cam)")
            XCTAssertEqual(e.footprintCentre.x, 0, accuracy: 0.03, "camera \(cam)")
            XCTAssertEqual(e.footprintCentre.z, 0, accuracy: 0.04, "camera \(cam)")
            XCTAssertGreaterThanOrEqual(e.depth, 0.15, "camera \(cam)")
        }
    }

    func testNeedsEnoughPoints() {
        let cam = SIMD3<Float>(0.05, 0.35, 0.8)
        let sc = scene(camera: cam)
        XCTAssertNil(ObjectSizing.fromPoints(camera: cam, points: Array(sc.points.prefix(5)), silhouetteRays: sc.silhouette, planeY: 0))
    }
}

final class VisualHullTests: XCTestCase {
    // A mouse-sized box: 11 × 3.5 × 6 cm (x, y, z half-extents below), turned 30°, centred off-origin.
    let boxCentre = SIMD3<Float>(0.03, 0.0175, -0.02)
    let half = SIMD3<Float>(0.055, 0.0175, 0.03)
    let yaw: Float = 30 * .pi / 180
    var boxCentreShift = SIMD3<Float>.zero  // simulated ARKit drift: where the box appears in world space
    let k = simd_float3x3(columns: ([1450, 0, 0], [0, 1450, 0], [960, 720, 1]))

    /// ARKit-style camera at `eye` looking at `target` (+x right, +y up, looking down −z).
    func camera(eye: SIMD3<Float>, target: SIMD3<Float>) -> simd_float4x4 {
        let z = simd_normalize(eye - target)
        let x = simd_normalize(simd_cross(SIMD3<Float>(0, 1, 0), z))
        let y = simd_cross(z, x)
        return simd_float4x4(columns: (SIMD4(x, 0), SIMD4(y, 0), SIMD4(z, 0), SIMD4(eye, 1)))
    }

    /// Exact silhouette: a mask pixel is on the item if its ray hits the box (slab test).
    func mask(_ cam: simd_float4x4, size: Int = 160) -> [UInt8] {
        let r = simd_float3x3(SIMD3(cam.columns.0.x, cam.columns.0.y, cam.columns.0.z),
                              SIMD3(cam.columns.1.x, cam.columns.1.y, cam.columns.1.z),
                              SIMD3(cam.columns.2.x, cam.columns.2.y, cam.columns.2.z))
        let toLocal = simd_float3x3(simd_quatf(angle: -yaw, axis: [0, 1, 0]))
        let o = toLocal * (cam.translation - (boxCentre + boxCentreShift))
        var m = [UInt8](repeating: 0, count: size * size)
        for my in 0..<size {
            for mx in 0..<size {
                let u = (Float(my) + 0.5) / Float(size) * 1920, v = (1 - (Float(mx) + 0.5) / Float(size)) * 1440
                let d = toLocal * (r * SIMD3((u - 960) / 1450, -(v - 720) / 1450, -1))
                var tmin: Float = -1e9, tmax: Float = 1e9
                for a in 0..<3 {
                    if abs(d[a]) < 1e-9 { if abs(o[a]) > half[a] { tmin = 1; tmax = 0 }; continue }
                    let t1 = (-half[a] - o[a]) / d[a], t2 = (half[a] - o[a]) / d[a]
                    tmin = max(tmin, min(t1, t2)); tmax = min(tmax, max(t1, t2))
                }
                if tmax >= max(tmin, 0) { m[my * size + mx] = 1 }
            }
        }
        return m
    }

    func testRecoversCentreFromAWrongStart() {
        // Start 3 cm off with the wrong size, like the single-view guess on the real mouse.
        let guess = ObjectEstimate(footprintCentre: [0.03 + 0.03, 0, -0.02 - 0.01], width: 0.08, height: 0.03, depth: 0.08)
        var hull = VisualHull(around: guess, planeY: 0)
        for i in 0..<8 {
            let az = Float(i) * .pi / 4
            let eye = boxCentre + SIMD3(0.3 * sin(az), 0.25, 0.3 * cos(az))
            let cam = camera(eye: eye, target: boxCentre)
            hull.carve(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                      mask: mask(cam), maskWidth: 160, maskHeight: 160))
        }
        let e = hull.estimate()!
        XCTAssertEqual(e.footprintCentre.x, 0.03, accuracy: 0.005)
        XCTAssertEqual(e.footprintCentre.z, -0.02, accuracy: 0.005)
        // Height is an upper bound when every view looks down (space just above a flat top projects
        // onto the top face in all of them). The ring sits on the table and only needs the footprint.
        XCTAssertGreaterThanOrEqual(e.height, 0.03)
        XCTAssertLessThanOrEqual(e.height, 0.06)
        XCTAssertEqual(max(e.width, e.depth), 0.11, accuracy: 0.015)
        XCTAssertEqual(min(e.width, e.depth), 0.06, accuracy: 0.015)
        XCTAssertGreaterThan(hull.spreadDegrees, 170)
    }

    func testRejectsAWrongMask() {
        let guess = ObjectEstimate(footprintCentre: [0.06, 0, -0.03], width: 0.08, height: 0.03, depth: 0.08)
        var hull = VisualHull(around: guess, planeY: 0)
        func view(_ az: Float, mask m: [UInt8]? = nil) -> SilhouetteView {
            let cam = camera(eye: boxCentre + SIMD3(0.3 * sin(az), 0.25, 0.3 * cos(az)), target: boxCentre)
            return SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                  mask: m ?? mask(cam), maskWidth: 160, maskHeight: 160)
        }
        for i in 0..<6 { XCTAssertTrue(hull.carveIfConsistent(view(Float(i) * .pi / 3))) }
        let good = hull.estimate()!
        // A mask of something else entirely (a blob in the image corner) must be refused…
        var wrong = [UInt8](repeating: 0, count: 160 * 160)
        for y in 0..<30 { for x in 0..<30 { wrong[y * 160 + x] = 1 } }
        XCTAssertFalse(hull.carveIfConsistent(view(0.5, mask: wrong)))
        XCTAssertEqual(hull.estimate()!.footprintCentre.x, good.footprintCentre.x, accuracy: 1e-6)
        // …while a correct new view is accepted.
        XCTAssertTrue(hull.carveIfConsistent(view(0.5)))
    }

    /// What happened on the cluttered table: ARKit's world slid ~3–4 cm during the lap. Simulated by
    /// moving the box 3 cm partway round while the cameras keep their poses. The tracker must follow.
    func testTrackerFollowsDrift() {
        let guess = ObjectEstimate(footprintCentre: [0.06, 0, -0.03], width: 0.08, height: 0.03, depth: 0.08)
        var tracker = ItemTracker(start: guess, planeY: 0)
        var global = VisualHull(around: guess, planeY: 0)
        let original = boxCentre
        for i in 0..<20 {
            let az = Float(i) * .pi / 8
            if i == 10 { boxCentreShift = SIMD3(0.03, 0, 0) }  // the drift
            let target = original + boxCentreShift
            let cam = camera(eye: target + SIMD3(0.3 * sin(az), 0.25, 0.3 * cos(az)), target: target)
            let v = SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                   mask: mask(cam), maskWidth: 160, maskHeight: 160)
            tracker.add(v)
            global.carve(v)
        }
        boxCentreShift = .zero
        let e = tracker.estimate
        XCTAssertEqual(e.footprintCentre.x, 0.06, accuracy: 0.006, "tracker should be at the drifted position")
        XCTAssertEqual(e.footprintCentre.z, -0.02, accuracy: 0.006)
        XCTAssertEqual(max(e.width, e.depth), 0.11, accuracy: 0.02, "size should survive the drift")
        // The all-views hull is what the app did before: it shrinks.
        if let g = global.estimate() { XCTAssertLessThan(max(g.width, g.depth), 0.095) }
    }

    func testTrackerRefusesAnotherObjectOnceTracking() {
        let guess = ObjectEstimate(footprintCentre: [0.03, 0, -0.02], width: 0.1, height: 0.04, depth: 0.08)
        var tracker = ItemTracker(start: guess, planeY: 0)
        for i in 0..<8 {
            let az = Float(i) * .pi / 4
            let cam = camera(eye: boxCentre + SIMD3(0.3 * sin(az), 0.25, 0.3 * cos(az)), target: boxCentre)
            tracker.add(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                       mask: mask(cam), maskWidth: 160, maskHeight: 160))
        }
        XCTAssertGreaterThan(tracker.updates, 0)
        let before = tracker.estimate
        var wrong = [UInt8](repeating: 0, count: 160 * 160)
        for y in 0..<30 { for x in 0..<30 { wrong[y * 160 + x] = 1 } }
        let cam = camera(eye: boxCentre + SIMD3(0.2, 0.25, 0.2), target: boxCentre)
        XCTAssertFalse(tracker.add(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                                  mask: wrong, maskWidth: 160, maskHeight: 160)))
        XCTAssertEqual(tracker.estimate, before)
    }

    func testTwoCloseViewsDontPretendToKnowDepth() {
        let guess = ObjectEstimate(footprintCentre: [0.03, 0, -0.02], width: 0.1, height: 0.04, depth: 0.1)
        var hull = VisualHull(around: guess, planeY: 0)
        for az: Float in [0, 0.1] {
            let cam = camera(eye: boxCentre + SIMD3(0.3 * sin(az), 0.25, 0.3 * cos(az)), target: boxCentre)
            hull.carve(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: 1920, sensorHeight: 1440,
                                      mask: mask(cam), maskWidth: 160, maskHeight: 160))
        }
        XCTAssertLessThan(hull.spreadDegrees, 10)  // the app waits for more spread before trusting it
    }
}

final class TurntableTests: XCTestCase {
    /// Corners of a Letter sheet (27.9 × 21.6 cm) centred at `c`, long edges at `yaw`, slightly shuffled.
    private func sheet(_ c: SIMD3<Float>, yaw: Float, noise: Float = 0) -> [SIMD3<Float>] {
        let l = SIMD3<Float>(sin(yaw), 0, cos(yaw)), s = SIMD3<Float>(cos(yaw), 0, -sin(yaw))
        let pts = [c + l * 0.1395 + s * 0.108, c - l * 0.1395 + s * 0.108, c - l * 0.1395 - s * 0.108, c + l * 0.1395 - s * 0.108]
        return [pts[2], pts[0], pts[3], pts[1]].enumerated().map { i, p in p + SIMD3(noise * Float(i % 2 == 0 ? 1 : -1), 0, noise) }
    }

    func testPoseFromCorners() {
        for deg: Float in [0, 17, 45, 89, 91, 135, 179] {
            let yaw = deg * .pi / 180
            let p = Turntable.pose(corners: sheet([0.3, -0.17, 0.1], yaw: yaw))!
            XCTAssertEqual(p.centre.x, 0.3, accuracy: 1e-4)
            XCTAssertEqual(p.centre.z, 0.1, accuracy: 1e-4)
            XCTAssertEqual(p.long, 0.279, accuracy: 1e-3)
            XCTAssertEqual(p.short, 0.216, accuracy: 1e-3)
            let d = abs(Turntable.unwrap(p.yaw, near: yaw) - yaw)
            XCTAssertLessThan(d, 1e-3, "yaw \(deg)°")
        }
    }

    func testCornerNoiseCostsUnderADegree() {
        // 3 mm of corner error (a few pixels at arm's length) on a sheet.
        let p = Turntable.pose(corners: sheet([0, 0, 0], yaw: 0.6, noise: 0.003))!
        XCTAssertLessThan(abs(Turntable.unwrap(p.yaw, near: 0.6) - 0.6) * 180 / .pi, 1.0)
    }

    func testRejectsNonSheets() {
        // A square (90° ambiguous), a trapezoid, and three points.
        let sq: [SIMD3<Float>] = [[0, 0, 0], [0.2, 0, 0], [0.2, 0, 0.2], [0, 0, 0.2]]
        let trap: [SIMD3<Float>] = [[0, 0, 0], [0.3, 0, 0], [0.25, 0, 0.2], [0.05, 0, 0.2]]
        XCTAssertNil(Turntable.pose(corners: sq))
        XCTAssertNil(Turntable.pose(corners: trap))
        XCTAssertNil(Turntable.pose(corners: Array(sq.prefix(3))))
    }

    func testUnwrapFollowsAFullTurn() {
        // Reads every 20° over two full turns; raw yaw is only known mod π.
        var cont: Float = 0.3
        for step in 1...36 {
            let truth = 0.3 + Float(step) * 20 * .pi / 180
            var raw = truth.truncatingRemainder(dividingBy: .pi)
            if raw < 0 { raw += .pi }
            cont = Turntable.unwrap(raw, near: cont)
            XCTAssertEqual(cont, truth, accuracy: 1e-4)
        }
    }

    func testCameraInItemFrame() {
        // Item turned 90° and slid 5 cm. A camera that hasn't moved now sees the item from 90° round.
        let start = PaperPose(centre: [0, 0, 0], yaw: 0, long: 0.28, short: 0.22)
        let now = PaperPose(centre: [0.05, 0, 0], yaw: .pi / 2, long: 0.28, short: 0.22)
        let m = Turntable.motion(from: start, startYaw: 0, to: now, nowYaw: .pi / 2)
        // A point on the item that started 10 cm along +Z is now 10 cm along +X from the new centre.
        let moved = m * SIMD4<Float>(0, 0, 0.1, 1)
        XCTAssertEqual(moved.x, 0.15, accuracy: 1e-5)
        XCTAssertEqual(moved.z, 0, accuracy: 1e-5)
        var cam = matrix_identity_float4x4
        cam.columns.3 = [0.05, 0.3, 0.4, 1]  // above and in front (+Z) of the item's new spot
        let inItem = Turntable.cameraInItemFrame(camera: cam, itemMotion: m)
        let p = Dome.position(camera: inItem.translation, anchor: .zero)
        XCTAssertEqual(p.azimuthDeg, 270, accuracy: 0.01)  // the item's −X side faces the camera now
    }
}

final class PaperTrackerTests: XCTestCase {
    let long: Float = 0.27, short: Float = 0.20

    /// A table map with a sheet at `yaw` centred at `c`, a dark item on it, optionally a hand over
    /// one long edge and a strip the camera can't see.
    func map(yaw: Float, c: SIMD2<Float>, hand: Bool = false, blind: Bool = false) -> TableMap {
        var m = TableMap(centre: [0, 0], halfSize: 0.25, res: 0.0025)
        let l = SIMD2<Float>(sin(yaw), cos(yaw)), s = SIMD2<Float>(cos(yaw), -sin(yaw))
        let handAt = c + s * (short / 2)
        for r in 0..<m.n {
            for k in 0..<m.n {
                let p = m.cell(r, k), d = p - c, i = r * m.n + k
                m.valid[i] = blind && p.x > 0.2 ? 0 : 1
                let onPaper = abs(simd_dot(d, l)) <= long / 2 && abs(simd_dot(d, s)) <= short / 2
                (m.luma[i], m.chroma[i]) = onPaper ? (240, 2) : (210, 25)
                if simd_length(d) < 0.04 { (m.luma[i], m.chroma[i]) = (40, 3) }                 // the item
                if hand && simd_length(p - handAt) < 0.05 { (m.luma[i], m.chroma[i]) = (170, 45) } // a hand
            }
        }
        return m
    }

    func angleErrorDeg(_ a: Float, _ b: Float) -> Float {
        var d = (a - b).truncatingRemainder(dividingBy: .pi / 2)
        if d > .pi / 4 { d -= .pi / 2 }
        if d < -.pi / 4 { d += .pi / 2 }
        return abs(d) * 180 / .pi
    }

    func testReadsAngleAndSize() {
        for deg: Float in [0, 10, 37.3, 45, 80, 95, 133, 170] {
            let yaw = deg * .pi / 180
            let r = PaperDetector.read(map(yaw: yaw, c: [0.01, -0.02]), near: [0.01, -0.02])!
            XCTAssertLessThan(angleErrorDeg(r.angleMod90, yaw), 0.8, "yaw \(deg)°")
            let sizes = [r.uMax - r.uMin, r.vMax - r.vMin].sorted()
            XCTAssertEqual(sizes[1], long, accuracy: 0.012, "yaw \(deg)°")
            XCTAssertEqual(sizes[0], short, accuracy: 0.012, "yaw \(deg)°")
            XCTAssertGreaterThanOrEqual(r.confidence, 0.3)  // the follower's minimum
        }
    }

    func testHandAndBlindSpot() {
        let yaw: Float = 0.5
        let r = PaperDetector.read(map(yaw: yaw, c: [0.02, 0], hand: true, blind: true), near: [0.02, 0])!
        XCTAssertLessThan(angleErrorDeg(r.angleMod90, yaw), 1.5)
    }

    func testFollowsTwoLapsWithSlide() {
        var f = PaperFollower()
        let startYaw: Float = 0.3
        for step in 0...60 {
            let truth = startYaw + Float(step) * 12 * .pi / 180          // 12° per reading, 720° total
            let c = SIMD2<Float>(0.01 * sin(Float(step) / 9), 0.008 * cos(Float(step) / 7))  // a little slide
            let r = PaperDetector.read(map(yaw: truth, c: c, hand: step % 3 == 0), near: c)!
            let pose = f.update(r)
            XCTAssertNotNil(pose, "step \(step)")
            if let pose {
                XCTAssertEqual(pose.yaw, truth, accuracy: 1.5 * .pi / 180, "step \(step): yaw must stay continuous")
                XCTAssertEqual(pose.centre.x, c.x, accuracy: 0.008, "step \(step)")
                XCTAssertEqual(pose.centre.z, c.y, accuracy: 0.008, "step \(step)")
            }
        }
        XCTAssertEqual(f.turned, 720 * .pi / 180, accuracy: 1.5 * .pi / 180)
        XCTAssertEqual(f.long, long, accuracy: 0.012)
        XCTAssertEqual(f.short, short, accuracy: 0.012)
    }
}

extension PaperTrackerTests {
    func testRestartKeepsSheetButResetsStart() {
        var f = PaperFollower()
        for step in 0..<5 {
            let yaw = 0.2 + Float(step) * 0.2
            f.update(PaperDetector.read(map(yaw: yaw, c: .zero), near: .zero)!)
        }
        let knownLong = f.long
        f.restart()
        XCTAssertNil(f.start)
        // Next reading has a hand over the sheet: still accepted (continuity), and it becomes the start.
        let pose = f.update(PaperDetector.read(map(yaw: 1.2, c: .zero, hand: true), near: .zero)!)
        XCTAssertNotNil(pose)
        XCTAssertEqual(f.turned, 0, accuracy: 1e-6)
        XCTAssertEqual(f.long, knownLong, accuracy: 0.01)
    }
}

final class ItemOnPaperTests: XCTestCase {
    /// A beige table, a tilted ruled sheet (lines run edge to edge), a dark item on it with a soft
    /// shadow, a hand reaching onto the sheet's edge, and a knee in the corner of the frame.
    func scene() -> ImageGrid {
        let w = 160, h = 120
        var luma = [UInt8](repeating: 180, count: w * h), chroma = [UInt8](repeating: 42, count: w * h)
        let c = SIMD2<Float>(80, 55), a: Float = 0.35
        let u = SIMD2<Float>(cos(a), sin(a)), v = SIMD2<Float>(-sin(a), cos(a))
        for y in 0..<h {
            for x in 0..<w {
                let p = SIMD2<Float>(Float(x), Float(y)), d = p - c, i = y * w + x
                let pu = simd_dot(d, u), pv = simd_dot(d, v)
                if abs(pu) < 45 && abs(pv) < 34 {
                    (luma[i], chroma[i]) = (232, 3)                                            // paper
                    if Int(pv + 100) % 7 == 0 { (luma[i], chroma[i]) = (190, 30) }             // ruled line, edge to edge
                }
                if simd_length(d / SIMD2(14, 9)) < 1 { (luma[i], chroma[i]) = (35, 4) }       // the item
                else if simd_length((d - SIMD2(3, 4)) / SIMD2(17, 12)) < 1, luma[i] > 200 { luma[i] = 160 }  // shadow
                if simd_length(p - (c + u * 45)) < 9 { (luma[i], chroma[i]) = (150, 60) }    // hand on the sheet's edge
                if simd_length(p - SIMD2(15, 110)) < 20 { (luma[i], chroma[i]) = (40, 8) }   // knee
            }
        }
        return ImageGrid(width: w, height: h, luma: luma, chroma: chroma)
    }

    func testFindsTheItemNotTheHandLinesOrKnee() {
        let g = scene()
        let r = ItemOnPaper.segment(g)!
        var sx = 0, sy = 0, n = 0
        for y in 0..<g.height { for x in 0..<g.width where r.item[y * g.width + x] != 0 { sx += x; sy += y; n += 1 } }
        XCTAssertEqual(Float(sx) / Float(n), 80, accuracy: 2.5, "item centre x")
        XCTAssertEqual(Float(sy) / Float(n), 55, accuracy: 2.5, "item centre y")
        // The item (π·14·9 ≈ 396 px) plus at most a little shadow; never the hand, lines or knee.
        XCTAssertGreaterThan(n, 380)
        XCTAssertLessThan(n, 700)
        XCTAssertEqual(r.item[110 * g.width + 15], 0, "knee")
    }

    func testNoPaperNoAnswer() {
        let g = ImageGrid(width: 40, height: 30, luma: .init(repeating: 180, count: 1200), chroma: .init(repeating: 42, count: 1200))
        XCTAssertNil(ItemOnPaper.segment(g))
    }
}

final class PaperTurnTests: XCTestCase {
    private func reading(_ deg: Float, confidence: Float = 0.6) -> SheetAngle.Reading {
        var a = (deg * .pi / 180).truncatingRemainder(dividingBy: .pi / 2)
        if a < 0 { a += .pi / 2 }
        return SheetAngle.Reading(angleMod90: a, confidence: confidence, samples: 500)
    }

    func testUnwrapsTwoLapsBothWays() {
        for dir: Float in [1, -1] {
            var turn = PaperTurn()
            // Two laps in 20 s read at 7.5 Hz: 4.8° per read, across every 90° wrap.
            for i in 0...150 { turn.update(reading(10 + dir * Float(i) * 4.8), time: Double(i) / 7.5) }
            XCTAssertEqual(turn.turned * 180 / .pi, dir * 720, accuracy: 0.01)
        }
    }

    func testIgnoresUnsureAndImpossibleReadings() {
        var turn = PaperTurn()
        turn.update(reading(20), time: 0)
        XCTAssertFalse(turn.update(reading(60, confidence: 0.1), time: 0.13))   // unsure
        XCTAssertFalse(turn.update(reading(55), time: 0.13))                    // 35° in 0.13 s: a hand, not the paper
        XCTAssertTrue(turn.update(reading(24), time: 0.26))
        XCTAssertEqual(turn.turned * 180 / .pi, 4, accuracy: 0.01)
    }

    func testRestartMakesNowTheStart() {
        var turn = PaperTurn()
        for i in 0...10 { turn.update(reading(Float(i) * 3), time: Double(i) / 7.5) }
        turn.restart()
        XCTAssertEqual(turn.turned, 0)
        turn.update(reading(33), time: 11 / 7.5)
        XCTAssertEqual(turn.turned * 180 / .pi, 3, accuracy: 0.01)
    }
}

final class TurnCoverageTests: XCTestCase {
    /// Turns the item `degrees` over `seconds` at a fixed elevation, observed at 7.5 Hz.
    private func turn(_ c: inout TurnCoverage, from start: Float, by degrees: Float, seconds: Double, elevationDeg: Float) {
        let n = Int(seconds * 7.5)
        for i in 1...n {
            c.observe(turned: (start + degrees * Float(i) / Float(n)) * .pi / 180, elevation: elevationDeg * .pi / 180, dt: 1 / 7.5)
        }
    }

    func testOneLapAtOneHeightIsHalf() {
        var c = TurnCoverage()
        c.observe(turned: 0, elevation: 0.9, dt: 0)
        turn(&c, from: 0, by: 370, seconds: 10, elevationDeg: 0.9 * 180 / .pi)
        XCTAssertEqual(c.percent, 50)
        XCTAssertTrue(c.arcs(band: 0, count: 12).allSatisfy { $0 >= 0.999 })
        XCTAssertTrue(c.arcs(band: 1, count: 12).allSatisfy { $0 == 0 })
    }

    func testTwoLapsAtTwoHeightsIsFull() {
        for dir: Float in [1, -1] {
            var c = TurnCoverage()
            turn(&c, from: 0, by: dir * 370, seconds: 10, elevationDeg: 55)
            turn(&c, from: dir * 370, by: dir * 370, seconds: 10, elevationDeg: 30)   // lower, as the demo does
            XCTAssertEqual(c.percent, 100)
        }
    }

    func testStandingStillOnlyCoversTheFront() {
        var c = TurnCoverage()
        for _ in 0..<150 { c.observe(turned: 0, elevation: 0.9, dt: 1 / 7.5) }
        XCTAssertEqual(c.level(side: 0), 1, accuracy: 0.001 + 0.5)   // both heights averaged: half
        XCTAssertEqual(c.level(side: .pi), 0)                          // the back was never seen
        XCTAssertLessThan(c.percent, 25)
    }

    func testPercentNeverDropsAndOnlyCountsMeasuredTime() {
        var c = TurnCoverage()
        var last = 0
        for i in 0..<300 {
            c.observe(turned: Float(i) * 0.02, elevation: 0.9, dt: 1 / 7.5)
            XCTAssertGreaterThanOrEqual(c.percent, last)
            last = c.percent
        }
        // A long gap (paper lost) counts at most 0.25 s.
        var gap = TurnCoverage()
        gap.observe(turned: 0, elevation: 0.9, dt: 30)
        XCTAssertEqual(gap.level(side: 0), 0.125, accuracy: 0.01)
    }

    func testSidesSeenAcrossTheSilhouette() {
        var c = TurnCoverage()
        c.observe(turned: 0.5, elevation: 0.9, dt: 0)
        XCTAssertEqual(c.side(atOffset: 0), -0.5, accuracy: 1e-6)          // the middle faces the camera
        XCTAssertEqual(c.side(atOffset: 1), -0.5 - .pi / 2, accuracy: 1e-6) // the right edge: a quarter turn anticlockwise
        XCTAssertEqual(c.side(atOffset: -1), -0.5 + .pi / 2, accuracy: 1e-6)
    }
}
