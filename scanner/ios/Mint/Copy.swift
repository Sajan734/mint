import CoverageKit

/// User-facing words. Calm, short, plain language (CLAUDE.md §14.4, §15).
enum Copy {
    static let aim = "Point at the item."
    static let finding = "Move the phone slowly so it can see the table."
    static let findingTable = "Found it. Finding the table under it…"
    static let saving = "Saving…"
    static let complete = "Coverage verified. Nothing hidden."

    /// "Found it · 18 × 24 cm" (width × height).
    static func found(_ e: ObjectEstimate) -> String {
        String(format: "Found it · %.0f × %.0f cm", e.width * 100, e.height * 100)
    }

    static func issue(_ issue: CaptureIssue) -> String {
        switch issue {
        case .trackingLimited: return "Lost track for a moment. Point at the item."
        case .tooClose: return "A little too close. Step back."
        case .tooFar: return "Get a bit closer."
        case .tooLow: return "Raise the phone a little."
        case .tooHigh: return "Lower the phone a little."
        case .tooFast: return "Too fast. Slow down a little."
        case .tooDark: return "Too dark. Find more light."
        case .blurry: return "Hold steady for a sharp shot."
        }
    }

    static func hint(_ hint: Hint) -> (text: String, symbol: String) {
        switch hint {
        case .done: return (complete, "checkmark.seal.fill")
        case .holdHere: return ("Hold here a moment.", "hand.raised.fill")
        case .walkRight: return ("Keep walking right.", "arrow.right")
        case .walkLeft: return ("Walk back to the left.", "arrow.left")
        case .raise: return ("Now raise the phone and look down at it.", "arrow.up")
        case .lower: return ("Now lower the phone to the item's level.", "arrow.down")
        }
    }
}
