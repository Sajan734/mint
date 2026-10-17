import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// One item = one scan = one or more passes (recordings of it): a lap, then maybe the item flipped
/// over for another, as many as the demonstrator wants.
/// ready → 3·2·1 → recording (until the ring is tapped) → saving → review
/// review: Scan again (→ ready, the next pass) · Done (sends every pass) · discard the last pass.
/// The ring shows how much of one lap has been seen; it's a guide and never ends a pass.
@MainActor
final class CaptureSession: NSObject, ObservableObject {
    enum Phase: Equatable {
        case ready
        case countdown(Int)
        case recording
        case saving
        case review
        case failed(String)
    }

    enum Upload: Equatable {
        case idle
        case notConfigured
        case sending(Double)
        case sent(String)
        case failed(String)
    }

    /// A pass stops by itself only here: Storage takes 50 MB per file and the video is ~1 MB/s.
    static let maxPassSeconds: TimeInterval = 45
    static let segments = 12
    static let tintSamples = 25

    @Published private(set) var phase: Phase = .ready
    @Published private(set) var recordStart: Date?
    /// The item being scanned: every pass is stored under this id.
    @Published private(set) var scanID = UUID().uuidString.lowercased()
    @Published private(set) var passes: [VideoRecorder.Summary] = []
    /// How much of one lap has been seen (`TurnCoverage`): measured from the paper's turn, nothing scripted.
    @Published private(set) var percent = 0
    /// The ring's arcs, 0…1: slices of the item's sides, lit as they've been seen head-on.
    @Published private(set) var ring: [Double] = Array(repeating: 0, count: segments)
    /// How well each side of the item has been seen, sampled across its silhouette from one edge to the
    /// other along `tintAxis` (view space): the overlay paints the item mintier where it's been seen.
    @Published private(set) var tint: [Double] = []
    @Published private(set) var tintAxis = CGVector(dx: 1, dy: 0)
    /// The sheet's edges were read in the last moment (false: no paper, or hands covering it).
    @Published private(set) var paperSeen = false
    @Published private(set) var outline: [CGPoint] = []      // view points, smoothed
    @Published private(set) var sparkles: [CGPoint] = []     // ARKit feature points on/near the item, view points
    @Published private(set) var upload: Upload = .idle

    var isRecording: Bool { phase == .recording }
    var nextPass: Int { passes.count + 1 }

    let arView: ARView
    private let loop = CaptureLoop()
    private var smoother = OutlineSmoother()
    private var lastOutlineAt = Date.distantPast
    private var ticker: Timer?
    private var turn = PaperTurn()
    private var coverage = TurnCoverage()
    private var lastObservation: TimeInterval?
    private var lastPaperAt = Date.distantPast
    private var fullArcs: Set<Int> = []
    private var exposureLocked = false
    private let tick = UIImpactFeedbackGenerator(style: .light)
    private let bump = UIImpactFeedbackGenerator(style: .heavy)
    private let success = UINotificationFeedbackGenerator()

    override init() {
        arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        super.init()
        arView.renderOptions = [.disableMotionBlur, .disableDepthOfField, .disablePersonOcclusion, .disableHDR,
                                .disableGroundingShadows, .disableAREnvironmentLighting]
        arView.session.delegate = loop
        arView.session.delegateQueue = loop.queue
        loop.onSight = { [weak self] in self?.apply($0) }
    }

    func run() {
        let config = ARWorldTrackingConfiguration()
        // Full 4:3 sensor frames: ARKit's K refers to exactly these pixels (the poses stay exact).
        if let format = ARWorldTrackingConfiguration.supportedVideoFormats
            .filter({ $0.imageResolution == CGSize(width: 1920, height: 1440) })
            .max(by: { $0.framesPerSecond < $1.framesPerSecond }) {
            config.videoFormat = format
        }
        arView.session.run(config, options: [.resetTracking])
        ticker?.invalidate()
        ticker = Timer.scheduledTimer(withTimeInterval: 1.0 / 15, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.onTick() }
        }
    }

    func pause() {
        if phase == .recording || phase.isCountdown { cancel() }
        arView.session.pause()
        ticker?.invalidate()
    }

    /// The big button: start a pass (with a countdown), or finish it.
    func primaryAction() {
        switch phase {
        case .ready: Task { await countdownAndRecord() }
        case .recording: stop()
        default: break
        }
    }

    /// Another pass of the same item (flipped over, another height, touch-ups).
    func scanAgain() {
        guard phase == .review, upload == .idle else { return }
        resetCoverage()
        phase = .ready
    }

    /// Throws away the most recent pass.
    func discardLastPass() {
        guard phase == .review, upload == .idle, let last = passes.popLast() else { return }
        try? FileManager.default.removeItem(at: last.directory)
        if passes.isEmpty {
            resetCoverage()
            phase = .ready
        }
    }

    /// Done with this item: send every pass.
    func finish() {
        guard phase == .review, !passes.isEmpty else { return }
        send()
    }

    func retryUpload() { send() }

    /// Start over with a new item.
    func newItem() {
        scanID = UUID().uuidString.lowercased()
        passes = []
        upload = .idle
        recordStart = nil
        resetCoverage()
        phase = .ready
    }

    private func resetCoverage() {
        coverage = TurnCoverage()
        lastObservation = nil
        fullArcs = []
        tint = []
        publishCoverage()
    }

    private func countdownAndRecord() async {
        tick.prepare(); bump.prepare(); success.prepare()
        for n in [3, 2, 1] {
            phase = .countdown(n)
            tick.impactOccurred(intensity: 0.7)
            try? await Task.sleep(nanoseconds: 650_000_000)
            guard phase == .countdown(n) else { return }  // cancelled
        }
        let recorder: VideoRecorder
        do {
            recorder = try VideoRecorder(scanID: scanID, pass: nextPass)
        } catch {
            phase = .failed("Couldn't start recording: \(error.localizedDescription)")
            return
        }
        exposureLocked = CameraLock.lock()
        turn.restart()
        resetCoverage()
        recordStart = Date()
        phase = .recording
        bump.impactOccurred()
        loop.startRecording(recorder)
    }

    private func stop() {
        guard phase == .recording else { return }
        phase = .saving
        success.notificationOccurred(.success)
        let locked = exposureLocked
        let pct = percent
        loop.stopRecording { recorder, sensorSize in
            guard let recorder else {
                DispatchQueue.main.async { MainActor.assumeIsolated { self.phase = .failed("Nothing was recorded.") } }
                return
            }
            recorder.finish(sensorSize: sensorSize, exposureLocked: locked, coveragePct: pct) { result in
                MainActor.assumeIsolated {
                    CameraLock.unlock()
                    switch result {
                    case .success(let s):
                        self.passes.append(s)
                        self.phase = .review
                    case .failure(let e):
                        self.phase = .failed("Couldn't save: \(e.localizedDescription)")
                    }
                }
            }
        }
    }

    private func cancel() {
        loop.cancel()
        CameraLock.unlock()
        phase = passes.isEmpty ? .ready : .review
        recordStart = nil
    }

    private func send() {
        guard SupabaseUploader.functionURL != nil else {
            upload = .notConfigured
            return
        }
        upload = .sending(0)
        let id = scanID, list = passes.map { (directory: $0.directory, pass: $0.pass) }
        Task {
            do {
                let folder = try await SupabaseUploader.upload(scanID: id, passes: list) { p in
                    if case .sending = self.upload { self.upload = .sending(p) }
                }
                upload = .sent(folder)
                success.notificationOccurred(.success)
            } catch {
                upload = .failed(error.localizedDescription)
            }
        }
    }

    /// 15 Hz: the size limit on a pass, sparkles, and whether the paper is in view.
    private func onTick() {
        if phase == .recording, let start = recordStart, Date().timeIntervalSince(start) >= Self.maxPassSeconds { stop() }
        let seen = Date().timeIntervalSince(lastPaperAt) < 0.6
        if seen != paperSeen { paperSeen = seen }
        updateSparkles()
        // The outline fades if the item hasn't been seen for a moment.
        if !outline.isEmpty && Date().timeIntervalSince(lastOutlineAt) > 0.8 {
            outline = []
            smoother = OutlineSmoother()
        }
    }

    /// A new reading of the frame: the outline, and (on paper) how far it has turned, which while
    /// recording is what fills the coverage.
    private func apply(_ sight: SubjectOutliner.Sight) {
        if let reading = sight.paper, turn.update(reading, time: sight.timestamp) {
            lastPaperAt = Date()
            if phase == .recording, let elevation = sight.elevation {
                coverage.observe(turned: turn.turned, elevation: elevation, dt: lastObservation.map { sight.timestamp - $0 } ?? 0)
                lastObservation = sight.timestamp
                publishCoverage()
            }
        }
        applyOutline(sight.outline)
        if phase == .recording || phase.isFinished { updateTint() }
    }

    private func publishCoverage() {
        percent = coverage.percent
        ring = coverage.arcs(band: 0, count: Self.segments).map(Double.init)
        // A tick for every arc that fills, a thump when the lap is done (the pass carries on).
        for (k, f) in ring.enumerated() where f >= 0.98 && !fullArcs.contains(k) {
            fullArcs.insert(k)
            tick.impactOccurred(intensity: 0.5)
            if ring.allSatisfy({ $0 >= 0.98 }) { bump.impactOccurred() }
        }
    }

    /// Samples how well each side has been seen across the silhouette as it faces the camera now,
    /// and which way the item's sides run across the screen (the camera's horizontal right).
    private func updateTint() {
        guard let frame = arView.session.currentFrame else { return }
        let t = frame.camera.transform
        let r = simd_float3x3(SIMD3(t.columns.0.x, t.columns.0.y, t.columns.0.z), SIMD3(t.columns.1.x, t.columns.1.y, t.columns.1.z),
                              SIMD3(t.columns.2.x, t.columns.2.y, t.columns.2.z))
        guard let heading = SheetAngle.HeadingFrame(cameraRotation: r) else { return }
        let size = arView.bounds.size
        let position = SIMD3(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let ahead = position + r * SIMD3<Float>(0, 0, -0.3)
        let a = frame.camera.projectPoint(ahead, orientation: .portrait, viewportSize: size)
        let b = frame.camera.projectPoint(ahead + 0.02 * heading.right, orientation: .portrait, viewportSize: size)
        let len = hypot(b.x - a.x, b.y - a.y)
        if len > 0.5 { tintAxis = CGVector(dx: (b.x - a.x) / len, dy: (b.y - a.y) / len) }
        tint = (0..<Self.tintSamples).map { i in
            let s = Float(i) / Float(Self.tintSamples - 1) * 2 - 1
            return Double(coverage.level(side: coverage.side(atOffset: s)))
        }
    }

    private func applyOutline(_ sensorPoints: SubjectOutliner.Outline?) {
        guard let sensorPoints, let frame = arView.session.currentFrame else { return }
        let size = arView.bounds.size
        guard size.width > 0 else { return }
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        let pts = sensorPoints.map { p -> CGPoint in
            let v = p.applying(toView)
            return CGPoint(x: v.x * size.width, y: v.y * size.height)
        }
        outline = smoother.feed(pts)
        lastOutlineAt = Date()
    }

    /// ARKit's tracked feature points inside the item's outline box: real measured points, drawn as glints.
    private func updateSparkles() {
        guard outline.count > 8, let frame = arView.session.currentFrame, let cloud = frame.rawFeaturePoints else {
            if !sparkles.isEmpty { sparkles = [] }
            return
        }
        let size = arView.bounds.size
        let box = OutlineSmoother.bounds(outline).insetBy(dx: -12, dy: -12)
        var pts: [CGPoint] = []
        for p in cloud.points {
            let v = frame.camera.projectPoint(p, orientation: .portrait, viewportSize: size)
            if box.contains(v) { pts.append(v) }
            if pts.count >= 90 { break }
        }
        sparkles = pts
    }
}

extension CaptureSession.Phase {
    var isCountdown: Bool {
        if case .countdown = self { return true }
        return false
    }

    /// Saving or reviewing: the pass is over and its coverage stays on screen.
    var isFinished: Bool { self == .saving || self == .review }
}

/// Steadies the outline: resample to a fixed number of points by arc length, keep the start point
/// consistent between updates, and ease towards each new outline (Vision updates ~8 Hz).
struct OutlineSmoother {
    static let count = 96
    private var points: [CGPoint] = []

    mutating func feed(_ raw: [CGPoint]) -> [CGPoint] {
        var next = Self.resample(raw, count: Self.count)
        guard next.count == Self.count else { return points }
        guard points.count == Self.count,
              hypot(Self.centroid(points).x - Self.centroid(next).x, Self.centroid(points).y - Self.centroid(next).y) < 90 else {
            points = next
            return next
        }
        // Rotate so the start lines up with the previous outline's start.
        let k = next.indices.min { hypot(next[$0].x - points[0].x, next[$0].y - points[0].y) < hypot(next[$1].x - points[0].x, next[$1].y - points[0].y) }!
        next = Array(next[k...] + next[..<k])
        points = zip(points, next).map { CGPoint(x: $0.x + ($1.x - $0.x) * 0.55, y: $0.y + ($1.y - $0.y) * 0.55) }
        return points
    }

    static func resample(_ pts: [CGPoint], count: Int) -> [CGPoint] {
        guard pts.count >= 3 else { return [] }
        let closed = pts + [pts[0]]
        var lengths: [CGFloat] = [0]
        for i in 1..<closed.count { lengths.append(lengths[i - 1] + hypot(closed[i].x - closed[i - 1].x, closed[i].y - closed[i - 1].y)) }
        let total = lengths.last!
        guard total > 0 else { return [] }
        var out: [CGPoint] = []
        var j = 1
        for i in 0..<count {
            let d = total * CGFloat(i) / CGFloat(count)
            while j < lengths.count - 1 && lengths[j] < d { j += 1 }
            let seg = lengths[j] - lengths[j - 1]
            let f = seg > 0 ? (d - lengths[j - 1]) / seg : 0
            out.append(CGPoint(x: closed[j - 1].x + (closed[j].x - closed[j - 1].x) * f,
                               y: closed[j - 1].y + (closed[j].y - closed[j - 1].y) * f))
        }
        return out
    }

    static func centroid(_ pts: [CGPoint]) -> CGPoint {
        let n = CGFloat(max(pts.count, 1))
        return CGPoint(x: pts.reduce(0) { $0 + $1.x } / n, y: pts.reduce(0) { $0 + $1.y } / n)
    }

    static func bounds(_ pts: [CGPoint]) -> CGRect {
        guard let x0 = pts.map(\.x).min(), let x1 = pts.map(\.x).max(),
              let y0 = pts.map(\.y).min(), let y1 = pts.map(\.y).max() else { return .zero }
        return CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }
}
