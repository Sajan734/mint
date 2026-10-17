// swift-tools-version:5.9
import PackageDescription

// Pure capture logic (no ARKit, no UIKit) so it unit-tests on any Mac.
let package = Package(
    name: "CoverageKit",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "CoverageKit", targets: ["CoverageKit"])],
    targets: [
        .target(name: "CoverageKit"),
        .testTarget(name: "CoverageKitTests", dependencies: ["CoverageKit"]),
    ]
)
