import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// The app, start to finish, for one product at a time:
///
///   waiting  ── "New product" on the seller's dashboard (or its QR link, or "scan without the dashboard")
///      ↓
///   ready → recording (until the stop button) → saving → review ─┬─ Scan again → ready (the next pass)
///                                                                ├─ Discard the last pass
///                                                                └─ Done → sending → finished ("look at your computer")
///                                                                                       ↓ (next request, or Next product)
///                                                                                    waiting
///
/// One product = one scan_id = one or more passes (a lap, then maybe flipped over, …). The ring shows
/// how much of one lap has been seen, measured from the paper's turn; it's a guide and never ends a pass.
@MainActor
final class CaptureSession: NSObject, ObservableObject {
    enum Phase: Equatable {
        case waiting
        case ready
        case recording
        case saving
        case review
        case sending(Double)
        case finished
        case failed(String)
    }

    /// The product being scanned.
    struct Job: Equatable {
        let scanID: String
        let fromDashboard: Bool
        let title: String?
    }

    /// Whether the dashboard can be reached (shown on the waiting screen).
    enum Link: Equatable { case notSetUp, connecting, online, offline }

    /// A pass stops by itself only here: Storage takes 50 MB per file and the video is ~1 MB/s.
    static let maxPassSeconds: TimeInterval = 45
    /// Ticks round the ring: 5° each, clockwise from the top, like the item's sides seen from above.
    static let tickCount = 72

    @Published private(set) var phase: Phase = .waiting
    @Published private(set) var job: Job?
    @Published private(set) var link: Link = DashboardLink.url == nil ? .notSetUp : .connecting
    @Published private(set) var recordStart: Date?
    @Published private(set) var passes: [VideoRecorder.Summary] = []
    /// How much of one lap has been seen (`TurnCoverage`): measured from the paper's turn, nothing scripted.
    @Published private(set) var percent = 0
    /// ticks[i], 0…1: how well the side at tick i (clockwise from the top) has been seen head-on.
    @Published private(set) var ticks: [Double] = Array(repeating: 0, count: tickCount)
    /// Where the camera is looking round the item now, as a ring angle (radians, clockwise from the top).
    @Published private(set) var facingAngle: Double = 0
    @Published private(set) var lapCompletedAt: Date?
    /// The sheet's edges were read in the last moment (false: no paper, or hands covering it).
    @Published private(set) var paperSeen = false

    var isRecording: Bool { phase == .recording }
    var inScanner: Bool { ([.ready, .recording, .saving, .review] as [Phase]).contains(phase) }
    var nextPass: Int { passes.count + 1 }

    let arView: ARView
    private let loop = CaptureLoop()
    private var ticker: Timer?
    private var poller: Task<Void, Never>?
    private var handled: Set<String> = []
    private var linkFailures = 0
    private var turn = PaperTurn()
    private var coverage = TurnCoverage()
    private var lastObservation: TimeInterval?
    private var lastPaperAt = Date.distantPast
    private var fullSlices = 0
    private var reportedTenth = -1
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

    // MARK: - Lifecycle

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
        startPolling()
        #if DEBUG
        if let screen = UserDefaults.standard.string(forKey: "MintPreview") { preview(screen) }
        #endif
    }

    func pause() {
        if phase == .recording { cancelPass() }
        arView.session.pause()
        ticker?.invalidate()
        poller?.cancel()
        poller = nil
    }

    // MARK: - Getting a product to scan

    /// While waiting (or showing "done"), ask the dashboard for the next "New product" every 1.5 s.
    private func startPolling() {
        poller?.cancel()
        guard DashboardLink.url != nil else { link = .notSetUp; return }
        poller = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if self.phase == .waiting || self.phase == .finished {
                    do {
                        let request = try await DashboardLink.next()
                        self.linkFailures = 0
                        self.link = .online
                        if let request, !self.handled.contains(request.scan_id),
                           self.phase == .waiting || self.phase == .finished {
                            self.begin(Job(scanID: request.scan_id, fromDashboard: true, title: request.title))
                        }
                    } catch {
                        self.linkFailures += 1
                        if self.linkFailures >= 2 { self.link = .offline }
                    }
                }
                try? await Task.sleep(nanoseconds: 1_500_000_000)
            }
        }
    }

    /// The dashboard's QR link (`mintscan://scan?scan_id=…`) opened the app.
    func open(_ url: URL) {
        guard let id = DashboardLink.scanID(from: url), !inScanner, !isSending, !handled.contains(id) else { return }
        begin(Job(scanID: id, fromDashboard: true, title: nil))
    }

    /// No dashboard: scan anyway (the product gets its own scan_id).
    func scanWithoutDashboard() {
        begin(Job(scanID: UUID().uuidString.lowercased(), fromDashboard: false, title: nil))
    }

    private func begin(_ job: Job) {
        handled.insert(job.scanID)
        self.job = job
        passes = []
        resetCoverage()
        phase = .ready
        success.notificationOccurred(.success)
        DashboardLink.report(.scanning, scanID: job.scanID, passes: 0)
    }

    /// Give up on this product (from the scanner, before sending): its passes are deleted.
    func cancelJob() {
        guard let job, phase == .ready || phase == .review else { return }
        try? FileManager.default.removeItem(at: VideoRecorder.folder(scanID: job.scanID))
        DashboardLink.report(.cancelled, scanID: job.scanID, passes: 0)
        backToWaiting()
    }

    func backToWaiting() {
        job = nil
        passes = []
        recordStart = nil
        resetCoverage()
        phase = .waiting
    }

    // MARK: - Passes

    /// The big button: start a pass, or finish it.
    func primaryAction() {
        switch phase {
        case .ready: startPass()
        case .recording: stopPass()
        default: break
        }
    }

    /// Another pass of the same product (flipped over, another height, touch-ups).
    func scanAgain() {
        guard phase == .review else { return }
        resetCoverage()
        phase = .ready
    }

    /// Throws away the most recent pass.
    func discardLastPass() {
        guard phase == .review, let job, let last = passes.popLast() else { return }
        try? FileManager.default.removeItem(at: last.directory)
        DashboardLink.report(.scanning, scanID: job.scanID, passes: passes.count)
        if passes.isEmpty {
            resetCoverage()
            phase = .ready
        }
    }

    private func resetCoverage() {
        coverage = TurnCoverage()
        lastObservation = nil
        fullSlices = 0
        lapCompletedAt = nil
        facingAngle = 0
        publishCoverage()
    }

    private func startPass() {
        guard let job else { return }
        let recorder: VideoRecorder
        do {
            recorder = try VideoRecorder(scanID: job.scanID, pass: nextPass)
        } catch {
            phase = .failed("Couldn't start recording: \(error.localizedDescription)")
            return
        }
        tick.prepare(); bump.prepare(); success.prepare()
        exposureLocked = CameraLock.lock()
        turn.restart()
        resetCoverage()
        recordStart = Date()
        phase = .recording
        bump.impactOccurred()
        loop.startRecording(recorder)
    }

    private func stopPass() {
        guard phase == .recording else { return }
        phase = .saving
        bump.impactOccurred()
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
                        if let job = self.job { DashboardLink.report(.scanning, scanID: job.scanID, passes: self.passes.count) }
                    case .failure(let e):
                        self.phase = .failed("Couldn't save: \(e.localizedDescription)")
                    }
                }
            }
        }
    }

    private func cancelPass() {
        loop.cancel()
        CameraLock.unlock()
        phase = passes.isEmpty ? .ready : .review
        recordStart = nil
    }

    // MARK: - Sending

    var isSending: Bool {
        if case .sending = phase { return true }
        return false
    }

    /// Done with this product: send every pass, then tell the seller to look at their computer.
    func finish() {
        guard phase == .review, let job, !passes.isEmpty else { return }
        send(job)
    }

    func retrySend() {
        guard case .failed = phase, let job, !passes.isEmpty else { return }
        send(job)
    }

    private func send(_ job: Job) {
        phase = .sending(0)
        reportedTenth = -1
        let count = passes.count
        let list = passes.map { (directory: $0.directory, pass: $0.pass) }
        DashboardLink.report(.uploading, scanID: job.scanID, passes: count, progress: 0)
        Task {
            do {
                _ = try await SupabaseUploader.upload(scanID: job.scanID, passes: list) { p in
                    guard self.isSending else { return }
                    self.phase = .sending(p)
                    let tenth = Int(p * 10)
                    if tenth != self.reportedTenth {
                        self.reportedTenth = tenth
                        DashboardLink.report(.uploading, scanID: job.scanID, passes: count, progress: p)
                    }
                }
                DashboardLink.report(.uploaded, scanID: job.scanID, passes: count, progress: 1)
                success.notificationOccurred(.success)
                phase = .finished
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    // MARK: - Measuring

    /// 15 Hz: the size limit on a pass, and whether the paper is in view.
    private func onTick() {
        if phase == .recording, let start = recordStart, Date().timeIntervalSince(start) >= Self.maxPassSeconds { stopPass() }
        let seen = Date().timeIntervalSince(lastPaperAt) < 0.6
        if seen != paperSeen { paperSeen = seen }
    }

    /// A new reading of the frame: how far the paper has turned, which while recording fills the coverage.
    private func apply(_ sight: PaperReader.Sight) {
        guard let reading = sight.paper, turn.update(reading, time: sight.timestamp) else { return }
        lastPaperAt = Date()
        guard phase == .recording, let elevation = sight.elevation else { return }
        coverage.observe(turned: turn.turned, elevation: elevation, dt: lastObservation.map { sight.timestamp - $0 } ?? 0)
        lastObservation = sight.timestamp
        publishCoverage()
    }

    private func publishCoverage() {
        percent = coverage.percent
        // Tick i sits at i × 5° clockwise from the top and shows the side that faces the camera when the
        // paper has turned that far clockwise (`TurnCoverage.facing` = −turned), so turning the paper
        // clockwise lights the ring clockwise.
        ticks = (0..<Self.tickCount).map { i in
            Double(coverage.level(side: -Float(i) / Float(Self.tickCount) * 2 * .pi))
        }
        facingAngle = Double(-coverage.facing)
        // A tick of the phone for every 10° slice that fills, a big one when the lap is done (the pass carries on).
        let full = coverage.fill[0].filter { $0 >= 0.98 }.count
        if full > fullSlices && phase == .recording { tick.impactOccurred(intensity: 0.45) }
        fullSlices = full
        if percent >= 100, lapCompletedAt == nil, phase == .recording {
            lapCompletedAt = Date()
            success.notificationOccurred(.success)
        }
    }

    #if DEBUG
    /// Design check only (Debug builds, Simulator): `-MintPreview ready|recording|full|review|sending|finished|failed`
    /// puts the app on that screen with made-up coverage so the layout can be screenshotted without ARKit.
    /// Never in a Release build, never on stage.
    private func preview(_ screen: String) {
        poller?.cancel()
        job = Job(scanID: UUID().uuidString.lowercased(), fromDashboard: true, title: "Logitech M325 mouse")
        let fake = VideoRecorder.Summary(directory: URL(fileURLWithPath: "/nonexistent"), scanID: job!.scanID, pass: 1,
                                         seconds: 23, frames: 690, megabytes: 23)
        lastPaperAt = .distantFuture
        let fill = { (deg: Double) in
            self.ticks = (0..<Self.tickCount).map { i in Double(i) * 5 < deg ? 1 : (Double(i) * 5 < deg + 25 ? 0.4 : 0) }
            self.facingAngle = deg * .pi / 180
            self.percent = Int(min(100, deg / 3.15))
        }
        switch screen {
        case "ready": phase = .ready
        case "recording": recordStart = Date().addingTimeInterval(-9); fill(205); phase = .recording
        case "full": recordStart = Date().addingTimeInterval(-17); fill(360); lapCompletedAt = Date(); phase = .recording
        case "review": fill(360); passes = [fake]; phase = .review
        case "sending": passes = [fake, fake]; phase = .sending(0.62)
        case "finished": passes = [fake]; phase = .finished
        case "failed": passes = [fake]; phase = .failed("Couldn't get upload links: {\"code\":\"NOT_FOUND\"}")
        default: link = .online
        }
    }
    #endif
}
