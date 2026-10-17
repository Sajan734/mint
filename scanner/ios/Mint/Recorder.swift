import ARKit
import AVFoundation
import CoreImage
import CoverageKit
import CryptoKit
import VideoToolbox

/// Writes one scan to Documents/scans/{scan_id}/:
///   video.mp4     960×720 H.264, sensor (landscape) orientation, no B-frames; frame n ↔ poses.jsonl line n
///   poses.jsonl   one PoseRecord per video frame
///   f{nnnnn}.jpg  best frame per dome segment, 1440×1080 (n = the video frame it came from)
///   manifest.json contracts/capture_manifest (v3), capture.json session info
/// `append` and `finish` must be called on the frame queue.
final class Recorder {
    static let videoSize = CGSize(width: 960, height: 720)
    static let keyframeSize = CGSize(width: 1440, height: 1080)

    struct Summary {
        let directory: URL
        let scanID: String
        let durationMs: Int
        let videoFrames: Int
        let keyframes: Int
        let bytes: Int64
        let coveragePct: Int
    }

    struct FrameMeta {
        let cameraTransform: simd_float4x4   // raw ARKit, world
        let itemPose: simd_float4x4?         // camera-to-item; nil while handled
        let intrinsics: simd_float3x3        // sensor pixels
        let tracking: String
        let state: String
        let sharpness: Double
        let segment: SegmentID?
        let isBestForSegment: Bool
        let itemCentre: SIMD3<Float>?
    }

    let scanID = UUID().uuidString.lowercased()
    let directory: URL

    private let writer: AVAssetWriter
    private let input: AVAssetWriterInput
    private let adaptor: AVAssetWriterInputPixelBufferAdaptor
    private var transfer: VTPixelTransferSession?
    private var keyframePool: CVPixelBufferPool?
    private let poseHandle: FileHandle
    private let jpegQueue = DispatchQueue(label: "mint.jpeg", qos: .utility)
    private let ciContext = CIContext(options: [.cacheIntermediates: false])

    private var t0: TimeInterval?
    private var lastTimestamp: TimeInterval = 0
    private var frameIndex = 0
    private var droppedFrames = 0
    /// Best keyframe per segment: frame index + manifest entry (path filled in).
    private var keyframes: [SegmentID: CaptureManifest.Frame] = [:]
    private var keyframeHashes: [Int: String] = [:]  // written on jpegQueue
    private let startDate = Date()

    init() throws {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        directory = docs.appendingPathComponent("scans/\(scanID)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        writer = try AVAssetWriter(outputURL: directory.appendingPathComponent("video.mp4"), fileType: .mp4)
        input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: Int(Self.videoSize.width),
            AVVideoHeightKey: Int(Self.videoSize.height),
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: 8_000_000,          // generous for 720p: sharp detail for the splat
                AVVideoMaxKeyFrameIntervalKey: 15,
                AVVideoAllowFrameReorderingKey: false,        // decode order = capture order
                AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                AVVideoExpectedSourceFrameRateKey: 30,
            ],
        ])
        input.expectsMediaDataInRealTime = true
        adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelBufferWidthKey as String: Int(Self.videoSize.width),
            kCVPixelBufferHeightKey as String: Int(Self.videoSize.height),
            kCVPixelBufferIOSurfacePropertiesKey as String: [:],
        ])
        guard writer.canAdd(input) else { throw RecorderError.setup("can't add video input") }
        writer.add(input)
        guard writer.startWriting() else { throw RecorderError.setup(writer.error?.localizedDescription ?? "startWriting failed") }
        writer.startSession(atSourceTime: .zero)

        let posesURL = directory.appendingPathComponent("poses.jsonl")
        FileManager.default.createFile(atPath: posesURL.path, contents: nil)
        poseHandle = try FileHandle(forWritingTo: posesURL)

        VTPixelTransferSessionCreate(allocator: nil, pixelTransferSessionOut: &transfer)
        CVPixelBufferPoolCreate(nil, [kCVPixelBufferPoolMinimumBufferCountKey as String: 3] as CFDictionary, [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
            kCVPixelBufferWidthKey as String: Int(Self.keyframeSize.width),
            kCVPixelBufferHeightKey as String: Int(Self.keyframeSize.height),
            kCVPixelBufferIOSurfacePropertiesKey as String: [:],
        ] as CFDictionary, &keyframePool)
    }

    /// Adds one frame to the video and pose log, and keeps it as a keyframe if it's the best for its segment.
    func append(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval, sensorSize: CGSize, meta: FrameMeta) {
        guard writer.status == .writing, timestamp > lastTimestamp else { return }
        guard input.isReadyForMoreMediaData, let pool = adaptor.pixelBufferPool, let transfer else {
            droppedFrames += 1  // the pose log only gets lines for frames that made it into the video
            return
        }
        var out: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &out)
        guard let out, VTPixelTransferSessionTransferImage(transfer, from: pixelBuffer, to: out) == noErr else {
            droppedFrames += 1
            return
        }
        if t0 == nil { t0 = timestamp }
        let tMs = Int(((timestamp - t0!) * 1000).rounded())
        let pts = CMTime(value: Int64(((timestamp - t0!) * 1_000_000).rounded()), timescale: 1_000_000)
        guard adaptor.append(out, withPresentationTime: pts) else {
            droppedFrames += 1
            return
        }
        lastTimestamp = timestamp

        let n = frameIndex
        frameIndex += 1
        let sx = Float(Self.videoSize.width / sensorSize.width), sy = Float(Self.videoSize.height / sensorSize.height)
        let record = PoseRecord(
            frame: n, t_ms: tMs,
            pose_world: Geometry.rowMajor(meta.cameraTransform),
            pose: meta.itemPose.map(Geometry.rowMajor),
            intrinsics: Geometry.rowMajor(Geometry.scaleIntrinsics(meta.intrinsics, sx: sx, sy: sy)),
            tracking: meta.tracking, state: meta.state, sharpness: meta.sharpness,
            segment: meta.segment?.name, counted: meta.isBestForSegment,
            item_centre: meta.itemCentre.map(CaptureJSON.vec)
        )
        if var line = try? CaptureJSON.encode(record) {
            line.append(0x0A)
            poseHandle.write(line)
        }

        if meta.isBestForSegment, let seg = meta.segment, let itemPose = meta.itemPose {
            saveKeyframe(pixelBuffer, frame: n, tMs: tMs, segment: seg, itemPose: itemPose,
                         intrinsics: meta.intrinsics, sensorSize: sensorSize, sharpness: meta.sharpness)
        }
    }

    private func saveKeyframe(_ buffer: CVPixelBuffer, frame n: Int, tMs: Int, segment: SegmentID, itemPose: simd_float4x4,
                              intrinsics: simd_float3x3, sensorSize: CGSize, sharpness: Double) {
        guard let keyframePool, let transfer else { return }
        var out: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, keyframePool, &out)
        // Copy now: ARKit's buffer must not be held while the JPEG encodes.
        guard let out, VTPixelTransferSessionTransferImage(transfer, from: buffer, to: out) == noErr else { return }

        let name = String(format: "f%05d.jpg", n)
        let sx = Float(Self.keyframeSize.width / sensorSize.width), sy = Float(Self.keyframeSize.height / sensorSize.height)
        let replaced = keyframes[segment]
        keyframes[segment] = CaptureManifest.Frame(
            index: n, path: "scans/\(scanID)/\(name)", t_ms: tMs,
            pose: Geometry.rowMajor(itemPose),
            intrinsics: Geometry.rowMajor(Geometry.scaleIntrinsics(intrinsics, sx: sx, sy: sy)),
            sharpness: sharpness, segment: segment.name
        )

        let dir = directory, ctx = ciContext
        jpegQueue.async { [weak self] in
            if let old = replaced {
                try? FileManager.default.removeItem(at: dir.appendingPathComponent(URL(fileURLWithPath: old.path).lastPathComponent))
                self?.keyframeHashes[old.index] = nil
            }
            let image = CIImage(cvPixelBuffer: out)
            guard let data = ctx.jpegRepresentation(
                of: image, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.92]
            ) else { return }
            try? data.write(to: dir.appendingPathComponent(name))
            self?.keyframeHashes[n] = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        }
    }

    /// Closes the video and writes manifest.json + capture.json. `completion` runs on the main queue.
    func finish(item: ObjectEstimate, planeY: Float, coveragePct: Int, filled: Set<SegmentID>,
                sensorSize: CGSize, exposureLocked: Bool, completion: @escaping (Result<Summary, Error>) -> Void) {
        input.markAsFinished()
        let frames = frameIndex
        let durationMs = Int(((lastTimestamp - (t0 ?? lastTimestamp)) * 1000).rounded())
        let keyframeList = keyframes.values.sorted { $0.index < $1.index }
        let createdAt = ISO8601DateFormatter().string(from: startDate)
        try? poseHandle.close()

        writer.finishWriting { [self] in
            // Wait for pending JPEGs, then write the JSON files on the JPEG queue (it owns keyframeHashes).
            jpegQueue.async { [self] in
                let result = Result<Summary, Error> {
                    if writer.status != .completed {
                        throw RecorderError.setup(writer.error?.localizedDescription ?? "video didn't finish")
                    }
                    let device = Self.deviceModel()
                    let manifest = CaptureManifest(
                        scan_id: scanID, item_id: UUID().uuidString.lowercased(), batch_id: UUID().uuidString.lowercased(),
                        kind: "listing",
                        frames: keyframeList.map { var f = $0; f.sha256 = keyframeHashes[f.index]; return f },
                        anchor: CaptureJSON.vec(item.centre), coverage_pct: coveragePct,
                        width: Int(Self.keyframeSize.width), height: Int(Self.keyframeSize.height),
                        device: device, created_at: createdAt
                    )
                    try CaptureJSON.encode(manifest, pretty: true).write(to: directory.appendingPathComponent("manifest.json"))

                    let info = CaptureInfo(
                        scan_id: scanID, device: device, os: UIDevice.current.systemVersion, created_at: createdAt,
                        duration_ms: durationMs, video: "video.mp4",
                        video_width: Int(Self.videoSize.width), video_height: Int(Self.videoSize.height), video_frames: frames,
                        sensor_width: Int(sensorSize.width), sensor_height: Int(sensorSize.height),
                        orientation: "sensor_landscape",
                        item: .init(centre: CaptureJSON.vec(item.centre), footprint_centre: CaptureJSON.vec(item.footprintCentre),
                                    size_m: [Double(item.width), Double(item.height), Double(item.depth)],
                                    dome_radius_m: Double(item.domeRadius), plane_y: Double(planeY)),
                        coverage_pct: coveragePct, segments_filled: filled.sorted().map(\.name),
                        exposure_locked: exposureLocked
                    )
                    try CaptureJSON.encode(info, pretty: true).write(to: directory.appendingPathComponent("capture.json"))

                    return Summary(directory: directory, scanID: scanID, durationMs: durationMs, videoFrames: frames,
                                   keyframes: keyframeList.count, bytes: Self.folderSize(directory), coveragePct: coveragePct)
                }
                DispatchQueue.main.async { completion(result) }
            }
        }
    }

    /// Stops without saving: removes the folder.
    func cancel() {
        input.markAsFinished()
        try? poseHandle.close()
        writer.cancelWriting()
        let dir = directory
        jpegQueue.async { try? FileManager.default.removeItem(at: dir) }
    }

    private static func deviceModel() -> String {
        var info = utsname()
        uname(&info)
        let machine = withUnsafeBytes(of: &info.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
        return "\(machine) iOS \(UIDevice.current.systemVersion)"
    }

    private static func folderSize(_ url: URL) -> Int64 {
        let files = (try? FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: [.fileSizeKey])) ?? []
        return files.reduce(0) { $0 + Int64((try? $1.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
    }
}

enum RecorderError: LocalizedError {
    case setup(String)
    var errorDescription: String? {
        switch self { case .setup(let m): return m }
    }
}
