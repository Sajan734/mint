import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// Pure Kotlin (no Android): the measured pieces of the scanner, unit-tested on the JVM.
// The Android port of scanner/ios/Packages/CoverageKit (the parts the app uses), plus link parsing and the upload plan.
plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
