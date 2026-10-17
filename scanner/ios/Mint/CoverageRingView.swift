import CoverageKit
import SwiftUI

/// Top-down map of the dome. Outer ring = low band, inner ring = high band.
/// It rotates so the user is always at the bottom looking up at the item in the centre,
/// which makes "walk right" mean screen-right.
struct CoverageRingView: View {
    let filled: Set<SegmentID>
    let cameraAzimuthDeg: Float?
    let pct: Int

    var body: some View {
        ZStack {
            Canvas { ctx, size in
                let centre = CGPoint(x: size.width / 2, y: size.height / 2)
                let outer = min(size.width, size.height) / 2 - 8
                let ringWidth: CGFloat = 14
                let me = Double(cameraAzimuthDeg ?? 0)

                for seg in Dome.allSegments {
                    // Band 0 (low) outside, band 1 (high) inside.
                    let r = outer - CGFloat(seg.el) * (ringWidth + 6) - ringWidth / 2
                    let start = Double(seg.az * Dome.azimuthStepDeg) + 2
                    let end = Double((seg.az + 1) * Dome.azimuthStepDeg) - 2
                    // Screen angle (y down, 90° = bottom): the user sits at the bottom, and azimuth to the
                    // user's right lands screen-right. Drawn as points to avoid arc-direction ambiguity.
                    var path = Path()
                    let steps = 8
                    for i in 0...steps {
                        let az = start + (end - start) * Double(i) / Double(steps)
                        let a = (90 - (az - me)) * .pi / 180
                        let p = CGPoint(x: centre.x + r * cos(a), y: centre.y + r * sin(a))
                        if i == 0 { path.move(to: p) } else { path.addLine(to: p) }
                    }
                    let color: Color = filled.contains(seg) ? .brandMint : .white.opacity(0.18)
                    ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: ringWidth, lineCap: .butt))
                }

                // "You are here."
                let dot = CGRect(x: centre.x - 6, y: centre.y + outer + 2 - 6, width: 12, height: 12)
                ctx.fill(Path(ellipseIn: dot), with: .color(.white))
            }
            VStack(spacing: 0) {
                Text("\(pct)%").font(.system(size: 30, weight: .bold, design: .rounded)).monospacedDigit()
                Text("coverage").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(6)
        .background(.ultraThinMaterial, in: Circle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Coverage \(pct) percent")
    }
}
