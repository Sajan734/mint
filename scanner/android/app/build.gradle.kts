plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "ca.htv11.mint.scanner"
    compileSdk = 37

    defaultConfig {
        applicationId = "ca.htv11.mint.scanner"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        // Supabase Edge Function that hands out signed upload URLs (scanner/supabase/README.md). Empty = save + share only.
        buildConfigField("String", "MINT_UPLOAD_URL", "\"https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-upload\"")
        // The dashboard hand-off (scanner/supabase/functions/scan-session, see scanner/DASHBOARD.md).
        buildConfigField("String", "MINT_SESSION_URL", "\"https://jpanyhsifoxxiizkgjno.supabase.co/functions/v1/scan-session\"")
    }

    buildTypes {
        // Debug runs optimised enough for the 30 fps capture loop; Release is minified.
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(project(":coveragekit"))

    implementation(platform("androidx.compose:compose-bom:2026.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended:1.7.8")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")

    // ARCore: world tracking + camera poses (the ARKit of this app); shared camera for focus/exposure/white balance locks.
    implementation("com.google.ar:core:1.57.0")
    // The website's QR codes (bundled model: works offline).
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
}
