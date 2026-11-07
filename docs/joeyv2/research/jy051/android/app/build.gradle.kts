plugins {
    id("com.android.application")
}

// JY-051 "Joey Study": T1 (the study page in a WebView), T2 (Media3 ExoPlayer on Jellyfin's direct stream),
// T2F (T2 + the FFmpeg audio decoder extension), T2H (ExoPlayer on Jellyfin HLS, only for rows T2/T2F could not play).
// Debug build only, signed with the runner's throwaway debug key; installed and removed by scripts/jy051_sitting.py.
android {
    namespace = "net.joeyhome.study"
    compileSdk = 37

    defaultConfig {
        applicationId = "net.joeyhome.study"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

val media3 = "1.9.0"

dependencies {
    implementation("androidx.media3:media3-exoplayer:$media3")
    implementation("androidx.media3:media3-exoplayer-hls:$media3")
    implementation("androidx.media3:media3-ui:$media3")
    // Prebuilt FFmpeg audio decoders for Media3 from the Jellyfin project (Maven Central; POM licence GPL-3.0),
    // built against Media3 1.9.0. The same artefact Jellyfin's Android TV app ships.
    implementation("org.jellyfin.media3:media3-ffmpeg-decoder:1.9.0+1")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    testImplementation("junit:junit:4.13.2")
}
