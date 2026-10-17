import SwiftUI

@main
struct MintApp: App {
    var body: some Scene {
        WindowGroup {
            CaptureView()
                .preferredColorScheme(.dark)
                .statusBarHidden()
        }
    }
}
