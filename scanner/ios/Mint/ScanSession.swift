import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// Owns the AR session and the scan state machine:
/// starting (finding the table) → aiming (item found, measured, previewed) → scanning (dome filling,
/// recording) → saving → done (files ready to share).
@MainActor
final class ScanSession: NSObject, ObservableObject {
    enum Phase: Equatable {
        case starting, aiming, scanning, saving
        case done(ScanSummary)
        case failed(String)
    }

    /// What the aiming UI shows.
    struct Found: Equatable {
        let boundsInView: CGRect
        let estimate: ObjectEstimate?
        let planeY: Float?
        /// The measurement has held steady; Start is allowed.
        let locked: Bool
    }

    @Published private(set) var phase: Phase = .starting
    @Published private(set) var found: Found?
    @Published private(set) var filled: Set<SegmentID> = []
    @Published private(set) var position: DomePosition?
    @Published private(set) var hint: Hint?
    @Published private(set) var issue: CaptureIssue?
    @Published private(set) var cameraLocked = false
    @Published private(set) var scanStart: Date?

    var coveragePct: Int { filled.count * 100 / Dome.segmentCount }
    var canStart: Bool { phase == .aiming && found?.locked == true }

    let arView: ARView
    private let processor = FrameProcessor()
    /// Preview while aiming, the scan dome while scanning.
    private var dome: DomeEntity?
    private var item: (estimate: ObjectEstimate, planeY: Float)?
    private var locker = LockingEstimator()
    private var issueDebounce = IssueDebounce()
    private let tick = UIImpactFeedbackGenerator(style: .light)
    private let success = UINotificationFeedbackGenerator()

    override init() {
        arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        super.init()
        arView.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disablePersonOcclusion, .disableHDR]
        arView.session.delegate = processor
        arView.session.delegateQueue = processor.queue
        processor.onUpdate = { [weak self] in self?.apply($0) }
        processor.onDetection = { [weak self] in self?.applyDetection($0) }
        processor.onTrackingChange = { [weak self] state in
            guard let self, self.phase == .starting, case .normal = state else { return }
            self.phase = .aiming
            self.processor.startAiming()
        }
    }

    /// Starts (or restarts) tracking. A restart loses the world frame, so any scan in progress is dropped.
    func run() {
        reset()
        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        // Full 4:3 sensor frames (D2): ARKit's K refers to exactly these pixels.
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats
            .filter({ $0.imageResolution == CGSize(width: 1920, height: 1440) })
            .max(by: { $0.framesPerSecond < $1.framesPerSecond }) {
            config.videoFormat = format
        }
        arView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
        phase = .starting
    }

    func pause() {
        processor.cancel()
        arView.session.pause()
    }

    /// While aiming: tap picks which item to scan.
    func handleTap(at point: CGPoint) {
        guard phase == .aiming, let frame = arView.session.currentFrame else { return }
        let size = arView.bounds.size
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        let sensor = CGPoint(x: point.x / size.width, y: point.y / size.height).applying(toView.inverted())
        processor.setPreferredPoint(CGPoint(x: 1 - sensor.y, y: sensor.x))  // sensor → upright
        locker = LockingEstimator()
        tick.impactOccurred(intensity: 0.6)
    }

    func start() {
        guard canStart, let est = found?.estimate, let planeY = found?.planeY else { return }
        item = (est, planeY)
        let dome = self.dome ?? makeDome()
        dome.place(base: est.footprintCentre, radius: DomeEntity.radius(for: est), animated: false)
        dome.beginScan()

        cameraLocked = CameraLock.lock()
        let recorder: Recorder?
        do {
            recorder = try Recorder()
        } catch {
            phase = .failed("Couldn't start recording: \(error.localizedDescription)")
            return
        }
        processor.startScanning(item: est, recorder: recorder)
        filled = []
        issueDebounce = IssueDebounce()
        found = nil
        scanStart = Date()
        phase = .scanning
        tick.prepare()
        success.prepare()
        tick.impactOccurred(intensity: 1)
    }

    /// Finish now (auto at 90%, or the stop button).
    func finish() {
        guard phase == .scanning, let item else { return }
        phase = .saving
        let coverage = coveragePct, segments = filled, locked = cameraLocked
        processor.finish { recorder, sensorSize in
            guard let recorder else {
                DispatchQueue.main.async { MainActor.assumeIsolated { self.phase = .failed("Nothing was recorded.") } }
                return
            }
            recorder.finish(item: item.estimate, planeY: item.planeY, coveragePct: coverage, filled: segments,
                            sensorSize: sensorSize, exposureLocked: locked) { [weak self] result in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    CameraLock.unlock()
                    self.cameraLocked = false
                    switch result {
                    case .success(let s): self.phase = .done(ScanSummary(s))
                    case .failure(let e): self.phase = .failed("Couldn't save the scan: \(e.localizedDescription)")
                    }
                }
            }
        }
    }

    /// Pinch to adjust the dome if the measurement is off.
    func scaleDome(by factor: Float) {
        guard let dome else { return }
        dome.setRadius(min(max(dome.radius * factor, 0.06), 1.5))
    }

    /// Back to aiming; drops any scan in progress.
    func reset() {
        processor.cancel()
        if let dome { arView.scene.removeAnchor(dome.anchor) }
        dome = nil
        item = nil
        CameraLock.unlock()
        cameraLocked = false
        filled = []
        position = nil
        hint = nil
        issue = nil
        found = nil
        scanStart = nil
        locker = LockingEstimator()
        if phase != .starting {
            phase = .aiming
            processor.startAiming()
        }
    }

    private func makeDome() -> DomeEntity {
        let d = DomeEntity()
        arView.scene.addAnchor(d.anchor)
        dome = d
        return d
    }

    // MARK: - Aiming: measure the item

    private func applyDetection(_ result: ObjectDetector.Result?) {
        guard phase == .aiming else { return }
        guard let result, result.areaFraction > 0.003, let frame = arView.session.currentFrame else {
            // A missed read doesn't drop a lock straight away (Vision misses the odd frame).
            if !locker.miss() {
                found = nil
                dome?.showPoints([])
            }
            return
        }
        let rect = viewRect(result.boundsUpright, frame: frame)

        // Measured points: where rays through the item's interior hit ARKit's surface estimate.
        let hits = result.interiorRays.compactMap { r -> SIMD3<Float>? in
            let q = ARRaycastQuery(origin: r.origin, direction: r.direction, allowing: .estimatedPlane, alignment: .any)
            return arView.session.raycast(q).first?.worldTransform.translation
        }
        let planeY = tablePlaneY(hits: hits, result: result, frame: frame)

        var estimate: ObjectEstimate?
        if let planeY {
            estimate = ObjectSizing.measure(camera: result.camera, surfaceHits: hits,
                                            silhouetteRays: result.silhouetteRays, planeY: planeY)
            if estimate == nil, hits.count < 4 {
                // Too plain for ARKit to measure: fall back to the single-view estimate.
                estimate = ObjectSizing.estimate(camera: result.camera, contactRays: result.contactRays,
                                                 silhouetteRays: result.silhouetteRays, planeY: planeY)
            }
        }

        guard let estimate, let planeY else {
            if !locker.miss() {
                found = Found(boundsInView: rect, estimate: nil, planeY: planeY, locked: false)
                dome?.showPoints([])
            }
            return
        }
        let wasLocked = locker.isLocked
        let steady = locker.feed(estimate)
        found = Found(boundsInView: rect, estimate: steady.estimate, planeY: planeY, locked: steady.locked)
        if steady.locked && !wasLocked {
            tick.impactOccurred(intensity: 0.8)
            dome?.showPoints([])
        } else if !steady.locked {
            dome?.showPoints(hits.filter { $0.y > planeY + 0.006 })
        }

        let dome = self.dome ?? makeDome()
        dome.place(base: steady.estimate.footprintCentre, radius: DomeEntity.radius(for: steady.estimate), animated: true)
    }

    /// The table: the highest horizontal plane clearly below the measured points. Candidates are
    /// ARKit's plane anchors plus whatever lies straight below the item; planes ARKit found on top
    /// of the item are excluded (they made earlier sizes jump).
    private func tablePlaneY(hits: [SIMD3<Float>], result: ObjectDetector.Result, frame: ARFrame) -> Float? {
        var candidates = frame.anchors.compactMap { a -> Float? in
            guard let p = a as? ARPlaneAnchor, p.alignment == .horizontal else { return nil }
            return p.transform.translation.y
        }
        if !hits.isEmpty {
            let ys = hits.map(\.y).sorted()
            let probe = SIMD3(hits.map(\.x).sorted()[hits.count / 2], ys[ys.count / 2], hits.map(\.z).sorted()[hits.count / 2])
            let q = ARRaycastQuery(origin: probe, direction: [0, -1, 0], allowing: .existingPlaneInfinite, alignment: .horizontal)
            candidates += arView.session.raycast(q).map { $0.worldTransform.translation.y }
            return ObjectSizing.tablePlane(candidates: candidates, surfaceHits: hits)
        }
        // No measured points: the plane whose *detected extent* is under the item's front edge.
        guard !result.contactRays.isEmpty else { return nil }
        let mid = result.contactRays[result.contactRays.count / 2]
        let q = ARRaycastQuery(origin: mid.origin, direction: mid.direction, allowing: .existingPlaneGeometry, alignment: .horizontal)
        return arView.session.raycast(q).first?.worldTransform.translation.y
    }

    private func viewRect(_ b: CGRect, frame: ARFrame) -> CGRect {
        let size = arView.bounds.size
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        // Upright normalized → sensor normalized (u = v′, v = 1 − u′) → view.
        let corners = [CGPoint(x: b.minX, y: b.minY), CGPoint(x: b.maxX, y: b.minY),
                       CGPoint(x: b.minX, y: b.maxY), CGPoint(x: b.maxX, y: b.maxY)]
            .map { CGPoint(x: $0.y, y: 1 - $0.x).applying(toView) }
            .map { CGPoint(x: $0.x * size.width, y: $0.y * size.height) }
        let xs = corners.map(\.x), ys = corners.map(\.y)
        return CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
    }

    // MARK: - Scanning

    private func apply(_ u: FrameProcessor.Update) {
        guard phase == .scanning else { return }
        position = u.decision.position
        hint = u.hint
        issue = issueDebounce.feed(u.decision.issue)

        if u.decision.filledNewSegment, let seg = u.decision.segment {
            dome?.pulse(seg)
            tick.impactOccurred()
        }
        filled = u.filled
        dome?.update(filled: u.filled, current: u.decision.segment)

        if u.isComplete {
            issue = nil
            success.notificationOccurred(.success)
            finish()
        }
    }
}

/// What the done screen shows.
struct ScanSummary: Equatable {
    let directory: URL
    let scanID: String
    let seconds: Double
    let videoFrames: Int
    let keyframes: Int
    let megabytes: Double
    let coveragePct: Int

    init(_ s: Recorder.Summary) {
        directory = s.directory
        scanID = s.scanID
        seconds = Double(s.durationMs) / 1000
        videoFrames = s.videoFrames
        keyframes = s.keyframes
        megabytes = Double(s.bytes) / 1_000_000
        coveragePct = s.coveragePct
    }
}

/// Acquire, then hold. Until locked: the median of recent reads, locking once the last three agree
/// (centre within 3 cm, size within 25%). Once locked, the estimate is **frozen** so the ring stays
/// put; only losing the item (6 missed reads ≈ 1.5 s, or 3 reads somewhere else) releases it.
/// The old version re-checked every read and kept dropping the lock after a second.
private struct LockingEstimator {
    private var window: [ObjectEstimate] = []
    private var held: ObjectEstimate?
    private var misses = 0
    private var strays = 0

    var isLocked: Bool { held != nil }

    mutating func feed(_ e: ObjectEstimate) -> (estimate: ObjectEstimate, locked: Bool) {
        misses = 0
        if let h = held {
            if simd_distance(h.footprintCentre, e.footprintCentre) < 0.08 {
                strays = 0
                return (h, true)
            }
            strays += 1
            if strays < 3 { return (h, true) }
            held = nil  // the item moved or we're looking at something else
            window.removeAll()
        }
        strays = 0
        if let m = median, simd_distance(m.footprintCentre, e.footprintCentre) > 0.08 {
            window.removeAll()
        }
        window.append(e)
        if window.count > 7 { window.removeFirst() }
        let m = median!
        let agree = window.count >= 3 && window.suffix(3).allSatisfy {
            simd_distance($0.footprintCentre, m.footprintCentre) < 0.03
                && abs($0.width - m.width) <= 0.25 * m.width
                && abs($0.height - m.height) <= 0.25 * m.height
        }
        if agree { held = m }
        return (m, agree)
    }

    /// A read that found nothing. Returns whether the lock still holds.
    mutating func miss() -> Bool {
        misses += 1
        if misses >= 6 {
            held = nil
            window.removeAll()
        }
        return held != nil
    }

    private var median: ObjectEstimate? {
        guard !window.isEmpty else { return nil }
        func med(_ v: [Float]) -> Float { v.sorted()[v.count / 2] }
        return ObjectEstimate(
            footprintCentre: SIMD3(med(window.map(\.footprintCentre.x)), med(window.map(\.footprintCentre.y)),
                                   med(window.map(\.footprintCentre.z))),
            width: med(window.map(\.width)), height: med(window.map(\.height)), depth: med(window.map(\.depth))
        )
    }
}

/// Stops warnings flickering: an issue must persist ~0.2 s to show and be clear ~0.3 s to hide.
private struct IssueDebounce {
    private var candidate: CaptureIssue?
    private var count = 0
    private var shown: CaptureIssue?
    private var clearCount = 0

    mutating func feed(_ issue: CaptureIssue?) -> CaptureIssue? {
        if let issue {
            clearCount = 0
            count = issue == candidate ? count + 1 : 1
            candidate = issue
            if count >= 6 { shown = issue }
        } else {
            candidate = nil
            count = 0
            clearCount += 1
            if clearCount >= 10 { shown = nil }
        }
        return shown
    }
}
