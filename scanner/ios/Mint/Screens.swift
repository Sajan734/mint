import SwiftUI

/// The full-screen moments around the scanner: waiting for the dashboard, sending, done, failed,
/// and the card after each pass.

/// Covers the live camera behind a full-screen moment.
private struct Backdrop: View {
    var body: some View {
        // Light: paper over the camera, like the website's pages.
        Rectangle().fill(Color.brandPaper.opacity(0.97)).ignoresSafeArea()
    }
}

/// Rings rippling out from the middle (waiting, done).
private struct Ripples: View {
    var color: Color = .brandMint
    var body: some View {
        TimelineView(.animation) { ctx in
            Canvas { g, size in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let t = ctx.date.timeIntervalSinceReferenceDate
                for k in 0..<3 {
                    let f = (t / 2.4 + Double(k) / 3).truncatingRemainder(dividingBy: 1)
                    let r = 46 + f * (min(size.width, size.height) / 2 - 46)
                    g.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)),
                             with: .color(color.opacity(0.5 * (1 - f))), lineWidth: 1.5)
                }
            }
        }
    }
}

// MARK: - Waiting for the dashboard

struct WaitingScreen: View {
    @ObservedObject var session: CaptureSession

    var body: some View {
        ZStack {
            // Paper over the camera, with a window in the middle where the live camera shows: you can see the QR
            // code you're aiming at. The camera reads the whole frame, so the code needn't sit exactly in the window.
            GeometryReader { geo in
                let window = Self.window(in: geo.size)
                ZStack(alignment: .top) {
                    Path { p in
                        p.addRect(CGRect(origin: .zero, size: geo.size))
                        p.addRoundedRect(in: window, cornerSize: CGSize(width: 30, height: 30), style: .continuous)
                    }
                    .fill(Color.brandPaper.opacity(0.96), style: FillStyle(eoFill: true))
                    QRWindow()
                        .frame(width: window.width, height: window.height)
                        .offset(x: window.minX, y: window.minY)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    VStack(spacing: 0) {
                        Text("Ready when you are")
                            .font(.system(size: 30, weight: .heavy, design: .rounded))
                        Text("Point this phone at the **QR code** on the website\n(Scan an item, or Scan on a listing).")
                            .font(.system(.body, design: .rounded))
                            .multilineTextAlignment(.center)
                            .foregroundStyle(Color.brandInk.opacity(0.75))
                            .padding(.top, 10)
                        if session.link == .online {
                            linkStatus.padding(.top, 18)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, window.maxY + 26)
                }
            }
            .ignoresSafeArea()

            VStack(spacing: 0) {
                HStack { MintMark(); Spacer() }.padding(.top, 6)
                Spacer()
                Button(action: session.scanWithoutDashboard) {
                    Label("Scan without the dashboard", systemImage: "viewfinder")
                        .font(.system(.subheadline, design: .rounded).weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.bordered)
                .tint(Color.brandInk)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .foregroundStyle(Color.brandInk)
    }

    /// The camera window, in full-screen points: a square a little above the middle of the screen, which is the
    /// middle of the camera picture (the part the QR reader looks at twice).
    static func window(in size: CGSize) -> CGRect {
        let side = min(size.width - 110, 260)
        return CGRect(x: (size.width - side) / 2, y: size.height / 2 - side / 2 - 60, width: side, height: side)
    }

    private var linkStatus: some View {
        let (color, text): (Color, String) = switch session.link {
        case .online: (.brandMint, "Connected · New product opens here by itself")
        case .connecting: (Color.brandInk.opacity(0.6), "Connecting to your dashboard…")
        case .offline: (.brandAmber, "Can't reach your dashboard. Check the Wi-Fi.")
        case .notSetUp: (.brandAmber, "Dashboard link isn't set up on this phone")
        }
        return HStack(spacing: 8) {
            Circle().fill(color).frame(width: 8, height: 8).shadow(color: color, radius: session.link == .online ? 5 : 0)
            Text(text).font(.system(.footnote, design: .rounded).weight(.semibold))
        }
        .chip()
        .animation(.easeInOut, value: session.link)
    }
}

/// Corner marks and a sweeping line over the camera window on the waiting screen.
private struct QRWindow: View {
    var body: some View {
        TimelineView(.animation) { ctx in
            Canvas { g, size in
                let r = CGRect(origin: .zero, size: size).insetBy(dx: 2, dy: 2)
                let len: CGFloat = 34, bend: CGFloat = 16
                var marks = Path()
                for (c, dx, dy) in [(CGPoint(x: r.minX, y: r.minY), 1.0, 1.0), (CGPoint(x: r.maxX, y: r.minY), -1.0, 1.0),
                                    (CGPoint(x: r.minX, y: r.maxY), 1.0, -1.0), (CGPoint(x: r.maxX, y: r.maxY), -1.0, -1.0)] {
                    marks.move(to: CGPoint(x: c.x + dx * len, y: c.y))
                    marks.addLine(to: CGPoint(x: c.x + dx * bend, y: c.y))
                    marks.addQuadCurve(to: CGPoint(x: c.x, y: c.y + dy * bend), control: c)
                    marks.addLine(to: CGPoint(x: c.x, y: c.y + dy * len))
                }
                g.stroke(marks, with: .color(.brandMint), style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round))
                // A line sweeping down and up, like a reader at work.
                let f = (sin(ctx.date.timeIntervalSinceReferenceDate * 1.6) + 1) / 2
                let y = r.minY + 22 + f * (r.height - 44)
                let line = Path(CGRect(x: r.minX + 22, y: y - 1, width: r.width - 44, height: 2))
                g.drawLayer { l in
                    l.addFilter(.blur(radius: 6))
                    l.fill(line, with: .color(.brandMint.opacity(0.9)))
                }
                g.fill(line, with: .color(.brandMint))
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - After each pass: another pass, or send them all

struct ReviewCard: View {
    @ObservedObject var session: CaptureSession

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text(session.passes.count == 1 ? "Pass saved" : "\(session.passes.count) passes saved")
                    .font(.system(.title2, design: .rounded).weight(.heavy))
                Spacer()
                if let last = session.passes.last {
                    Text(String(format: "%.0f s · %d frames", last.seconds, last.frames))
                        .font(.system(.subheadline, design: .rounded)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(session.passes, id: \.pass) { p in
                        ZStack(alignment: .bottomLeading) {
                            Thumbnail(directory: p.directory, size: 58)
                            Text("\(p.pass)")
                                .font(.system(.caption, design: .rounded).weight(.heavy))
                                .foregroundStyle(Color.brandStageBg)
                                .frame(width: 20, height: 20)
                                .background(Color.brandMint, in: Circle())
                                .padding(4)
                        }
                    }
                }
            }
            HStack(spacing: 12) {
                Button(action: session.scanAgain) {
                    Label("Scan again", systemImage: "arrow.triangle.2.circlepath").fontWeight(.semibold)
                        .frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.bordered)
                .tint(Color.brandInk)
                Button(action: session.finish) {
                    Label("Done", systemImage: "paperplane.fill").fontWeight(.bold)
                        .frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
            }
            HStack {
                Text("Flip it over or try another angle with **Scan again**.")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
                Button(role: .destructive, action: session.discardLastPass) {
                    Text("Discard pass \(session.passes.last?.pass ?? 1)").font(.footnote.weight(.semibold))
                }
            }
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }
}

struct Thumbnail: View {
    let directory: URL
    let size: CGFloat

    var body: some View {
        if let img = UIImage(contentsOfFile: directory.appendingPathComponent("thumb.jpg").path) {
            Image(uiImage: img).resizable().scaledToFill().frame(width: size, height: size)
                .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous).stroke(Color.brandMint, lineWidth: 2))
        } else {
            RoundedRectangle(cornerRadius: size * 0.22).fill(Color.brandMint.opacity(0.25)).frame(width: size, height: size)
        }
    }
}

// MARK: - Sending

struct SendingScreen: View {
    let progress: Double
    let passes: Int

    var body: some View {
        ZStack {
            Backdrop()
            VStack(spacing: 26) {
                ZStack {
                    Circle().stroke(Color.brandInk.opacity(0.12), lineWidth: 14)
                    Circle().trim(from: 0, to: max(0.02, progress))
                        .stroke(Color.brandMint, style: StrokeStyle(lineWidth: 14, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .shadow(color: .brandMint.opacity(0.7), radius: 12)
                        .animation(.easeOut(duration: 0.3), value: progress)
                    VStack(spacing: 2) {
                        Text("\(Int(progress * 100))%")
                            .font(.system(size: 50, weight: .heavy, design: .rounded)).monospacedDigit()
                            .contentTransition(.numericText(value: progress))
                        Text("SENDING").font(.system(.caption, design: .rounded).weight(.bold)).tracking(2)
                            .foregroundStyle(Color.brandMintInk)
                    }
                }
                .frame(width: 210, height: 210)
                VStack(spacing: 6) {
                    Text("Sending to Mint").font(.system(.title2, design: .rounded).weight(.heavy))
                    Text("\(passes) pass\(passes == 1 ? "" : "es") · keep the app open")
                        .font(.system(.subheadline, design: .rounded)).foregroundStyle(Color.brandInk.opacity(0.65))
                }
            }
        }
        .foregroundStyle(Color.brandInk)
    }
}

// MARK: - Done: look back at the computer

struct FinishedScreen: View {
    @ObservedObject var session: CaptureSession
    @State private var appeared = false

    var body: some View {
        ZStack {
            Backdrop()
            VStack(spacing: 0) {
                HStack { MintMark(); Spacer() }.padding(.top, 6)
                Spacer()
                ZStack {
                    Ripples().frame(width: 320, height: 320)
                    Circle().fill(Color.brandMint).frame(width: 118, height: 118)
                        .shadow(color: .brandMint.opacity(0.8), radius: 30)
                    Image(systemName: "checkmark")
                        .font(.system(size: 54, weight: .heavy))
                        .foregroundStyle(Color.brandStageBg)
                }
                .scaleEffect(appeared ? 1 : 0.4)
                .opacity(appeared ? 1 : 0)
                Text("You're done here")
                    .font(.system(.title3, design: .rounded).weight(.semibold))
                    .foregroundStyle(Color.brandMintInk)
                    .padding(.top, 6)
                HStack(spacing: 12) {
                    Image(systemName: "laptopcomputer").font(.system(size: 30, weight: .semibold))
                    Text(session.job?.isVerify == true ? "Look back at\nthe listing" : "Look back at\nyour computer")
                        .font(.system(size: 34, weight: .heavy, design: .rounded))
                        .multilineTextAlignment(.leading)
                }
                .padding(.top, 10)
                Text(session.job?.isVerify == true
                     ? "Mint is checking this scan against the seller's."
                     : session.job?.fromDashboard == false
                     ? "Your scan is on its way. Open your dashboard to see it."
                     : "Your 3D scan and listing are being built there.")
                    .font(.system(.body, design: .rounded))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color.brandInk.opacity(0.7))
                    .padding(.top, 12)
                Spacer()
                Button(action: session.backToWaiting) {
                    Text("Next product").fontWeight(.bold).frame(maxWidth: .infinity, minHeight: 52)
                }
                .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
                Text("Or point this phone at the next QR code.")
                    .font(.footnote).foregroundStyle(Color.brandInk.opacity(0.5))
                    .padding(.top, 8)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .foregroundStyle(Color.brandInk)
        .onAppear { withAnimation(.spring(response: 0.5, dampingFraction: 0.6).delay(0.1)) { appeared = true } }
    }
}

// MARK: - Couldn't send (or couldn't record)

struct FailedScreen: View {
    let message: String
    @ObservedObject var session: CaptureSession
    @State private var zipURL: URL?

    var body: some View {
        ZStack {
            Backdrop()
            VStack(spacing: 16) {
                Spacer()
                Image(systemName: "exclamationmark.icloud.fill")
                    .font(.system(size: 54)).foregroundStyle(Color.brandAmber)
                Text(session.passes.isEmpty ? "Something went wrong" : "Couldn't send it")
                    .font(.system(.title, design: .rounded).weight(.heavy))
                Text(message)
                    .font(.system(.footnote, design: .rounded))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color.brandInk.opacity(0.65))
                    .lineLimit(4)
                if !session.passes.isEmpty {
                    Text("Your \(session.passes.count == 1 ? "scan is" : "\(session.passes.count) passes are") saved on this phone.")
                        .font(.system(.subheadline, design: .rounded)).foregroundStyle(Color.brandInk.opacity(0.8))
                }
                Spacer()
                if !session.passes.isEmpty {
                    Button(action: session.retrySend) {
                        Label("Try again", systemImage: "arrow.clockwise").fontWeight(.bold).frame(maxWidth: .infinity, minHeight: 52)
                    }
                    .buttonStyle(.borderedProminent).tint(.brandMint).foregroundStyle(Color.brandStageBg)
                    if let zipURL {
                        ShareLink(item: zipURL) {
                            Label("Share the files", systemImage: "square.and.arrow.up").frame(maxWidth: .infinity, minHeight: 48)
                        }
                        .buttonStyle(.bordered).tint(Color.brandInk)
                    }
                }
                Button("Back to start", action: session.backToWaiting)
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Color.brandInk.opacity(0.7))
                    .padding(.top, 4)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .foregroundStyle(Color.brandInk)
        .task {
            guard let id = session.job?.scanID, !session.passes.isEmpty else { return }
            let dir = VideoRecorder.folder(scanID: id)
            zipURL = await Task.detached { try? ScanExport.zip(directory: dir, scanID: id) }.value
        }
    }
}

enum ScanExport {
    /// Zips a scan folder, every pass (NSFileCoordinator's built-in zipping), into Documents/exports/mint-{id}.zip.
    static func zip(directory: URL, scanID: String) throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let exports = docs.appendingPathComponent("exports", isDirectory: true)
        try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        let dest = exports.appendingPathComponent("mint-\(scanID.prefix(8)).zip")
        try? FileManager.default.removeItem(at: dest)
        var coordError: NSError?
        var copyError: Error?
        NSFileCoordinator().coordinate(readingItemAt: directory, options: .forUploading, error: &coordError) { tmp in
            do { try FileManager.default.copyItem(at: tmp, to: dest) } catch { copyError = error }
        }
        if let e = coordError ?? copyError { throw e }
        return dest
    }
}
