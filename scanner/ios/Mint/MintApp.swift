import SwiftUI

@main
struct MintApp: App {
    var body: some Scene {
        WindowGroup {
            ScanView()
                .preferredColorScheme(.dark)
                .statusBarHidden()
        }
    }
}
