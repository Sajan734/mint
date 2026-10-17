import SwiftUI
import UIKit

/// Brand tokens (CLAUDE.md §15). Drafts until C finalises the palette.
enum Brand {
    static let mint = UIColor(hex: 0x3DDC97)
    static let stageBg = UIColor(hex: 0x0B0F0E)
    static let paper = UIColor(hex: 0xFAF7F2)
    static let amber = UIColor(hex: 0xF5B53F)
    static let red = UIColor(hex: 0xFF4D4D)
    static let slate = UIColor(hex: 0x8A9499)
}

extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: alpha
        )
    }
}

extension Color {
    static let brandMint = Color(Brand.mint)
    static let brandStageBg = Color(Brand.stageBg)
    static let brandAmber = Color(Brand.amber)
    static let brandSlate = Color(Brand.slate)
}
