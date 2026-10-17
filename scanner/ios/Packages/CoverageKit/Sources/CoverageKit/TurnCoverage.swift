import Foundation

/// How much of the item has been seen, on the turntable: which sides have faced the camera, from
/// which height, and for how long. Driven only by measurements: the paper's turn (`PaperTurn`)
/// and the camera's elevation above the item.
///
/// The item's sides are 36 slices of 10° (item frame, 0 = the side facing the camera at the start).
/// One band (the default, what the app shows): one lap at any height. Two bands: band 0 = the height
/// of the first lap, band 1 = a clearly different height (≥ `bandGap` above or below). Each reading,
/// every slice within 25° of facing the camera (looked at nearly head-on) gains
/// cos(angle off the camera) × seconds / `secondsToFill`, so a slice fills as it turns past the
/// front, and 100% means the paper really went (nearly) all the way round: sides only glimpsed at a
/// steep angle don't count. On mint-33218a6e with a 70° reach, 100% came at 255° of turn.
public struct TurnCoverage: Sendable {
    public static let slices = 36
    public static let reach: Float = 25 * .pi / 180

    public let bands: Int
    public let secondsToFill: Float
    public let bandGap: Float
    /// fill[band][slice], 0…1.
    public private(set) var fill: [[Float]]
    /// The side currently facing the camera (item frame, radians, clockwise from above).
    public private(set) var facing: Float = 0
    public private(set) var band = 0
    public private(set) var firstElevation: Float?

    public init(bands: Int = 1, secondsToFill: Float = 0.5, bandGap: Float = 10 * .pi / 180) {
        precondition(bands == 1 || bands == 2)
        self.bands = bands
        self.secondsToFill = secondsToFill
        self.bandGap = bandGap
        fill = Array(repeating: Array(repeating: 0, count: Self.slices), count: bands)
    }

    /// One measurement. `turned`: the paper's turn since the start (`PaperTurn.turned`, clockwise
    /// from above); `elevation`: the camera above the item (radians); `dt`: seconds since the last one.
    public mutating func observe(turned: Float, elevation: Float, dt: Double) {
        // The item turned clockwise by `turned`, so the side facing the camera is the one that
        // started `turned` anticlockwise of it.
        facing = -turned
        if firstElevation == nil { firstElevation = elevation }
        band = bands == 2 && abs(elevation - firstElevation!) >= bandGap ? 1 : 0
        let gain = Float(min(dt, 0.25)) / secondsToFill
        guard gain > 0 else { return }
        for s in 0..<Self.slices {
            let d = Self.wrapPi(Self.centre(s) - facing)
            guard abs(d) < Self.reach else { continue }
            fill[band][s] = min(1, fill[band][s] + gain * cos(d))
        }
    }

    /// 0…100, the share of all slices (at every height) that have been seen. 100 only when every one is full.
    public var percent: Int {
        let all = fill.joined()
        if all.allSatisfy({ $0 >= 0.999 }) { return 100 }
        return min(99, Int(all.reduce(0, +) / Float(all.count) * 100))
    }

    /// How well a side has been seen (heights averaged), 0…1, interpolated between slices.
    public func level(side: Float) -> Float {
        let x = Self.wrap2Pi(side) / (2 * .pi) * Float(Self.slices) - 0.5
        let i0 = Int(floor(x)), f = x - floor(x)
        let a = (i0 % Self.slices + Self.slices) % Self.slices, b = (a + 1) % Self.slices
        func both(_ s: Int) -> Float { fill.reduce(0) { $0 + $1[s] } / Float(bands) }
        return both(a) * (1 - f) + both(b) * f
    }

    /// The side seen at horizontal offset `s` across the item's silhouette (−1 = its left edge on
    /// screen, +1 = its right edge, as seen from the camera), modelling the item as an upright cylinder.
    public func side(atOffset s: Float) -> Float {
        // Clockwise from above, a surface facing the camera's right is a quarter turn anticlockwise.
        facing - asin(max(-1, min(1, s)))
    }

    /// Mean fill of `count` equal arcs of one height's ring (arc 0 starts at the side that faced the camera first).
    public func arcs(band: Int, count: Int) -> [Float] {
        let per = Self.slices / count
        return (0..<count).map { k in fill[band][(k * per)..<((k + 1) * per)].reduce(0, +) / Float(per) }
    }

    static func centre(_ s: Int) -> Float { (Float(s) + 0.5) / Float(slices) * 2 * .pi }

    static func wrapPi(_ a: Float) -> Float {
        var x = a.truncatingRemainder(dividingBy: 2 * .pi)
        if x > .pi { x -= 2 * .pi }
        if x <= -.pi { x += 2 * .pi }
        return x
    }

    static func wrap2Pi(_ a: Float) -> Float {
        var x = a.truncatingRemainder(dividingBy: 2 * .pi)
        if x < 0 { x += 2 * .pi }
        return x
    }
}
