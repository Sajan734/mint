// Runs the app's paper-turn measurement (ItemOnPaper → SheetAngle → PaperTurn, CoverageKit) on a
// turntable recording, on the Mac, from the video frames and their recorded camera rotations,
// exactly as the phone does from the camera image (same 320 × 240 grid).
//
//   swiftc -O -parse-as-library -module-name CoverageKit -emit-library -emit-module -o libCoverageKit.dylib \
//       ../ios/Packages/CoverageKit/Sources/CoverageKit/*.swift
//   swiftc -O -I . -L . -lCoverageKit turn_check.swift -o turn_check
//   DYLD_LIBRARY_PATH=. ./turn_check /path/to/unzipped/scan [--every 4] [--render /tmp/frames]
// Writes turn.jsonl (frame, read, turned_deg, confidence, elevation_deg, coverage_pct) into the scan
// folder and, if paper.jsonl from paper_check is there, compares the two. `--every 4` reads every 4th
// frame (the phone reads ~8 per second); `--render` paints the coverage tint onto the item in each
// frame read (JPEGs, sensor orientation) with a coverage bar along the top.
import AVFoundation
import CoreGraphics
import CoverageKit
import Foundation
import ImageIO
import simd
import UniformTypeIdentifiers

func rowMajor4(_ a: [[Double]]) -> simd_float4x4 {
    simd_float4x4(rows: (0..<4).map { r in SIMD4<Float>((0..<4).map { Float(a[r][$0]) }) })
}

func rowMajor3(_ a: [[Double]]) -> simd_float3x3 {
    simd_float3x3(rows: (0..<3).map { r in SIMD3<Float>((0..<3).map { Float(a[r][$0]) }) })
}

func rotation(_ m: simd_float4x4) -> simd_float3x3 {
    simd_float3x3(SIMD3(m.columns.0.x, m.columns.0.y, m.columns.0.z), SIMD3(m.columns.1.x, m.columns.1.y, m.columns.1.z),
                  SIMD3(m.columns.2.x, m.columns.2.y, m.columns.2.z))
}

/// Same grid as the app (`SubjectOutliner.grid`): brightness + colour strength, every `step`-th pixel.
func grid(_ pb: CVPixelBuffer, step: Int) -> ImageGrid {
    CVPixelBufferLockBaseAddress(pb, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
    let W = CVPixelBufferGetWidth(pb), H = CVPixelBufferGetHeight(pb), bpr = CVPixelBufferGetBytesPerRow(pb)
    let px = CVPixelBufferGetBaseAddress(pb)!.assumingMemoryBound(to: UInt8.self)
    let w = W / step, h = H / step
    var luma = [UInt8](repeating: 0, count: w * h), chroma = [UInt8](repeating: 0, count: w * h)
    for gy in 0..<h {
        for gx in 0..<w {
            let o = gy * step * bpr + gx * step * 4
            let b = Int(px[o]), g = Int(px[o + 1]), r = Int(px[o + 2])
            luma[gy * w + gx] = UInt8((299 * r + 587 * g + 114 * b) / 1000)
            chroma[gy * w + gx] = UInt8(max(r, g, b) - min(r, g, b))
        }
    }
    return ImageGrid(width: w, height: h, luma: luma, chroma: chroma)
}

let args = CommandLine.arguments
let dir = URL(fileURLWithPath: args[1])
let every = args.firstIndex(of: "--every").map { Int(args[$0 + 1])! } ?? 1
let renderDir = args.firstIndex(of: "--render").map { URL(fileURLWithPath: args[$0 + 1]) }
if let renderDir { try FileManager.default.createDirectory(at: renderDir, withIntermediateDirectories: true) }

/// Image direction (grid pixels) of the camera's horizontal right: how the item's sides run across the image.
func screenRight(_ frame: SheetAngle.HeadingFrame, _ r: simd_float3x3, _ k: SheetAngle.Intrinsics) -> SIMD2<Float> {
    func project(_ w: SIMD3<Float>) -> SIMD2<Float> {
        let c = r.transpose * w
        return SIMD2(k.fx * c.x / -c.z + k.cx, -k.fy * c.y / -c.z + k.cy)
    }
    let ahead = r * SIMD3<Float>(0, 0, -0.3)
    return simd_normalize(project(ahead + 0.02 * frame.right) - project(ahead))
}

/// Paints the tint onto the item (what the app draws inside the outline) and a coverage bar, and saves a JPEG.
func render(_ pb: CVPixelBuffer, item: [UInt8], gw: Int, gh: Int, step: Int, axis: SIMD2<Float>,
            coverage: TurnCoverage, to url: URL) {
    CVPixelBufferLockBaseAddress(pb, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
    let W = CVPixelBufferGetWidth(pb), H = CVPixelBufferGetHeight(pb), bpr = CVPixelBufferGetBytesPerRow(pb)
    let src = CVPixelBufferGetBaseAddress(pb)!.assumingMemoryBound(to: UInt8.self)
    var px = [UInt8](repeating: 0, count: H * bpr)
    for i in 0..<(H * bpr) { px[i] = src[i] }
    // The item's extent along the axis: the silhouette's middle and half-width.
    var lo = Float.infinity, hi = -Float.infinity
    for y in 0..<gh { for x in 0..<gw where item[y * gw + x] != 0 {
        let d = simd_dot(SIMD2(Float(x), Float(y)), axis); lo = min(lo, d); hi = max(hi, d)
    } }
    let mid = (lo + hi) / 2, half = max(1, (hi - lo) / 2)
    let mint: SIMD3<Float> = [61, 220, 151]
    for y in 0..<H {
        for x in 0..<W {
            let gx = x / step, gy = y / step
            guard gx < gw, gy < gh, item[gy * gw + gx] != 0 else { continue }
            let s = (simd_dot(SIMD2(Float(x) / Float(step), Float(y) / Float(step)), axis) - mid) / half
            let l = coverage.level(side: coverage.side(atOffset: s))
            let tint = SIMD3<Float>(repeating: 255) * (1 - l) + mint * l
            let a = 0.18 + 0.5 * l
            let o = y * bpr + x * 4
            let c = SIMD3(Float(px[o + 2]), Float(px[o + 1]), Float(px[o]))
            let out = c * (1 - a) + tint * a
            px[o + 2] = UInt8(out.x); px[o + 1] = UInt8(out.y); px[o] = UInt8(out.z)
        }
    }
    // Coverage bar along the top (sensor image; the phone shows it rotated).
    let barW = W * coverage.percent / 100
    for y in 0..<14 { for x in 0..<W {
        let o = y * bpr + x * 4
        if x < barW { px[o + 2] = 61; px[o + 1] = 220; px[o] = 151 } else { px[o + 2] /= 3; px[o + 1] /= 3; px[o] /= 3 }
    } }
    let ctx = CGContext(data: &px, width: W, height: H, bitsPerComponent: 8, bytesPerRow: bpr, space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
    let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, ctx.makeImage()!, [kCGImageDestinationLossyCompressionQuality: 0.8] as CFDictionary)
    CGImageDestinationFinalize(dest)
}
let poses = try String(contentsOf: dir.appendingPathComponent("poses.jsonl"), encoding: .utf8)
    .split(separator: "\n").map { try JSONSerialization.jsonObject(with: Data($0.utf8)) as! [String: Any] }
let asset = AVURLAsset(url: dir.appendingPathComponent("video.mp4"))
let track = try await asset.loadTracks(withMediaType: .video)[0]
let reader = try AVAssetReader(asset: asset)
let out = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(out)
reader.startReading()

let step = 3   // 960 × 720 video → 320 × 240, like the phone's 1920 × 1440 / 6
var turn = PaperTurn()
var coverage = TurnCoverage()
var lastUsed: Double?
var rendered = 0
var turned: [Int: Float] = [:]
var lines: [String] = []
var read = 0, used = 0, total = 0
var ms: Double = 0
var i = 0
while let sample = out.copyNextSampleBuffer(), let pb = CMSampleBufferGetImageBuffer(sample) {
    defer { i += 1 }
    guard i < poses.count, i % every == 0 else { continue }
    total += 1
    let cam = rowMajor4(poses[i]["pose_world"] as! [[Double]])
    let k = SheetAngle.Intrinsics(arkit: rowMajor3(poses[i]["intrinsics"] as! [[Double]]), step: Float(step))
    let t0 = Date()
    let g = grid(pb, step: step)
    var line = "{\"frame\":\(i),\"read\":false}"
    if let seg = ItemOnPaper.segment(g), let frame = SheetAngle.HeadingFrame(cameraRotation: rotation(cam)),
       let r = SheetAngle.read(sheet: seg.sheet, item: seg.item, width: g.width, height: g.height, intrinsics: k, frame: frame) {
        read += 1
        let ok = turn.update(r, time: Double(i) / 30)
        if ok { used += 1; turned[i] = turn.turned }
        // Elevation of the camera above the item's middle.
        var sx: Float = 0, sy: Float = 0, sn: Float = 0
        for y in 0..<g.height { for x in 0..<g.width where seg.item[y * g.width + x] != 0 { sx += Float(x); sy += Float(y); sn += 1 } }
        let el = frame.elevation(sx / sn, sy / sn, k)
        let t = Double(i) / 30
        if ok {
            coverage.observe(turned: turn.turned, elevation: el, dt: lastUsed.map { t - $0 } ?? 0)
            lastUsed = t
        }
        line = String(format: "{\"frame\":%d,\"read\":true,\"used\":%@,\"turned_deg\":%.3f,\"confidence\":%.3f,\"samples\":%d,\"elevation_deg\":%.1f,\"coverage_pct\":%d}",
                      i, ok ? "true" : "false", turn.turned * 180 / .pi, r.confidence, r.samples, el * 180 / .pi, coverage.percent)
        if let renderDir {
            render(pb, item: seg.item, gw: g.width, gh: g.height, step: step, axis: screenRight(frame, rotation(cam), k),
                   coverage: coverage, to: renderDir.appendingPathComponent(String(format: "%05d.jpg", rendered)))
            rendered += 1
        }
    }
    ms += -t0.timeIntervalSinceNow * 1000
    lines.append(line)
}
try lines.joined(separator: "\n").write(to: dir.appendingPathComponent("turn.jsonl"), atomically: true, encoding: .utf8)
print("coverage \(coverage.percent)%: ring \(coverage.arcs(band: 0, count: 12).map { String(format: "%.2f", $0) })")
print("read \(read)/\(total) frames, used \(used); total turn \(String(format: "%.1f", turn.turned * 180 / .pi))°; \(String(format: "%.1f", ms / Double(total))) ms/frame (grid + segment + angle) on this Mac")

// Against paper_check's top-down tracker, if it was run.
let ref = dir.appendingPathComponent("paper.jsonl")
if let text = try? String(contentsOf: ref, encoding: .utf8) {
    var diffs: [Float] = []
    var sign: Float = 0
    for l in text.split(separator: "\n") {
        let o = try JSONSerialization.jsonObject(with: Data(l.utf8)) as! [String: Any]
        guard let f = o["frame"] as? Int, let deg = o["turned_deg"] as? Double, let mine = turned[f] else { continue }
        let a = Float(deg), b = mine * 180 / .pi
        if sign == 0 && abs(a) > 20 { sign = (a * b) > 0 ? 1 : -1 }
        if sign != 0 { diffs.append(abs(a - sign * b)) }
    }
    diffs.sort()
    if !diffs.isEmpty {
        print(String(format: "vs paper_check (%d frames, sign %+.0f): median |Δ| %.2f°, 95th %.2f°, max %.2f°",
                     diffs.count, sign, diffs[diffs.count / 2], diffs[diffs.count * 95 / 100], diffs.last!))
    }
}
