import Foundation
import simd

/// What the capture loop knows about one ARKit frame, already reduced to plain values.
public struct FrameObservation: Sendable {
    public let cameraTransform: simd_float4x4  // raw ARKit camera-to-world
    public let timestamp: Double               // seconds (ARFrame.timestamp)
    public let trackingNormal: Bool
    public let sharpness: Double               // Sharpness.laplacianVariance on the thumbnail
    public let meanLuma: Double                // 0–255

    public init(cameraTransform: simd_float4x4, timestamp: Double, trackingNormal: Bool, sharpness: Double, meanLuma: Double) {
        self.cameraTransform = cameraTransform
        self.timestamp = timestamp
        self.trackingNormal = trackingNormal
        self.sharpness = sharpness
        self.meanLuma = meanLuma
    }
}

/// Why a frame didn't count. The app maps each to plain-language copy.
public enum CaptureIssue: Equatable, Sendable {
    case trackingLimited
    case tooClose
    case tooFar
    case tooLow
    case tooHigh
    case tooFast
    case tooDark
    case blurry
}

public struct FrameDecision: Sendable {
    public let position: DomePosition
    public let segment: SegmentID?
    public let issue: CaptureIssue?
    /// This frame filled a previously empty segment.
    public let filledNewSegment: Bool
    /// This frame is now the best keyframe for its segment (first fill, or clearly sharper).
    public let isBestForSegment: Bool
}

public struct CoverageConfig: Sendable {
    public var minDistanceM: Float = 0.12
    public var maxDistanceM: Float = 1.5
    public var maxAngularSpeed: Float = 1.0   // rad/s; a slow walk-around is ~0.3
    public var minMeanLuma: Double = 35
    public var replaceIfSharperBy: Double = 1.15

    public init() {}
}

/// Tracks which dome segments have a good frame. Pure value type: feed it observations, read state.
public struct CoverageTracker: Sendable {
    /// Item centre. Updated as the item is tracked (ARKit's world drifts a few cm over a lap).
    public var anchor: SIMD3<Float>
    public var config: CoverageConfig
    public private(set) var bestSharpness: [SegmentID: Double] = [:]
    private var gate = SharpnessGate()
    private var last: (transform: simd_float4x4, t: Double)?

    public init(anchor: SIMD3<Float>, config: CoverageConfig = CoverageConfig()) {
        self.anchor = anchor
        self.config = config
    }

    public var filled: Set<SegmentID> { Set(bestSharpness.keys) }
    public var coverageFraction: Double { Double(bestSharpness.count) / Double(Dome.segmentCount) }
    /// Integer percent, floored (the contract's `coverage_pct`).
    public var coveragePct: Int { bestSharpness.count * 100 / Dome.segmentCount }
    public var isComplete: Bool { bestSharpness.count >= Dome.segmentsToComplete }

    public mutating func observe(_ o: FrameObservation) -> FrameDecision {
        let pos = Dome.position(camera: o.cameraTransform.translation, anchor: anchor)
        let seg = Dome.segment(for: pos)

        let speed: Float = last.map {
            Geometry.angularSpeed(from: $0.transform, to: o.cameraTransform, dt: o.timestamp - $0.t)
        } ?? 0
        last = (o.cameraTransform, o.timestamp)
        // The gate sees every frame so its "recent sharpest" stays current.
        let sharpEnough = gate.accept(o.sharpness)

        func reject(_ issue: CaptureIssue) -> FrameDecision {
            FrameDecision(position: pos, segment: seg, issue: issue, filledNewSegment: false, isBestForSegment: false)
        }

        if !o.trackingNormal { return reject(.trackingLimited) }
        if pos.distanceM < config.minDistanceM { return reject(.tooClose) }
        if pos.distanceM > config.maxDistanceM { return reject(.tooFar) }
        guard let seg else {
            return reject(pos.elevationDeg < Dome.bands[0].minDeg ? .tooLow : .tooHigh)
        }
        if speed > config.maxAngularSpeed { return reject(.tooFast) }
        if o.meanLuma < config.minMeanLuma { return reject(.tooDark) }
        if !sharpEnough { return reject(.blurry) }

        let previous = bestSharpness[seg]
        let isNew = previous == nil
        let isBest = isNew || o.sharpness > previous! * config.replaceIfSharperBy
        if isBest { bestSharpness[seg] = o.sharpness }
        return FrameDecision(position: pos, segment: seg, issue: nil, filledNewSegment: isNew, isBestForSegment: isBest)
    }
}
