import Foundation

/// A small 8-bit grayscale image (row-major, tightly packed).
public struct GrayImage: Sendable {
    public let width: Int
    public let height: Int
    public var pixels: [UInt8]

    public init(width: Int, height: Int, pixels: [UInt8]) {
        precondition(pixels.count == width * height)
        self.width = width
        self.height = height
        self.pixels = pixels
    }
}

public enum Sharpness {
    /// Box-downsample a luma plane by an integer factor (averages a 2×2 sample per block for speed).
    /// `base` points at the Y plane of an ARKit `capturedImage` (bytesPerRow may exceed width).
    public static func downsample(
        base: UnsafePointer<UInt8>, width: Int, height: Int, bytesPerRow: Int, factor: Int
    ) -> GrayImage {
        let w = width / factor, h = height / factor
        var out = [UInt8](repeating: 0, count: w * h)
        let half = max(factor / 2, 1)
        for y in 0..<h {
            let r0 = y * factor * bytesPerRow
            let r1 = min(y * factor + half, height - 1) * bytesPerRow
            for x in 0..<w {
                let c0 = x * factor, c1 = min(x * factor + half, width - 1)
                let s = Int(base[r0 + c0]) + Int(base[r0 + c1]) + Int(base[r1 + c0]) + Int(base[r1 + c1])
                out[y * w + x] = UInt8(s >> 2)
            }
        }
        return GrayImage(width: w, height: h, pixels: out)
    }

    /// Variance of the 4-neighbour Laplacian. Higher = sharper. Blur drives it towards 0.
    public static func laplacianVariance(_ img: GrayImage) -> Double {
        let w = img.width, h = img.height
        guard w >= 3, h >= 3 else { return 0 }
        var sum = 0.0, sumSq = 0.0
        img.pixels.withUnsafeBufferPointer { p in
            for y in 1..<(h - 1) {
                let row = y * w
                for x in 1..<(w - 1) {
                    let i = row + x
                    let lap = Int(p[i - w]) + Int(p[i + w]) + Int(p[i - 1]) + Int(p[i + 1]) - 4 * Int(p[i])
                    let v = Double(lap)
                    sum += v
                    sumSq += v * v
                }
            }
        }
        let n = Double((w - 2) * (h - 2))
        let mean = sum / n
        return sumSq / n - mean * mean
    }

    /// Mean luma 0–255, used for the "Too dark" warning.
    public static func meanLuma(_ img: GrayImage) -> Double {
        guard !img.pixels.isEmpty else { return 0 }
        return Double(img.pixels.reduce(0) { $0 + Int($1) }) / Double(img.pixels.count)
    }
}

/// Adaptive sharpness gate: a frame passes if it clears an absolute floor *and* is close to the
/// sharpest frames seen recently. Absolute Laplacian variance depends on the scene, so a purely
/// fixed threshold would be wrong on either plain or busy objects.
public struct SharpnessGate: Sendable {
    public var absoluteMin: Double
    public var relativeToRecent: Double
    public var window: Int
    private var recent: [Double] = []

    public init(absoluteMin: Double = 20, relativeToRecent: Double = 0.7, window: Int = 45) {
        self.absoluteMin = absoluteMin
        self.relativeToRecent = relativeToRecent
        self.window = window
    }

    /// Records the value and returns whether this frame is sharp enough to keep.
    public mutating func accept(_ value: Double) -> Bool {
        recent.append(value)
        if recent.count > window { recent.removeFirst(recent.count - window) }
        guard value >= absoluteMin else { return false }
        let sorted = recent.sorted()
        let p80 = sorted[min(sorted.count - 1, Int(Double(sorted.count) * 0.8))]
        return value >= relativeToRecent * p80
    }

    public mutating func reset() { recent.removeAll() }
}
