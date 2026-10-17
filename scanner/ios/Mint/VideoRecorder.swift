import ARKit
import AVFoundation
import CoreImage
import CoverageKit
import VideoToolbox

/// Writes one pass of a scan to Documents/scans/{scan_id}/pass{n}/ (an item can have several passes,
/// e.g. upright then flipped over; they share the scan_id):
///   video.mp4     960×720 H.264, sensor (landscape) orientation, no B-frames; frame n ↔ poses.jsonl line n
///   poses.jsonl   one PoseRecord per video frame (raw ARKit camera pose + K for the video's pixels)
///   capture.json  session info
///   thumb.jpg     the first frame, upright, for the UI
/// `append` and `finish` must be called on the capture queue.
final class VideoRecorder {
    static let videoSize = CGSize(width: 960, height: 720)

    struct Summary: Equatable {
        let directory: URL
        let scanID: String
        let pass: Int
        let seconds: Double
        let frames: Int
        let megabytes: Double
    }

    struct FrameMeta {
        let cameraTransform: simd_float4x4   // raw ARKit, world
        let intrinsics: simd_float3x3        // sensor pixels
        let tracking: String
        let sharpness: Double
    }

    let scanID: String
    let pass: Int
    /// The listing a verify rescan is checked against (nil: a seller's listing scan).
    let listingID: String?
    let directory: URL

    private let writer: AVAssetWriter
    private let input: AVAssetWriterInput
    private let adaptor: AVAssetWriterInputPixelBufferAdaptor
    private var transfer: VTPixelTransferSession?
    private let poseHandle: FileHandle
    private let startDate = Date()
    private var t0: TimeInterval?
    private var lastTimestamp: TimeInterval = 0
    private var frameIndex = 0

    init(scanID: String, pass: Int, listingID: String? = nil) throws {
        self.scanID = scanID
        self.pass = pass
        self.listingID = listingID
        directory = Self.folder(scanID: scanID).appendingPathComponent("pass\(pass)", isDirectory: true)
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
        guard writer.canAdd(input) else { throw RecorderError("can't add video input") }
        writer.add(input)
        guard writer.startWriting() else { throw RecorderError(writer.error?.localizedDescription ?? "startWriting failed") }
        writer.startSession(atSourceTime: .zero)

        let posesURL = directory.appendingPathComponent("poses.jsonl")
        FileManager.default.createFile(atPath: posesURL.path, contents: nil)
        poseHandle = try FileHandle(forWritingTo: posesURL)
        VTPixelTransferSessionCreate(allocator: nil, pixelTransferSessionOut: &transfer)
    }

    /// Adds one frame to the video and the pose log (the log only gets lines for frames in the video).
    func append(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval, sensorSize: CGSize, meta: FrameMeta) {
        guard writer.status == .writing, timestamp > lastTimestamp,
              input.isReadyForMoreMediaData, let pool = adaptor.pixelBufferPool, let transfer else { return }
        var out: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &out)
        guard let out, VTPixelTransferSessionTransferImage(transfer, from: pixelBuffer, to: out) == noErr else { return }
        if t0 == nil {
            t0 = timestamp
            saveThumbnail(out)
        }
        let seconds = timestamp - t0!
        guard adaptor.append(out, withPresentationTime: CMTime(value: Int64((seconds * 1_000_000).rounded()), timescale: 1_000_000)) else { return }
        lastTimestamp = timestamp

        let sx = Float(Self.videoSize.width / sensorSize.width), sy = Float(Self.videoSize.height / sensorSize.height)
        let pose = Geometry.rowMajor(meta.cameraTransform)
        let record = PoseRecord(
            frame: frameIndex, t_ms: Int((seconds * 1000).rounded()),
            pose_world: pose, pose: pose,
            intrinsics: Geometry.rowMajor(Geometry.scaleIntrinsics(meta.intrinsics, sx: sx, sy: sy)),
            tracking: meta.tracking, state: "recording", sharpness: meta.sharpness, segment: nil, counted: false
        )
        if var line = try? CaptureJSON.encode(record) {
            line.append(0x0A)
            poseHandle.write(line)
        }
        frameIndex += 1
    }

    /// Where all passes of a scan live on the phone.
    static func folder(scanID: String) -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("scans/\(scanID)", isDirectory: true)
    }

    /// Closes the video and writes capture.json. `completion` runs on the main queue.
    func finish(sensorSize: CGSize, exposureLocked: Bool, coveragePct: Int, completion: @escaping (Result<Summary, Error>) -> Void) {
        input.markAsFinished()
        try? poseHandle.close()
        let frames = frameIndex
        let seconds = lastTimestamp - (t0 ?? lastTimestamp)
        writer.finishWriting { [self] in
            let result = Result<Summary, Error> {
                guard writer.status == .completed else { throw RecorderError(writer.error?.localizedDescription ?? "video didn't finish") }
                let createdAt = ISO8601DateFormatter().string(from: startDate)
                var info = CaptureInfo(
                    scan_id: scanID, device: Self.deviceModel(), os: UIDevice.current.systemVersion, created_at: createdAt,
                    duration_ms: Int((seconds * 1000).rounded()), video: "video.mp4",
                    video_width: Int(Self.videoSize.width), video_height: Int(Self.videoSize.height), video_frames: frames,
                    sensor_width: Int(sensorSize.width), sensor_height: Int(sensorSize.height), orientation: "sensor_landscape",
                    exposure_locked: exposureLocked, mode: "turntable"
                )
                info.coverage_pct = coveragePct
                info.pass = pass
                info.kind = listingID == nil ? "listing" : "handover"
                info.listing_scan_id = listingID
                try CaptureJSON.encode(info, pretty: true).write(to: directory.appendingPathComponent("capture.json"))
                return Summary(directory: directory, scanID: scanID, pass: pass, seconds: seconds, frames: frames,
                               megabytes: Double(Self.folderSize(directory)) / 1_000_000)
            }
            DispatchQueue.main.async { completion(result) }
        }
    }

    /// Stops without saving: removes the folder.
    func cancel() {
        input.markAsFinished()
        try? poseHandle.close()
        writer.cancelWriting()
        try? FileManager.default.removeItem(at: directory)
    }

    private func saveThumbnail(_ buffer: CVPixelBuffer) {
        let image = CIImage(cvPixelBuffer: buffer).oriented(.right)  // upright, as the phone was held
        let url = directory.appendingPathComponent("thumb.jpg")
        DispatchQueue.global(qos: .utility).async {
            let data = CIContext().jpegRepresentation(of: image, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                                                      options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.8])
            try? data?.write(to: url)
        }
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

struct RecorderError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
