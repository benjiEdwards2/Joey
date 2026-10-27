plugins {
    alias(libs.plugins.android.application)
}

// tv/VERSION is the single source of the app version (D-P9, WP-B8 format): three key=value lines.
val tvVersion: Map<String, String> = rootProject.file("VERSION").readLines()
    .map { it.trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
    .associate { it.substringBefore("=").trim() to it.substringAfter("=").trim() }

// The same rules as tests/tv/test_version_file.py (the deploy gate) and VersionFileTest: a bad file stops every build.
run {
    val code = Regex("^20\\d{6}(0[1-9]|[1-9]\\d)$")
    require(tvVersion.keys == setOf("versionName", "versionCode", "minVersionCode")) {
        "tv/VERSION must hold exactly versionName, versionCode, minVersionCode"
    }
    require(Regex("^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$").matches(tvVersion.getValue("versionName"))) {
        "tv/VERSION versionName must be semver"
    }
    for (key in listOf("versionCode", "minVersionCode")) {
        val value = tvVersion.getValue(key)
        require(code.matches(value) && value.toLong() <= 2_100_000_000L) { "tv/VERSION $key must be YYYYMMDDnn" }
    }
    require(tvVersion.getValue("minVersionCode").toLong() <= tvVersion.getValue("versionCode").toLong()) {
        "tv/VERSION minVersionCode must not exceed versionCode"
    }
}

// Release signing (WP-B8 step 2, D-P10): PKCS12, alias joeytv, from the environment only (CI decodes the
// TV_KEYSTORE_B64 secret to a temp file). Without both variables a release build FAILS - never an unsigned APK.
val releaseKeystorePath: Provider<String> = providers.environmentVariable("TV_KEYSTORE_PATH")
val releaseKeystorePassword: Provider<String> = providers.environmentVariable("TV_KEYSTORE_PASSWORD")

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
        create("release") {
            releaseKeystorePath.orNull?.takeIf { it.isNotBlank() }?.let { storeFile = file(it) }
            storePassword = releaseKeystorePassword.orNull
            keyAlias = "joeytv"
            keyPassword = releaseKeystorePassword.orNull
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
            signingConfig = signingConfigs.getByName("release") // env only; requireReleaseKeystore guards it
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
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.exoplayer.hls)
    implementation(libs.media3.ui) // PlayerView (surface + subtitles) only; the controls are the shell's own (look A)
    implementation(libs.androidx.annotation) // @OptIn(UnstableApi::class) for Media3's data-source and factory APIs
    testImplementation(libs.junit)
    testImplementation(libs.json)
}

// Fail closed, early and with a clear message: every release variant's pre-build needs the keystore env.
val requireReleaseKeystore by tasks.registering {
    val path = releaseKeystorePath
    val password = releaseKeystorePassword
    doLast {
        val file = path.orNull?.takeIf { it.isNotBlank() }?.let { File(it) }
        if (file == null || !file.isFile || password.orNull.isNullOrEmpty()) {
            throw GradleException(
                "Release signing needs TV_KEYSTORE_PATH (an existing PKCS12 file) and TV_KEYSTORE_PASSWORD " +
                    "(alias joeytv). Refusing to build an unsigned release APK.",
            )
        }
    }
}
tasks.configureEach {
    if (Regex("^pre\\w+ReleaseBuild$").matches(name)) dependsOn(requireReleaseKeystore)
}
