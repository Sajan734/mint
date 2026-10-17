import Foundation

/// A small image as brightness + colour strength per pixel (row-major).
public struct ImageGrid: Sendable {
    public let width: Int
    public let height: Int
    public var luma: [UInt8]
    public var chroma: [UInt8]   // max(R,G,B) − min(R,G,B): ~0 for white/grey paper

    public init(width: Int, height: Int, luma: [UInt8], chroma: [UInt8]) {
        precondition(luma.count == width * height && chroma.count == width * height)
        self.width = width
        self.height = height
        self.luma = luma
        self.chroma = chroma
    }
}

/// Finds the item sitting on a sheet of paper: the sheet is the big bright colourless region, and
/// the item is what the sheet *encloses*. On the turntable recording Vision's subject segmentation
/// merged the mouse into the paper (or missed it) and picked hands and knees instead; this doesn't:
/// a hand reaches in from the sheet's edge and ruled lines run off it, so neither is enclosed.
public enum ItemOnPaper {
    public struct Result: Sendable {
        public let item: [UInt8]    // 1 = item pixel
        public let sheet: [UInt8]   // 1 = sheet pixel
        public let itemArea: Int
    }

    public static func segment(_ g: ImageGrid, chromaMax: UInt8 = 16) -> Result? {
        let w = g.width, h = g.height, n = w * h

        // Paper: colourless and bright relative to the paper itself (shadows are darker).
        var lumas: [UInt8] = []
        for i in 0..<n where g.chroma[i] <= chromaMax && g.luma[i] >= 100 { lumas.append(g.luma[i]) }
        guard lumas.count > n / 50 else { return nil }
        lumas.sort()
        let paperLuma = Float(lumas[lumas.count * 3 / 4])
        let minLuma = UInt8(max(80, min(255, paperLuma * 0.62)))
        var white = [UInt8](repeating: 0, count: n)
        for i in 0..<n where g.chroma[i] <= chromaMax && g.luma[i] >= minLuma { white[i] = 1 }
        // Bridge thin features: ruled lines run edge to edge and would cut the sheet into strips.
        for _ in 0..<2 { white = dilate(white, w, h) }
        for _ in 0..<2 { white = erode(white, w, h) }

        // The sheet: the biggest white region.
        let (labels, sizes) = label(white, w, h, where: 1)
        guard let (sheetLabel, sheetArea) = sizes.enumerated().dropFirst().max(by: { $0.element < $1.element }).map({ ($0.offset, $0.element) }),
              sheetArea >= n / 50 else { return nil }
        var sheet = [UInt8](repeating: 0, count: n)
        for i in 0..<n where labels[i] == Int32(sheetLabel) { sheet[i] = 1 }

        // Everything not sheet that can reach the image border is outside; the rest is enclosed.
        var outside = [UInt8](repeating: 0, count: n)
        var stack: [Int] = []
        func seed(_ i: Int) { if sheet[i] == 0 && outside[i] == 0 { outside[i] = 1; stack.append(i) } }
        for x in 0..<w { seed(x); seed((h - 1) * w + x) }
        for y in 0..<h { seed(y * w); seed(y * w + w - 1) }
        while let i = stack.popLast() {
            let x = i % w, y = i / w
            if x > 0 { seed(i - 1) }
            if x < w - 1 { seed(i + 1) }
            if y > 0 { seed(i - w) }
            if y < h - 1 { seed(i + w) }
        }
        var enclosed = [UInt8](repeating: 0, count: n)
        for i in 0..<n where sheet[i] == 0 && outside[i] == 0 { enclosed[i] = 1 }

        // The item: the biggest enclosed region (punched holes and specks are tiny).
        let (hl, hs) = label(enclosed, w, h, where: 1)
        guard let (itemLabel, itemArea) = hs.enumerated().dropFirst().max(by: { $0.element < $1.element }).map({ ($0.offset, $0.element) }),
              itemArea >= max(12, n / 2000), itemArea <= sheetArea else { return nil }
        var item = [UInt8](repeating: 0, count: n)
        for i in 0..<n where hl[i] == Int32(itemLabel) { item[i] = 1 }
        return Result(item: item, sheet: sheet, itemArea: itemArea)
    }

    static func dilate(_ m: [UInt8], _ w: Int, _ h: Int) -> [UInt8] {
        var out = m
        for y in 0..<h {
            for x in 0..<w where m[y * w + x] == 0 {
                let i = y * w + x
                if (x > 0 && m[i - 1] != 0) || (x < w - 1 && m[i + 1] != 0) || (y > 0 && m[i - w] != 0) || (y < h - 1 && m[i + w] != 0) { out[i] = 1 }
            }
        }
        return out
    }

    static func erode(_ m: [UInt8], _ w: Int, _ h: Int) -> [UInt8] {
        var out = m
        for y in 0..<h {
            for x in 0..<w where m[y * w + x] != 0 {
                let i = y * w + x
                if x == 0 || y == 0 || x == w - 1 || y == h - 1 || m[i - 1] == 0 || m[i + 1] == 0 || m[i - w] == 0 || m[i + w] == 0 { out[i] = 0 }
            }
        }
        return out
    }

    /// 4-connected labels of pixels equal to `value` (0 = not that value); sizes[label] = pixel count.
    static func label(_ m: [UInt8], _ w: Int, _ h: Int, where value: UInt8) -> ([Int32], [Int]) {
        var labels = [Int32](repeating: 0, count: w * h)
        var sizes = [0]
        var stack: [Int] = []
        for s in 0..<(w * h) where m[s] == value && labels[s] == 0 {
            let l = Int32(sizes.count)
            sizes.append(0)
            labels[s] = l
            stack.append(s)
            while let i = stack.popLast() {
                sizes[Int(l)] += 1
                let x = i % w, y = i / w
                for j in [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]
                where j >= 0 && m[j] == value && labels[j] == 0 {
                    labels[j] = l
                    stack.append(j)
                }
            }
        }
        return (labels, sizes)
    }
}
