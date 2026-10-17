import CoverageKit

/// User-facing words. Calm, short, plain language (CLAUDE.md §14.4, §15).
enum Copy {
    static let aim = "Point at the item."
    static let finding = "Move the phone slowly so it can see the table."
    static let findingTable = "Found it. Finding the table under it…"
    static let needMotion = "Found it. Move the phone a little to measure it."
    static let saving = "Saving…"
    static let complete = "Coverage verified. Nothing hidden."

    static let paperTip = "Tip: put it on a sheet of paper, then just turn the paper."
    static let paperLost = "Keep the whole sheet in view."

    /// No centimetres on screen: the capture doesn't need them, and a wrong number costs trust.
    static func found(locked: Bool, paper: Bool) -> String {
        guard locked else { return "Measuring… hold steady." }
        return paper ? "Locked on, paper found. Tap Start." : "Locked on. Tap Start."
    }

    /// Turntable: the phone stays still, the paper turns.
    static func turntableHint(_ hint: Hint) -> (text: String, symbol: String) {
        switch hint {
        case .done: return (complete, "checkmark.seal.fill")
        case .holdHere, .walkLeft, .walkRight: return ("Keep turning the paper.", "arrow.triangle.2.circlepath")
        case .raise: return ("Now raise the phone and turn it again.", "arrow.up")
        case .lower: return ("Lower the phone a little.", "arrow.down")
        }
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
        case .raise: return ("Raise the phone a little.", "arrow.up")
        case .lower: return ("Lower the phone a little.", "arrow.down")
        }
    }
}
