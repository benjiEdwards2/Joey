plugins {
    alias(libs.plugins.android.application)
}

// tv/VERSION is the single source of the app version (D-P9, WP-B8 format): three key=value lines.
val tvVersion: Map<String, String> = rootProject.file("VERSION").readLines()
    .map { it.trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
    .associate { it.substringBefore("=").trim() to it.substringAfter("=").trim() }

android {
    namespace = "net.joeyhome.media"
    compileSdk = 37

    defaultConfig {
        applicationId = "net.joeyhome.media" // Q35: permanent; never change after the first friend install
        minSdk = 28 // Q42
        targetSdk = 37
        versionCode = tvVersion.getValue("versionCode").toInt()
        versionName = tvVersion.getValue("versionName")
        buildConfigField("int", "MIN_VERSION_CODE", tvVersion.getValue("minVersionCode"))
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        // The committed, clearly labelled DEBUG key (tv/app/debug-signing/README.md): every CI debug build has the
        // same signature, so `adb install -r` keeps the TV's cookies. The release key is never in git (WP-B8/B9).
        getByName("debug") {
            storeFile = file("debug-signing/joeytv-debug.p12")
            storePassword = "android"
            keyAlias = "joeytv-debug"
            keyPassword = "android"
            storeType = "pkcs12"
        }
    }

    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".debug"
            signingConfig = signingConfigs.getByName("debug")
        }
        getByName("release") {
            isMinifyEnabled = false
            // signingConfigs.release (env TV_KEYSTORE_PATH / TV_KEYSTORE_PASSWORD, alias joeytv) arrives in WP-B8 step 2.
        }
    }

    flavorDimensions += "channel"
    productFlavors {
        create("sideload") {
            dimension = "channel"
            buildConfigField("boolean", "UPDATER", "true") // v1: self-update from <ui>/app/version.json (WP-B8)
        }
        create("store") {
            dimension = "channel"
            buildConfigField("boolean", "UPDATER", "false") // declared, empty: no updater, no REQUEST_INSTALL_PACKAGES
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = false // XML + HTML reports are always written (tv-reports artifact)
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    testImplementation(libs.junit)
}
