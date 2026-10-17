import SwiftUI
import UIKit

/// Brand tokens: docs/design/DESIGN.md, shared with the website (buyer/ and seller/ globals.css).
/// The app lives over the camera, so it uses the dark side of the system: pine fields, oat type, brand mint
/// ("spark") for progress and the done check. The old names stay as aliases.
enum Brand {
    static let spark = UIColor(hex: 0x3DDC97)   // brand mint: ring, check, logo dot
    static let pine = UIColor(hex: 0x163A30)    // deep field: full-screen moments, cards
    static let pineDeep = UIColor(hex: 0x0F201B) // backdrop over the camera
    static let oat = UIColor(hex: 0xF1EFE9)     // type on pine
    static let oatSoft = UIColor(hex: 0xB9C2BC) // secondary type on pine
    static let leaf = UIColor(hex: 0x0B6B4C)    // the action colour on light surfaces
    static let amber = UIColor(hex: 0xF5C66A)   // warnings on dark
    static let coral = UIColor(hex: 0xFF9A84)   // errors on dark
    static let slate = UIColor(hex: 0x8FA09A)

    // Aliases (pre-DESIGN.md names).
    static let mint = spark
    static let stageBg = pineDeep
    static let paper = oat
    static let red = coral
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
    static let brandSpark = Color(Brand.spark)
    static let brandPine = Color(Brand.pine)
    static let brandOat = Color(Brand.oat)
    static let brandOatSoft = Color(Brand.oatSoft)
    static let brandLeaf = Color(Brand.leaf)
    static let brandMint = Color(Brand.mint)
    static let brandStageBg = Color(Brand.stageBg)
    static let brandAmber = Color(Brand.amber)
    static let brandSlate = Color(Brand.slate)
    static let brandRed = Color(Brand.red)
    static let brandPaper = Color(Brand.paper)
}

/// Type (DESIGN.md §3). The website sets signs in Fraunces and everything else in Figtree; the app uses Apple's
/// equivalents: New York (`.serif`) for the big lines, SF Pro for what you read or press. SF Pro Rounded is kept
/// only for the big percentages, where its numbers read best at a glance.
extension Font {
    /// A big line: "Ready when you are", "Look back at your computer".
    static func mintSign(size: CGFloat) -> Font { .system(size: size, weight: .semibold, design: .serif) }
    /// A titled moment in a text style, so it follows Dynamic Type.
    static func mintSign(_ style: Font.TextStyle) -> Font { .system(style, design: .serif).weight(.semibold) }
    /// Big percentages on the lap and sending rings.
    static func mintNumber(size: CGFloat) -> Font { .system(size: size, weight: .bold, design: .rounded) }
}
