import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// The whole capture, start to finish:
/// ready → 3·2·1 → recording (20 s: lap 1, then lap 2 with the phone raised) → saving → done
/// (uploading to Supabase in the background of the done card).
@MainActor
final class CaptureSession: NSObject, ObservableObject {
    enum Phase: Equatable {
        case ready
        case countdown(Int)
        case recording
        case saving
        case done(VideoRecorder.Summary)
        case failed(String)
    }

    enum Upload: Equatable {
        case notConfigured
        case sending(Double)
        case sent(String)
        case failed(String)
    }

    static let duration: TimeInterval = 20
    static let segments = 12   // per height ring
    static let tintSamples = 25

    @Published private(set) var phase: Phase = .ready
    @Published private(set) var recordStart: Date?
    /// How much of the item has been seen (`TurnCoverage`): measured from the paper's turn and the
    /// camera's height, nothing scripted.
    @Published private(set) var percent = 0
    /// rings[height][arc], 0…1: the first height's ring, then the other height's.
    @Published private(set) var rings: [[Double]] = Array(repeating: Array(repeating: 0, count: segments), count: 2)
    /// How well each side of the item has been seen, sampled across its silhouette from one edge to the
    /// other along `tintAxis` (view space): the overlay paints the item mintier where it's been seen.
    @Published private(set) var tint: [Double] = []
    @Published private(set) var tintAxis = CGVector(dx: 1, dy: 0)
    /// The sheet's edges were read in the last moment (false: no paper, or hands covering it).
    @Published private(set) var paperSeen = false
    @Published private(set) var outline: [CGPoint] = []      // view points, smoothed
    @Published private(set) var sparkles: [CGPoint] = []     // ARKit feature points on/near the item, view points
    @Published private(set) var upload: Upload = .notConfigured

    var isRecording: Bool { phase == .recording }

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

    /// The big button: start (with a countdown), or finish early.
    func primaryAction() {
        switch phase {
        case .ready: Task { await countdownAndRecord() }
        case .recording: stop()
        default: break
        }
    }

    func newScan() {
        phase = .ready
        recordStart = nil
        upload = .notConfigured
        coverage = TurnCoverage()
        tint = []
        publishCoverage()
    }

    func retryUpload() {
        if case .done(let s) = phase { send(s) }
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
            recorder = try VideoRecorder()
        } catch {
            phase = .failed("Couldn't start recording: \(error.localizedDescription)")
            return
        }
        exposureLocked = CameraLock.lock()
        turn.restart()
        coverage = TurnCoverage()
        lastObservation = nil
        fullArcs = []
        publishCoverage()
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
        loop.stopRecording { recorder, sensorSize in
            guard let recorder else {
                DispatchQueue.main.async { MainActor.assumeIsolated { self.phase = .failed("Nothing was recorded.") } }
                return
            }
            recorder.finish(sensorSize: sensorSize, exposureLocked: locked) { result in
                MainActor.assumeIsolated {
                    CameraLock.unlock()
                    switch result {
                    case .success(let s):
                        self.phase = .done(s)
                        self.send(s)
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
        phase = .ready
        recordStart = nil
    }

    private func send(_ s: VideoRecorder.Summary) {
        guard SupabaseUploader.functionURL != nil else {
            upload = .notConfigured
            return
        }
        upload = .sending(0)
        Task {
            do {
                let path = try await SupabaseUploader.upload(directory: s.directory, scanID: s.scanID) { p in
                    if case .sending = self.upload { self.upload = .sending(p) }
                }
                upload = .sent(path)
                success.notificationOccurred(.success)
            } catch {
                upload = .failed(error.localizedDescription)
            }
        }
    }

    /// 15 Hz: recording clock (auto-stop at 20 s), sparkles, and whether the paper is in view.
    private func onTick() {
        if phase == .recording, let start = recordStart, Date().timeIntervalSince(start) >= Self.duration { stop() }
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
        rings = (0..<TurnCoverage.bands).map { b in coverage.arcs(band: b, count: Self.segments).map(Double.init) }
        // A tick for every arc that fills, a thump when a whole height is done.
        for b in 0..<TurnCoverage.bands {
            for (k, f) in rings[b].enumerated() where f >= 0.98 && !fullArcs.contains(b * Self.segments + k) {
                fullArcs.insert(b * Self.segments + k)
                tick.impactOccurred(intensity: 0.5)
                if rings[b].allSatisfy({ $0 >= 0.98 }) { bump.impactOccurred() }
            }
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

    /// Saving or done: the scan is over and its coverage stays on screen.
    var isFinished: Bool {
        if case .done = self { return true }
        return self == .saving
    }
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
