// Runs the app's paper tracker (TableMap + PaperDetector + PaperFollower, CoverageKit) on a
// turntable recording, on the Mac: the top-down map is resampled from each video frame with its
// recorded ARKit pose, exactly as the phone does from the camera image.
//
//   swiftc -O -parse-as-library -module-name CoverageKit -emit-library -emit-module -o libCoverageKit.dylib \
//       ../ios/Packages/CoverageKit/Sources/CoverageKit/*.swift
//   swiftc -O -I . -L . -lCoverageKit paper_check.swift -o paper_check
//   DYLD_LIBRARY_PATH=. ./paper_check /path/to/unzipped/scan
// Writes paper.jsonl (frame, tracked, turned_deg, confidence, centre) into the scan folder.
import AVFoundation
import CoverageKit
import Foundation
import simd

func rowMajor4(_ a: [[Double]]) -> simd_float4x4 {
    simd_float4x4(rows: (0..<4).map { r in SIMD4<Float>((0..<4).map { Float(a[r][$0]) }) })
}

func rowMajor3(_ a: [[Double]]) -> simd_float3x3 {
    simd_float3x3(rows: (0..<3).map { r in SIMD3<Float>((0..<3).map { Float(a[r][$0]) }) })
}

let dir = URL(fileURLWithPath: CommandLine.arguments[1])
let capture = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("capture.json"))) as! [String: Any]
let item = capture["item"] as! [String: Any]
let planeY = Float(item["plane_y"] as! Double)
let base = (item["footprint_centre"] as! [Double]).map(Float.init)
let near = SIMD2(base[0], base[2])
let poses = try String(contentsOf: dir.appendingPathComponent("poses.jsonl"), encoding: .utf8)
    .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }

let asset = AVURLAsset(url: dir.appendingPathComponent("video.mp4"))
let track = try await asset.loadTracks(withMediaType: .video)[0]
let reader = try AVAssetReader(asset: asset)
let out = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(out)
reader.startReading()

var follower = PaperFollower()
// End-to-end replay of what the app does in turntable mode: paper motion → camera in the item's
// frame → coverage. (Sharpness isn't re-measured here: geometry only.)
let centre = (item["centre"] as! [Double]).map(Float.init)
var coverage = CoverageTracker(anchor: SIMD3(centre[0], centre[1], centre[2]))
var fills: [(Int, String)] = []
var lines: [String] = []
var tracked = 0, total = 0
var ms: Double = 0
var i = 0
while let sample = out.copyNextSampleBuffer(), let pb = CMSampleBufferGetImageBuffer(sample) {
    defer { i += 1 }
    guard i < poses.count else { continue }
    total += 1
    let cam = rowMajor4(poses[i]["pose_world"] as! [[Double]])
    let k = rowMajor3(poses[i]["intrinsics"] as! [[Double]])
    let w2c = cam.inverse
    CVPixelBufferLockBaseAddress(pb, .readOnly)
    let W = CVPixelBufferGetWidth(pb), H = CVPixelBufferGetHeight(pb), bpr = CVPixelBufferGetBytesPerRow(pb)
    let px = CVPixelBufferGetBaseAddress(pb)!.assumingMemoryBound(to: UInt8.self)
    let t0 = Date()
    var map = TableMap(centre: near, halfSize: 0.25, res: 0.0025)
    map.fill(planeY: planeY) { p in
        let c = w2c * SIMD4(p, 1)
        guard c.z < -0.02 else { return nil }
        let u = k[0][0] * c.x / -c.z + k[2][0], v = k[1][1] * -c.y / -c.z + k[2][1]
        let x = Int(u), y = Int(v)
        guard x >= 0, y >= 0, x < W, y < H else { return nil }
        let o = y * bpr + x * 4
        let b = Int(px[o]), g = Int(px[o + 1]), r = Int(px[o + 2])
        let luma = (299 * r + 587 * g + 114 * b) / 1000
        return (UInt8(luma), UInt8(max(r, g, b) - min(r, g, b)))
    }
    CVPixelBufferUnlockBaseAddress(pb, .readOnly)
    var line = "{\"frame\":\(i),\"tracked\":false}"
    if let reading = PaperDetector.read(map, near: near), let pose = follower.update(reading) {
        tracked += 1
        if let m = follower.motion(planeY: planeY) {
            let camInItem = Turntable.cameraInItemFrame(camera: cam, itemMotion: m)
            let d = coverage.observe(FrameObservation(cameraTransform: camInItem, timestamp: Double(i) / 30,
                                                      trackingNormal: true, sharpness: 100, meanLuma: 120))
            if d.filledNewSegment, let seg = d.segment { fills.append((i, seg.name)) }
        }
        line = String(format: "{\"frame\":%d,\"tracked\":true,\"turned_deg\":%.3f,\"confidence\":%.3f,\"cx\":%.4f,\"cz\":%.4f,\"long\":%.4f,\"short\":%.4f}",
                      i, follower.turned * 180 / .pi, reading.confidence, pose.centre.x, pose.centre.z, pose.long, pose.short)
    }
    ms += -t0.timeIntervalSinceNow * 1000
    lines.append(line)
}
try lines.joined(separator: "\n").write(to: dir.appendingPathComponent("paper.jsonl"), atomically: true, encoding: .utf8)
print("coverage replay: \(coverage.filled.count)/\(Dome.segmentCount) segments (\(coverage.coveragePct)%), filled at: " +
      fills.map { String(format: "%@ %.1fs", $0.1, Double($0.0) / 30) }.joined(separator: ", "))
print("tracked \(tracked)/\(total) frames; total turn \(String(format: "%.1f", follower.turned * 180 / .pi))°; sheet \(String(format: "%.3f × %.3f", follower.long, follower.short)) m; \(String(format: "%.1f", ms / Double(total))) ms/frame on this Mac")
