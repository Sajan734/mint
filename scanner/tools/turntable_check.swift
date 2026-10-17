// Measures the turntable method on a recording: finds the sheet of paper under the item in every
// frame with Vision's rectangle detector (as the phone would), puts its corners on the table with
// the recorded ARKit pose, and follows the paper's angle through the turns.
//
//   swiftc -O -parse-as-library -module-name CoverageKit -emit-library -emit-module -o libCoverageKit.dylib \
//       ../ios/Packages/CoverageKit/Sources/CoverageKit/*.swift
//   swiftc -O -I . -L . -lCoverageKit turntable_check.swift -o turntable_check
//   DYLD_LIBRARY_PATH=. ./turntable_check /path/to/unzipped/scan [every_nth_frame=1]
// Writes turntable.jsonl (frame, found, yaw_deg, corners_px) into the scan folder.
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
guard args.count >= 2 else { print("usage: turntable_check scan_dir [nth]"); exit(1) }
let dir = URL(fileURLWithPath: args[1])
let nth = args.count > 2 ? Int(args[2])! : 1

let capture = try JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("capture.json"))) as! [String: Any]
let item = capture["item"] as! [String: Any]
let planeY = Float(item["plane_y"] as! Double)
let itemBase = (item["footprint_centre"] as! [Double]).map(Float.init)
let poses = try String(contentsOf: dir.appendingPathComponent("poses.jsonl"), encoding: .utf8)
    .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }

let asset = AVURLAsset(url: dir.appendingPathComponent("video.mp4"))
let track = try await asset.loadTracks(withMediaType: .video)[0]
let reader = try AVAssetReader(asset: asset)
let out = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(out)
reader.startReading()

var lines: [String] = []
var yawCont: Float?
var startYaw: Float?
var found = 0, tried = 0
var i = 0
while let sample = out.copyNextSampleBuffer(), let pb = CMSampleBufferGetImageBuffer(sample) {
    defer { i += 1 }
    guard i % nth == 0, i < poses.count else { continue }
    tried += 1
    let cam = rowMajor4(poses[i]["pose_world"] as! [[Double]])
    let k = rowMajor3(poses[i]["intrinsics"] as! [[Double]])
    let w = Float(CVPixelBufferGetWidth(pb)), h = Float(CVPixelBufferGetHeight(pb))

    let req = VNDetectRectanglesRequest()
    req.minimumAspectRatio = 0.3
    req.maximumAspectRatio = 1.0
    req.minimumSize = 0.1
    req.maximumObservations = 8
    req.quadratureTolerance = 45   // seen at an angle, a sheet is far from a rectangle in the image
    req.minimumConfidence = 0.3
    try VNImageRequestHandler(cvPixelBuffer: pb, orientation: .right).perform([req])

    // Vision corners: normalized, upright image, origin bottom-left → sensor pixels → ray → table.
    func toTable(_ p: CGPoint) -> SIMD3<Float>? {
        let ux = Float(p.x), uy = 1 - Float(p.y)              // upright, origin top-left
        let u = uy * w, v = (1 - ux) * h                      // sensor pixels (u = v′·W, v = (1 − u′)·H)
        let d = SIMD3((u - k[2][0]) / k[0][0], -(v - k[2][1]) / k[1][1], -1)
        let r = simd_float3x3(SIMD3(cam.columns.0.x, cam.columns.0.y, cam.columns.0.z),
                              SIMD3(cam.columns.1.x, cam.columns.1.y, cam.columns.1.z),
                              SIMD3(cam.columns.2.x, cam.columns.2.y, cam.columns.2.z))
        return Ray(origin: cam.translation, direction: r * d).hitHorizontalPlane(y: planeY)
    }
    var best: (PaperPose, [CGPoint])?
    for obs in req.results ?? [] {
        let pts = [obs.topLeft, obs.topRight, obs.bottomRight, obs.bottomLeft]
        let corners = pts.compactMap(toTable)
        guard corners.count == 4, let pose = Turntable.pose(corners: corners),
              pose.long > 0.15, pose.long < 0.5 else { continue }
        // The sheet under the item: its centre within half a sheet of the item.
        let dc = simd_length(SIMD2(pose.centre.x - itemBase[0], pose.centre.z - itemBase[2]))
        guard dc < pose.short / 2 else { continue }
        if best == nil || pose.long > best!.0.long { best = (pose, pts) }
    }
    if let (pose, pts) = best {
        found += 1
        let y = yawCont.map { Turntable.unwrap(pose.yaw, near: $0) } ?? pose.yaw
        yawCont = y
        if startYaw == nil { startYaw = y }
        let px = pts.map { p -> [Int] in [Int((1 - Float(p.y)) * w), Int((1 - Float(p.x)) * h)] }  // sensor px for drawing
        lines.append(String(format: "{\"frame\":%d,\"found\":true,\"yaw_deg\":%.3f,\"long\":%.4f,\"short\":%.4f,\"cx\":%.4f,\"cz\":%.4f,\"corners_px\":%@}",
                            i, (y - startYaw!) * 180 / .pi, pose.long, pose.short, pose.centre.x, pose.centre.z,
                            String(describing: px).replacingOccurrences(of: " ", with: "")))
    } else {
        lines.append("{\"frame\":\(i),\"found\":false}")
    }
}
try lines.joined(separator: "\n").write(to: dir.appendingPathComponent("turntable.jsonl"), atomically: true, encoding: .utf8)
print("paper found in \(found) of \(tried) frames")
if let y = yawCont, let s = startYaw { print(String(format: "total turn: %.1f°", (y - s) * 180 / .pi)) }
