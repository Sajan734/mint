import XCTest
import simd
@testable import CoverageKit

/// Camera pose at a dome position around the origin (rotation only matters for angular speed).
private func pose(azDeg: Float, elDeg: Float, dist: Float = 0.5, yawDeg: Float = 0) -> simd_float4x4 {
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
            (SegmentID(az: 0, el: 0), "az000_el20"),
            (SegmentID(az: 3, el: 0), "az090_el20"),
            (SegmentID(az: 11, el: 1), "az330_el50"),
        ]
        for (seg, name) in cases { XCTAssertEqual(seg.name, name) }
        XCTAssertEqual(Dome.segmentCount, 24)
        XCTAssertEqual(Dome.segmentsToComplete, 22)
        XCTAssertEqual(Set(Dome.allSegments.map(\.name)).count, 24)
    }

    func testPositionToSegment() {
        let cases: [(SIMD3<Float>, SegmentID?)] = [
            ([0, 0.1, 1], SegmentID(az: 0, el: 0)),       // +Z, low
            ([1, 0.1, 0], SegmentID(az: 3, el: 0)),       // +X = 90°
            ([0, 0.1, -1], SegmentID(az: 6, el: 0)),      // 180°
            ([-1, 0.1, 0], SegmentID(az: 9, el: 0)),      // 270°
            ([-0.001, 0.1, 1], SegmentID(az: 11, el: 0)), // just under 360°
            ([0, 1.2, 1], SegmentID(az: 0, el: 1)),       // ~50°
            ([0, 5, 1], nil),                             // ~79°, above the top ring
            ([0, 0.01, 1], nil),                          // ~0.6°, below the low ring
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
        let a = pose(azDeg: 0, elDeg: 20, yawDeg: 0)
        let b = pose(azDeg: 0, elDeg: 20, yawDeg: 90)
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
        let d1 = t.observe(obs(pose(azDeg: 100, elDeg: 20), t: 0))
        XCTAssertNil(d1.issue)
        XCTAssertTrue(d1.filledNewSegment)
        XCTAssertEqual(d1.segment, SegmentID(az: 3, el: 0))

        // Same segment again, not sharper: no new fill, not a better keyframe.
        let d2 = t.observe(obs(pose(azDeg: 105, elDeg: 20), t: 0.1))
        XCTAssertFalse(d2.filledNewSegment)
        XCTAssertFalse(d2.isBestForSegment)

        // 90° of rotation in 0.1 s is too fast.
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 0.2)).issue, .tooFast)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 20, dist: 3, yawDeg: 90), t: 1.0)).issue, .tooFar)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 20, dist: 0.05, yawDeg: 90), t: 1.5)).issue, .tooClose)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 80, yawDeg: 90), t: 2.0)).issue, .tooHigh)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 1, yawDeg: 90), t: 2.5)).issue, .tooLow)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 3.0, luma: 10)).issue, .tooDark)
        XCTAssertEqual(t.observe(obs(pose(azDeg: 140, elDeg: 20, yawDeg: 90), t: 3.5, tracking: false)).issue, .trackingLimited)
        XCTAssertEqual(t.coveragePct, 4)  // 1 of 24
    }

    func testCompletesAt22Segments() {
        var t = CoverageTracker(anchor: .zero)
        var time = 0.0
        for seg in Dome.allSegments.prefix(21) {
            time += 1
            let az = Float(seg.az * Dome.azimuthStepDeg) + 15
            _ = t.observe(obs(pose(azDeg: az, elDeg: Float(Dome.bands[seg.el].centreDeg)), t: time))
        }
        XCTAssertEqual(t.filled.count, 21)
        XCTAssertFalse(t.isComplete)
        _ = t.observe(obs(pose(azDeg: 15 + 30 * 9, elDeg: 50), t: time + 1))
        XCTAssertTrue(t.isComplete)
        XCTAssertEqual(t.coveragePct, 91)
    }
}

final class GuidanceTests: XCTestCase {
    private func at(_ az: Float, _ el: Float) -> DomePosition {
        Dome.position(camera: pose(azDeg: az, elDeg: el).translation, anchor: .zero)
    }

    func testHints() {
        let lowRing = Set((0..<12).map { SegmentID(az: $0, el: 0) })
        let highRing = Set((0..<12).map { SegmentID(az: $0, el: 1) })
        let lowMissing2And9 = lowRing.subtracting([SegmentID(az: 2, el: 0), SegmentID(az: 9, el: 0)])
        let cases: [(DomePosition, Set<SegmentID>, Hint)] = [
            (at(15, 20), [], .holdHere),
            (at(15, 20), [SegmentID(az: 0, el: 0)], .walkRight(segments: 1)),  // tie between bins 11 and 1 → right
            (at(15, 20), lowMissing2And9, .walkRight(segments: 2)),
            (at(255, 20), lowMissing2And9, .walkRight(segments: 1)),           // bin 8 → bin 9
            (at(345, 20), lowMissing2And9, .walkLeft(segments: 2)),            // bin 11: bin 9 is 2 left, bin 2 is 3 right
            (at(15, 20), lowRing, .raise),
            (at(15, 50), highRing, .lower),
            (at(15, 2), [], .raise),
            (at(15, 80), [], .lower),
            (at(15, 20), Set(Dome.allSegments.prefix(22)), .done),
        ]
        for (i, (p, filled, expected)) in cases.enumerated() {
            XCTAssertEqual(Guidance.hint(position: p, filled: filled), expected, "case \(i)")
        }
    }
}
