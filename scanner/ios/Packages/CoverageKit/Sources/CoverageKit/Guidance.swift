import Foundation

/// The single most useful instruction for the user right now.
public enum Hint: Equatable, Sendable {
    case done
    case holdHere                     // standing in an empty segment: keep steady for a sharp frame
    case walkRight(segments: Int)     // nearest empty segment in this ring is to the user's right
    case walkLeft(segments: Int)
    case raise                        // this ring is full (or too low): go up to the next ring
    case lower
}

public enum Guidance {
    public static func hint(position p: DomePosition, filled: Set<SegmentID>) -> Hint {
        if filled.count >= Dome.segmentsToComplete { return .done }

        let bands = Dome.bands
        if p.elevationDeg < bands[0].minDeg { return .raise }
        if p.elevationDeg >= bands[bands.count - 1].maxDeg { return .lower }
        let band = bands.firstIndex { p.elevationDeg >= $0.minDeg && p.elevationDeg < $0.maxDeg } ?? 0

        let emptyHere = (0..<Dome.azimuthCount).filter { !filled.contains(SegmentID(az: $0, el: band)) }
        if emptyHere.isEmpty {
            // Ring done: send them to the nearest ring that still has gaps.
            let other = bands.indices
                .filter { b in b != band && (0..<Dome.azimuthCount).contains { !filled.contains(SegmentID(az: $0, el: b)) } }
                .min { abs($0 - band) < abs($1 - band) }
            guard let other else { return .done }
            return other > band ? .raise : .lower
        }

        let step = Float(Dome.azimuthStepDeg)
        let currentBin = min(Int(p.azimuthDeg / step), Dome.azimuthCount - 1)
        if emptyHere.contains(currentBin) { return .holdHere }

        // Signed circular distance in bins, positive = walk right (azimuth increases to the user's right).
        func delta(_ bin: Int) -> Int {
            var d = bin - currentBin
            if d > Dome.azimuthCount / 2 { d -= Dome.azimuthCount }
            if d < -Dome.azimuthCount / 2 { d += Dome.azimuthCount }
            return d
        }
        // Ties go right so the user keeps one walking direction.
        let best = emptyHere.map(delta).min { (abs($0), $0 < 0 ? 1 : 0) < (abs($1), $1 < 0 ? 1 : 0) }!
        return best > 0 ? .walkRight(segments: best) : .walkLeft(segments: -best)
    }
}
