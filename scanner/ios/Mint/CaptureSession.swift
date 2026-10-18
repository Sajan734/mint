import ARKit
import Combine
import CoverageKit
import RealityKit
import UIKit

/// The app, start to finish, for one product at a time:
///
///   waiting  ── a mint:// link from the website (QR code read by the iPhone camera or by this screen),
///      │        the dashboard's auto-pickup, or "scan without the dashboard"
///      ↓
///   ready → recording (until the stop button) → saving → review ─┬─ Scan again → ready (the next pass)
///                                                                ├─ Discard the last pass
///                                                                └─ Done → sending → finished ("look at your computer")
///                                                                                       ↓ (next request, or Next product)
///                                                                                    waiting
///
/// One product = one scan_id = one or more passes (a lap, then maybe flipped over, …). A job is either a
/// seller's listing scan or a buyer's verify rescan of a listing (in-person deal). The ring shows how
/// much of one lap has been seen, measured from the paper's turn; it's a guide and never ends a pass.
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
        /// A buyer's verify rescan of this listing (nil: a seller's listing scan).
        var listingID: String? = nil
        var isVerify: Bool { listingID != nil }
    }

    /// Whether the dashboard can be reached (shown on the waiting screen).
    enum Link: Equatable { case notSetUp, connecting, online, offline }

    /// A pass stops by itself only here: Storage takes 50 MB per file and the video is ~1 MB/s.
    static let maxPassSeconds: TimeInterval = 45
    /// Ticks round the ring: 5° each, clockwise from the top, like the item's sides seen from above.
    static let tickCount = 72

    @Published private(set) var phase: Phase = .waiting {
        didSet { loop.lookForCodes = phase.readsCodes }
    }
    @Published private(set) var job: Job?
    @Published private(set) var link: Link = DashboardLink.url == nil ? .notSetUp : .connecting
    @Published private(set) var recordStart: Date?
    @Published private(set) var passes: [VideoRecorder.Summary] = []
    /// How much of one lap has been seen (`TurnCoverage`): measured from the paper's turn, nothing scripted.
    @Published private(set) var percent = 0
    /// ticks[i], 0…1: how well the item's side i × 5° (clockwise from above, from the side that faced the
    /// camera at the start) has been seen head-on.
    @Published private(set) var ticks: [Double] = Array(repeating: 0, count: tickCount)
    /// How far the paper has turned this pass (radians, clockwise from above), eased for display: the ring's
    /// bright spot sits at this angle (clockwise from the top), on the side the camera is looking at now.
    @Published private(set) var ringTurn: Double = 0
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
    private var sent: Set<String> = []
    private var linkFailures = 0
    private var turn = PaperTurn()
    private var coverage = TurnCoverage()
    private var lastObservation: TimeInterval?
    private var lastPaperAt = Date.distantPast
    private var fullSlices = 0
    private var previewing = false   // Debug screen previews only
    private var reportedTenth = -1
    private var exposureLocked = false
    /// The AR session should be running (between `run()` and `pause()`).
    private(set) var isRunning = false
    private var startedAt = Date.distantPast
    private var lastRestart = Date.distantPast
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
        loop.onNeedsRestart = { [weak self] _ in self?.restartCamera() }
        // `phase` starts at .waiting without running its didSet: read QR codes from the very first screen.
        loop.lookForCodes = phase.readsCodes
    }

    // MARK: - Lifecycle

    /// Starts the camera, AR tracking, the 30 Hz tick and the dashboard polling. Safe to call again.
    func run() {
        arView.session.run(Self.configuration(), options: [.resetTracking])
        isRunning = true
        startedAt = Date()
        ticker?.invalidate()
        ticker = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.onTick() }
        }
        startPolling()
        #if DEBUG
        if let screen = UserDefaults.standard.string(forKey: "MintPreview") { preview(screen) }
        #endif
    }

    /// Back in the foreground (from the Camera app's QR banner, the app switcher, a call…): run again if paused.
    func resume() {
        if !isRunning { run() }
    }

    private static func configuration() -> ARWorldTrackingConfiguration {
        let config = ARWorldTrackingConfiguration()
        // Full 4:3 sensor frames from the main (1x, wide-angle) back camera: ARKit's K refers to exactly these
        // pixels (the poses stay exact). Asking for the wide camera by name: a format is otherwise picked by size
        // and frame rate alone, which on some iPhones can land on the ultra-wide, with softer edges and weaker
        // autofocus up close.
        let formats = ARWorldTrackingConfiguration.supportedVideoFormats
            .filter { $0.imageResolution == CGSize(width: 1920, height: 1440) }
        let wide = formats.filter { $0.captureDeviceType == .builtInWideAngleCamera && $0.captureDevicePosition == .back }
        if let format = (wide.isEmpty ? formats : wide).max(by: { $0.framesPerSecond < $1.framesPerSecond }) {
            config.videoFormat = format
        }
        config.isAutoFocusEnabled = true
        return config
    }

    func pause() {
        if phase == .recording { cancelPass() }
        arView.session.pause()
        isRunning = false
        ticker?.invalidate()
        poller?.cancel()
        poller = nil
    }

    /// The camera stopped while the app is open (frozen preview: no frames for a while, the camera came back
    /// from another app, or the session failed). Run the session again; mid-pass, keep its tracking so the
    /// pass's poses stay in one world. At most once every 2 s.
    private func restartCamera() {
        guard isRunning, Date().timeIntervalSince(lastRestart) > 2 else { return }
        lastRestart = Date()
        arView.session.run(Self.configuration(), options: phase == .recording ? [] : [.resetTracking])
        if phase == .recording { CameraLock.lock() }
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
                            let listing = request.kind == "verify" ? request.listing_scan_id : nil
                            self.begin(Job(scanID: request.scan_id, fromDashboard: true, title: request.title, listingID: listing))
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

    /// A website link (`mint://scan?id=…` / `mint://verify?id=…&listing=…`) opened the app, or its QR code
    /// was read on the waiting screen.
    func open(_ url: URL) { follow(url.absoluteString, explicit: true) }

    /// `explicit`: the link was opened on purpose (tapped, or from the Camera app's QR banner). Such a link
    /// always wins, unless that scan was already sent or something has been recorded for the current one.
    /// A QR code read by this app's own camera never reopens an id it has seen: a cancelled scan's QR may
    /// still be on the laptop's screen.
    private func follow(_ text: String, explicit: Bool = false) {
        guard let link = DashboardLink.parse(text), !isSending, !sent.contains(link.scanID), link.scanID != job?.scanID,
              explicit || !handled.contains(link.scanID) else { return }
        if inScanner {
            // In the scanner only before anything was recorded: drop that job for the new one.
            guard phase == .ready, passes.isEmpty, let old = job else { return }
            DashboardLink.report(.cancelled, scanID: old.scanID, passes: 0)
        }
        begin(Job(scanID: link.scanID, fromDashboard: true, title: nil, listingID: link.listingID))
    }

    /// No dashboard: scan anyway (the product gets its own scan_id).
    func scanWithoutDashboard() {
        begin(Job(scanID: UUID().uuidString.lowercased(), fromDashboard: false, title: nil))
    }

    private func begin(_ job: Job) {
        handled.insert(job.scanID)
        CameraLock.unlock(resetPoint: true)   // a new item: focus on the middle until tapped
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
        CameraLock.unlock(resetPoint: true)
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
        ringTurn = 0
        publishCoverage()
    }

    private func startPass() {
        guard let job else { return }
        let recorder: VideoRecorder
        do {
            recorder = try VideoRecorder(scanID: job.scanID, pass: nextPass, listingID: job.listingID)
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
                _ = try await SupabaseUploader.upload(scanID: job.scanID, passes: list, verify: job.isVerify) { p in
                    guard self.isSending else { return }
                    self.phase = .sending(p)
                    let tenth = Int(p * 10)
                    if tenth != self.reportedTenth {
                        self.reportedTenth = tenth
                        DashboardLink.report(.uploading, scanID: job.scanID, passes: count, progress: p)
                    }
                }
                sent.insert(job.scanID)
                DashboardLink.report(.uploaded, scanID: job.scanID, passes: count, progress: 1)
                success.notificationOccurred(.success)
                phase = .finished
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    // MARK: - Measuring

    /// 30 Hz: the size limit on a pass, whether the paper is in view, and easing the ring's turn towards the
    /// latest reading (they come ~8 times a second).
    private func onTick() {
        // Watchdog: frames normally arrive 30–60 times a second. None for 1.5 s (and not just started) = frozen.
        let now = Date()
        if isRunning, now.timeIntervalSince(startedAt) > 3,
           ProcessInfo.processInfo.systemUptime - loop.lastFrameAt > 1.5 { restartCamera() }
        if phase == .recording, let start = recordStart, Date().timeIntervalSince(start) >= Self.maxPassSeconds { stopPass() }
        let seen = Date().timeIntervalSince(lastPaperAt) < 0.6
        if seen != paperSeen { paperSeen = seen }
        // The ring follows the paper while recording, then stays where the paper stopped.
        let goal = Double(turn.turned)
        if phase == .recording, lapCompletedAt == nil, !previewing, abs(goal - ringTurn) > 0.0005 { ringTurn += (goal - ringTurn) * 0.3 }
    }

    /// A new reading of the frame: a QR code (while waiting), or how far the paper has turned, which while
    /// recording fills the coverage.
    private func apply(_ sight: PaperReader.Sight) {
        if let code = sight.code { follow(code) }
        guard let reading = sight.paper, turn.update(reading, time: sight.timestamp) else { return }
        lastPaperAt = Date()
        // Once the lap is done the measurement stops: hand-held touch-ups (walking round, other heights)
        // vary run to run, and the ring just stays full.
        guard phase == .recording, lapCompletedAt == nil, let elevation = sight.elevation else { return }
        coverage.observe(turned: turn.turned, elevation: elevation, dt: lastObservation.map { sight.timestamp - $0 } ?? 0)
        lastObservation = sight.timestamp
        publishCoverage()
    }

    // MARK: - Tap to focus

    /// Focus where the screen was tapped (window points), like the Camera app. Before a scan, focus and exposure
    /// follow that point until the scan starts and locks them; during a scan, focus runs once there and holds
    /// (exposure stays locked). false: the tap wasn't on the camera picture, or the camera can't be set.
    @discardableResult
    func focus(atScreen point: CGPoint) -> Bool {
        guard isRunning, phase == .waiting || phase == .ready || phase == .recording,
              let frame = arView.session.currentFrame else { return false }
        let size = arView.bounds.size
        let p = arView.convert(point, from: nil)
        guard size.width > 0, size.height > 0, arView.bounds.contains(p) else { return false }
        // View → sensor-normalized (the camera's landscape image, top-left origin): the inverse of how the
        // camera image is laid onto the view.
        let toView = frame.displayTransform(for: .portrait, viewportSize: size)
        let sensor = CGPoint(x: p.x / size.width, y: p.y / size.height).applying(toView.inverted())
        let target = CGPoint(x: min(max(sensor.x, 0), 1), y: min(max(sensor.y, 0), 1))
        guard CameraLock.focus(at: target, holdExposure: phase == .recording) else { return false }
        tick.impactOccurred(intensity: 0.6)
        return true
    }

    private func publishCoverage() {
        percent = coverage.percent
        ticks = (0..<Self.tickCount).map { i in
            Double(coverage.level(side: Float(i) / Float(Self.tickCount) * 2 * .pi))
        }
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
        previewing = true
        job = Job(scanID: UUID().uuidString.lowercased(), fromDashboard: true, title: "Logitech M325 mouse",
                  listingID: screen.hasPrefix("verify") ? UUID().uuidString.lowercased() : nil)
        let fake = VideoRecorder.Summary(directory: URL(fileURLWithPath: "/nonexistent"), scanID: job!.scanID, pass: 1,
                                         seconds: 23, frames: 690, megabytes: 23)
        lastPaperAt = .distantFuture
        // Made-up coverage: the paper turned `deg` clockwise, so sides −deg…0 have been seen.
        let fill = { (deg: Double) in
            self.ticks = (0..<Self.tickCount).map { i in
                let side = (360 - Double(i) * 5).truncatingRemainder(dividingBy: 360)
                return side <= deg ? 1 : (side <= deg + 20 ? 0.4 : 0)
            }
            self.ringTurn = deg * .pi / 180
            self.percent = Int(min(100, deg / 3.15))
        }
        switch screen {
        case "ready": phase = .ready
        case "early": recordStart = Date().addingTimeInterval(-4); fill(120); phase = .recording
        case "recording", "verify": recordStart = Date().addingTimeInterval(-9); fill(205); phase = .recording
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
