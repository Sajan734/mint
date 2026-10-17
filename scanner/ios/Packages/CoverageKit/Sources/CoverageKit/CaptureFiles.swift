import Foundation
import simd

/// contracts/capture_manifest.schema.json (v3). `pose` = camera-to-item transform in ARKit camera
/// axes, row-major; while the item hasn't moved this is exactly the raw ARKit camera.transform.
public struct CaptureManifest: Codable, Equatable, Sendable {
    public struct Frame: Codable, Equatable, Sendable {
        public var index: Int
        public var path: String
        public var t_ms: Int
        public var pose: [[Double]]
        public var intrinsics: [[Double]]
        public var sharpness: Double
        public var segment: String
        public var sha256: String?

        public init(index: Int, path: String, t_ms: Int, pose: [[Double]], intrinsics: [[Double]],
                    sharpness: Double, segment: String, sha256: String? = nil) {
            self.index = index
            self.path = path
            self.t_ms = t_ms
            self.pose = pose
            self.intrinsics = intrinsics
            self.sharpness = sharpness
            self.segment = segment
            self.sha256 = sha256
        }
    }

    public var v = 3
    public var scan_id: String
    public var item_id: String
    public var batch_id: String
    public var deal_id: String?
    public var kind: String
    public var frames: [Frame]
    public var anchor: [Double]
    public var coverage_pct: Int
    public var width: Int
    public var height: Int
    public var device: String
    public var created_at: String

    public init(scan_id: String, item_id: String, batch_id: String, deal_id: String? = nil, kind: String,
                frames: [Frame], anchor: [Double], coverage_pct: Int, width: Int, height: Int,
                device: String, created_at: String) {
        self.scan_id = scan_id
        self.item_id = item_id
        self.batch_id = batch_id
        self.deal_id = deal_id
        self.kind = kind
        self.frames = frames
        self.anchor = anchor
        self.coverage_pct = coverage_pct
        self.width = width
        self.height = height
        self.device = device
        self.created_at = created_at
    }
}

/// One line of poses.jsonl: one per frame of video.mp4, in order (line n = encoded frame n).
public struct PoseRecord: Codable, Equatable, Sendable {
    public var frame: Int
    public var t_ms: Int
    /// Raw ARKit camera.transform (camera-to-world), row-major.
    public var pose_world: [[Double]]
    /// Camera-to-item (the item's own frame, see the manifest). Absent while the item is being handled.
    public var pose: [[Double]]?
    /// K for the video's pixels (960×720).
    public var intrinsics: [[Double]]
    public var tracking: String       // "normal" | "limited" | "not_available"
    public var state: String          // "scanning" | "handling" | "settling"
    public var sharpness: Double
    public var segment: String?
    public var counted: Bool          // this frame filled or improved a dome segment
    /// Where the item's centre is in this frame's ARKit world (tracked from the masks; follows ARKit drift).
    public var item_centre: [Double]?

    public init(frame: Int, t_ms: Int, pose_world: [[Double]], pose: [[Double]]?, intrinsics: [[Double]],
                tracking: String, state: String, sharpness: Double, segment: String?, counted: Bool,
                item_centre: [Double]? = nil) {
        self.frame = frame
        self.t_ms = t_ms
        self.pose_world = pose_world
        self.pose = pose
        self.intrinsics = intrinsics
        self.tracking = tracking
        self.state = state
        self.sharpness = sharpness
        self.segment = segment
        self.counted = counted
        self.item_centre = item_centre
    }
}

/// capture.json: everything about the session that isn't per-frame.
public struct CaptureInfo: Codable, Equatable, Sendable {
    public struct Item: Codable, Equatable, Sendable {
        public var centre: [Double]            // ARKit world, metres (dome centre, half-way up)
        public var footprint_centre: [Double]
        public var size_m: [Double]            // width, height, depth (depth assumed = width)
        public var dome_radius_m: Double
        public var plane_y: Double

        public init(centre: [Double], footprint_centre: [Double], size_m: [Double], dome_radius_m: Double, plane_y: Double) {
            self.centre = centre
            self.footprint_centre = footprint_centre
            self.size_m = size_m
            self.dome_radius_m = dome_radius_m
            self.plane_y = plane_y
        }
    }

    public var v = 1
    public var scan_id: String
    public var device: String
    public var os: String
    public var created_at: String
    public var duration_ms: Int
    public var video: String                  // "video.mp4"
    public var video_width: Int
    public var video_height: Int
    public var video_frames: Int
    public var sensor_width: Int
    public var sensor_height: Int
    public var orientation: String            // "sensor_landscape": frames are NOT rotated to portrait
    public var item: Item?
    public var coverage_pct: Int?
    public var segments_filled: [String]?
    public var exposure_locked: Bool
    /// "turntable" (item on a sheet the user turned; `pose` = camera in the item's frame) or "walk".
    public var mode: String?
    /// Turntable: the sheet's size (long, short), metres.
    public var paper_m: [Double]?
    /// Which recording of the item this is (1 = the main lap; 2 = usually the item flipped over; …).
    /// All passes of one item share `scan_id`.
    public var pass: Int?
    /// "listing" (a seller scanning an item to sell) or "handover" (a buyer rescanning it at an in-person
    /// deal to check it matches the listing; CLAUDE.md M14).
    public var kind: String?
    /// Handover: the scan_id of the listing this rescan is checked against.
    public var listing_scan_id: String?

    public init(scan_id: String, device: String, os: String, created_at: String, duration_ms: Int,
                video: String, video_width: Int, video_height: Int, video_frames: Int,
                sensor_width: Int, sensor_height: Int, orientation: String, item: Item? = nil,
                coverage_pct: Int? = nil, segments_filled: [String]? = nil, exposure_locked: Bool,
                mode: String? = nil, paper_m: [Double]? = nil) {
        self.scan_id = scan_id
        self.device = device
        self.os = os
        self.created_at = created_at
        self.duration_ms = duration_ms
        self.video = video
        self.video_width = video_width
        self.video_height = video_height
        self.video_frames = video_frames
        self.sensor_width = sensor_width
        self.sensor_height = sensor_height
        self.orientation = orientation
        self.item = item
        self.coverage_pct = coverage_pct
        self.segments_filled = segments_filled
        self.exposure_locked = exposure_locked
        self.mode = mode
        self.paper_m = paper_m
    }
}

public enum CaptureJSON {
    /// Stable output: sorted keys, no slashes escaped. One line for JSONL.
    public static func encode<T: Encodable>(_ value: T, pretty: Bool = false) throws -> Data {
        let e = JSONEncoder()
        e.outputFormatting = pretty ? [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted] : [.sortedKeys, .withoutEscapingSlashes]
        return try e.encode(value)
    }

    public static func vec(_ v: SIMD3<Float>) -> [Double] { [Double(v.x), Double(v.y), Double(v.z)] }
}
