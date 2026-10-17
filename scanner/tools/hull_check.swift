// Runs the app's multi-view refinement (VisualHull) on a recorded scan, on the Mac, with the same
// Vision segmentation the phone uses. Shows how the item estimate moves as views accumulate, and
// writes refined.json into the scan folder so check_scan.py can draw it (--centre-from refined.json).
//
//   swiftc -O -parse-as-library -module-name CoverageKit -emit-library -emit-module -o libCoverageKit.dylib \
//       ../ios/Packages/CoverageKit/Sources/CoverageKit/*.swift
//   swiftc -O -I . -L . -lCoverageKit hull_check.swift -o hull_check
//   DYLD_LIBRARY_PATH=. ./hull_check /path/to/unzipped/scan [every_nth_frame=10]
import AVFoundation
import CoverageKit
import Foundation
import Vision
import simd

func rowMajor4(_ a: [[Double]]) -> simd_float4x4 {
    simd_float4x4(rows: (0..<4).map { r in SIMD4<Float>((0..<4).map { Float(a[r][$0]) }) })
}

func rowMajor3(_ a: [[Double]]) -> simd_float3x3 {
    simd_float3x3(rows: (0..<3).map { r in SIMD3<Float>((0..<3).map { Float(a[r][$0]) }) })
}

let args = CommandLine.arguments
guard args.count >= 2 else { print("usage: hull_check scan_dir [nth]"); exit(1) }
let dir = URL(fileURLWithPath: args[1])
let nth = args.count > 2 ? Int(args[2])! : 10

let capture = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("capture.json"))) as! [String: Any]
let item = capture["item"] as! [String: Any]
let size = (item["size_m"] as! [Double]).map(Float.init)
let base = (item["footprint_centre"] as! [Double]).map(Float.init)
let planeY = Float(item["plane_y"] as! Double)
let start = ObjectEstimate(footprintCentre: SIMD3(base[0], base[1], base[2]), width: size[0], height: size[1], depth: size[2])
let poses = try String(contentsOf: dir.appendingPathComponent("poses.jsonl"), encoding: .utf8)
    .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }

// Decode the video in order (frame i ↔ poses line i).
let asset = AVURLAsset(url: dir.appendingPathComponent("video.mp4"))
let track = try await asset.loadTracks(withMediaType: .video)[0]
let reader = try AVAssetReader(asset: asset)
let out = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(out)
reader.startReading()

var hull = VisualHull(around: start, planeY: planeY)
// Sliding window: a hull from only the last few accepted views, to see if early and late views disagree (drift).
let windowSize = Int(ProcessInfo.processInfo.environment["HULL_WINDOW"] ?? "8")!
var recent: [SilhouetteView] = []
var tracker = ItemTracker(start: start, planeY: planeY)
var allViews: [(frame: Int, view: SilhouetteView)] = []
var trackedLines: [String] = []
var current = start
print("start: base (\(start.footprintCentre.x), \(start.footprintCentre.z)) w \(start.width) d \(start.depth) h \(start.height)")
var i = 0
while let sample = out.copyNextSampleBuffer(), let pb = CMSampleBufferGetImageBuffer(sample) {
    defer { i += 1 }
    guard i % nth == 0, i < poses.count, let poseRows = poses[i]["pose_world"] as? [[Double]] else { continue }
    let cam = rowMajor4(poseRows)
    let k = rowMajor3(poses[i]["intrinsics"] as! [[Double]])
    let w = Float(CVPixelBufferGetWidth(pb)), h = Float(CVPixelBufferGetHeight(pb))

    let req = VNGenerateForegroundInstanceMaskRequest()
    try VNImageRequestHandler(cvPixelBuffer: pb, orientation: .right).perform([req])
    guard let obs = req.results?.first else { continue }
    let m = obs.instanceMask
    CVPixelBufferLockBaseAddress(m, .readOnly)
    let mw = CVPixelBufferGetWidth(m), mh = CVPixelBufferGetHeight(m), bpr = CVPixelBufferGetBytesPerRow(m)
    let px = CVPixelBufferGetBaseAddress(m)!.assumingMemoryBound(to: UInt8.self)
    var labels = [UInt8](repeating: 0, count: mw * mh)
    for y in 0..<mh { for x in 0..<mw { labels[y * mw + x] = px[y * bpr + x] } }
    CVPixelBufferUnlockBaseAddress(m, .readOnly)

    // Sticky choice: the instance under the current estimate's centre (most common label nearby).
    let probe = SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: w, sensorHeight: h,
                               mask: labels, maskWidth: mw, maskHeight: mh)
    let c = probe.worldToCamera * SIMD4(current.centre, 1)
    guard c.z < 0 else { continue }
    let u = k[0][0] * c.x / -c.z + k[2][0], v = k[1][1] * -c.y / -c.z + k[2][1]
    let mx0 = Int((1 - v / h) * Float(mw)), my0 = Int(u / w * Float(mh))
    var counts: [UInt8: Int] = [:]
    for dy in -10...10 { for dx in -10...10 {
        let x = mx0 + dx, y = my0 + dy
        guard x >= 0, y >= 0, x < mw, y < mh else { continue }
        let l = labels[y * mw + x]
        if l != 0 { counts[l, default: 0] += 1 }
    } }
    guard let label = counts.max(by: { $0.value < $1.value })?.key else { print("frame \(i): no instance at the item"); continue }
    let binary = labels.map { $0 == label ? UInt8(1) : 0 }
    if let dbg = ProcessInfo.processInfo.environment["HULL_DEBUG_DIR"] {
        // The chosen mask, resampled into the video frame's (sensor) orientation, as a PGM.
        let W = Int(w), H = Int(h)
        var img = [UInt8](repeating: 0, count: W * H)
        for v in 0..<H { for u in 0..<W {
            let mx = min(mw - 1, Int((1 - (Float(v) + 0.5) / h) * Float(mw))), my = min(mh - 1, Int((Float(u) + 0.5) / w * Float(mh)))
            img[v * W + u] = binary[my * mw + mx] * 255
        } }
        var pgm = Data("P5\n\(W) \(H)\n255\n".utf8); pgm.append(contentsOf: img)
        try pgm.write(to: URL(fileURLWithPath: dbg).appendingPathComponent(String(format: "mask_%04d.pgm", i)))
    }
    let used = hull.carveIfConsistent(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: w, sensorHeight: h,
                                                     mask: binary, maskWidth: mw, maskHeight: mh))
    if !used { print("frame \(i): mask disagrees with the hull, skipped"); continue }
    allViews.append((i, SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: w, sensorHeight: h, mask: binary, maskWidth: mw, maskHeight: mh)))
    let refined = tracker.add(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: w, sensorHeight: h, mask: binary, maskWidth: mw, maskHeight: mh))
    let te = tracker.estimate
    print(String(format: "           tracker%@ base (%.4f, %.4f)  w %.3f d %.3f", refined ? "*" : " ", te.footprintCentre.x, te.footprintCentre.z, te.width, te.depth))
    trackedLines.append("{\"frame\":\(i),\"centre\":[\(te.centre.x),\(te.centre.y),\(te.centre.z)]}")
    recent.append(SilhouetteView(cameraTransform: cam, intrinsics: k, sensorWidth: w, sensorHeight: h, mask: binary, maskWidth: mw, maskHeight: mh))
    if recent.count > windowSize { recent.removeFirst() }
    var win = VisualHull(around: hull.estimate() ?? start, planeY: planeY)
    for v in recent { win.carve(v) }
    if let we = win.estimate() {
        print(String(format: "           window(%d) spread %5.1f°  base (%.4f, %.4f)  w %.3f d %.3f", recent.count, win.spreadDegrees,
                     we.footprintCentre.x, we.footprintCentre.z, we.width, we.depth))
    }
    if let e = hull.estimate(), hull.spreadDegrees >= 35 { current = e }
    let e = hull.estimate()
    print(String(format: "frame %3d views %2d spread %5.1f°  base (%.4f, %.4f)  w %.3f d %.3f h %.3f", i, hull.views, hull.spreadDegrees,
                 e?.footprintCentre.x ?? .nan, e?.footprintCentre.z ?? .nan, e?.width ?? .nan, e?.depth ?? .nan, e?.height ?? .nan))
}
// Offline reference: for each frame, a hull from views within ±45 frames (past AND future), i.e. the
// best estimate of where the item is at that moment despite drift. The live tracker can't see the future.
var refLines: [String] = []
for (f, _) in allViews {
    let near = allViews.filter { abs($0.frame - f) <= 45 }.map(\.view)
    var hullRef = VisualHull(around: tracker.estimate, planeY: planeY)
    for v in near { hullRef.carve(v) }
    if near.count >= 4, hullRef.spreadDegrees >= 60, let e = hullRef.estimate() {
        refLines.append("{\"frame\":\(f),\"base\":[\(e.footprintCentre.x),\(e.footprintCentre.z)]}")
    }
}
try refLines.joined(separator: "\n").write(to: dir.appendingPathComponent("reference.jsonl"), atomically: true, encoding: .utf8)
try trackedLines.joined(separator: "\n").write(to: dir.appendingPathComponent("tracked.jsonl"), atomically: true, encoding: .utf8)
let moved = simd_distance(SIMD2(current.footprintCentre.x, current.footprintCentre.z), SIMD2(start.footprintCentre.x, start.footprintCentre.z))
print(String(format: "refined: moved %.1f cm from the start estimate", moved * 100))
let result: [String: Any] = ["footprint_centre": [current.footprintCentre.x, current.footprintCentre.y, current.footprintCentre.z].map(Double.init),
                             "centre": [current.centre.x, current.centre.y, current.centre.z].map(Double.init),
                             "size_m": [current.width, current.height, current.depth].map(Double.init)]
try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: dir.appendingPathComponent("refined.json"))
