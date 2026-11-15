# Manual walkthrough of each v0.1 source change

This guide explains the code produced by `apply_stream_controls.py`. You can type the changes directly in Android Studio instead of running the patch script. They target the Meta CameraAccess sample already in `samples/CameraAccess`.

## A. `camera/CameraUiState.kt` — state is the UI's source of truth

Add the import alongside `StreamState`:

```kotlin
import com.meta.wearable.dat.camera.types.VideoQuality
```

Add fields inside the `CameraUiState` constructor, immediately after `isStartingStream`:

```kotlin
val requestedVideoQuality: VideoQuality = VideoQuality.HIGH,
val requestedFrameRate: Int = 30,
val actualWidth: Int = 0,
val actualHeight: Int = 0,
val observedFrameRate: Float = 0f,
```

`requested...` is what the user chose; `actual...` is what the glasses delivered. The SDK is allowed to downgrade quality.

## B. `camera/CameraViewModel.kt` — apply settings to the SDK

Add the `Context` and `SystemClock` imports:

```kotlin
import android.content.Context
import android.os.SystemClock
```

Remove `private const val FRAME_RATE = 24` (or `30` if you already edited it). Before `_uiState`, create device-local settings:

```kotlin
private val streamPreferences = application.getSharedPreferences(
    "kilo_glasses_stream_settings", Context.MODE_PRIVATE)
private val _uiState = MutableStateFlow(
    CameraUiState(
        requestedVideoQuality = when (streamPreferences.getString("quality", "HIGH")) {
          "LOW" -> VideoQuality.LOW
          "MEDIUM" -> VideoQuality.MEDIUM
          else -> VideoQuality.HIGH
        },
        requestedFrameRate = streamPreferences.getInt("fps", 30).let {
          if (it in listOf(15, 24, 30)) it else 30
        },
    ),
)
```

This replaces the original `_uiState = MutableStateFlow(CameraUiState())` declaration. The preferences are different on each device.

Near the `Job` fields, add:

```kotlin
private var restartPreviewAfterSettings = false
private var frameWindowStartedAtMs = 0L
private var frameCountInWindow = 0
```

In `beginStream()`, replace its static camera configuration with:

```kotlin
StreamConfiguration(
    videoQuality = _uiState.value.requestedVideoQuality,
    frameRate = _uiState.value.requestedFrameRate,
    compressVideo = true,
)
```

Just before `fun stopStreaming()` add the following function. It refuses to reconfigure during a recording and queues a controlled preview restart:

```kotlin
fun applyStreamSettings(quality: VideoQuality, frameRate: Int) {
  val state = _uiState.value
  if (frameRate !in listOf(15, 24, 30) || state.isBusy || state.isRecording ||
      state.isCapturingPhoto || state.isPaused) return
  if (state.requestedVideoQuality == quality && state.requestedFrameRate == frameRate) return
  val qualityValue = when (quality) {
    VideoQuality.LOW -> "LOW"
    VideoQuality.MEDIUM -> "MEDIUM"
    else -> "HIGH"
  }
  streamPreferences.edit().putString("quality", qualityValue).putInt("fps", frameRate).apply()
  _uiState.update { it.copy(requestedVideoQuality = quality, requestedFrameRate = frameRate) }
  if (state.hasStream && state.isStreaming) {
    restartPreviewAfterSettings = true
    stopStreaming()
  }
}
```

In `onStreamTerminated()`, immediately **after** `clearStreamResources()`, add:

```kotlin
val shouldRestart = restartPreviewAfterSettings
restartPreviewAfterSettings = false
if (shouldRestart && _uiState.value.isSessionActive) startStreaming()
```

That is the important lifecycle detail: restart only **after** the existing SDK camera capability is closed. It uses the original `startStreaming()` permission gate. In `endSession()`, `cleanupSession()`, and `handleUnregistered()`, set `restartPreviewAfterSettings = false` to prevent a pending restart after leaving the session.

To measure real received video, replace the first-frame block at the end of `handleVideoFrame()` with:

```kotlin
if (!videoFrame.isCodecConfig) {
  val now = SystemClock.elapsedRealtime()
  if (frameWindowStartedAtMs == 0L) frameWindowStartedAtMs = now
  frameCountInWindow++
  val elapsedMs = now - frameWindowStartedAtMs
  val reportFps = elapsedMs >= 1_000L
  val fps = if (reportFps) frameCountInWindow * 1000f / elapsedMs else 0f
  val previous = _uiState.value
  if (!previous.hasReceivedFirstFrame || previous.actualWidth != width ||
      previous.actualHeight != height || reportFps) {
    _uiState.update {
      it.copy(
          hasReceivedFirstFrame = true,
          actualWidth = width,
          actualHeight = height,
          observedFrameRate = if (reportFps) fps else it.observedFrameRate,
      )
    }
  }
  if (reportFps) {
    frameCountInWindow = 0
    frameWindowStartedAtMs = now
  }
}
```

In `clearStreamResources()` reset `frameWindowStartedAtMs = 0L` and `frameCountInWindow = 0` after `csdCollector.reset()`, and reset `actualWidth`, `actualHeight`, `observedFrameRate` to zero when resetting `streamState` to STOPPED.

## C. `ui/CameraScreen.kt` — connect the button and dialog

Add:

```kotlin
import androidx.compose.material.icons.filled.Tune
```

Inside `CameraScreen`, near `showSettingsMenu`, add:

```kotlin
var showStreamSettings by remember { mutableStateOf(false) }
```

Add this argument to the existing `TopBar(...)` call:

```kotlin
onOpenStreamSettings = { showStreamSettings = true },
```

Add to `TopBar` function arguments:

```kotlin
onOpenStreamSettings: () -> Unit,
```

Inside `TopBar`, just after its weighted `Spacer` and **before** the existing disconnect icon `Box`, insert:

```kotlin
Icon(
    imageVector = Icons.Filled.Tune,
    contentDescription = "Video settings",
    tint = Color.White,
    modifier = Modifier.size(28.dp).clickable(onClick = onOpenStreamSettings)
        .testTag("stream_settings_button"),
)
Spacer(modifier = Modifier.width(18.dp))
```

Inside the `CameraScreen` composable (still inside its outer `Box`), before the camera permission dialog, add:

```kotlin
if (showStreamSettings) {
  StreamSettingsDialog(
      ui = ui,
      onDismiss = { showStreamSettings = false },
      onApply = { quality, fps ->
        cameraViewModel.applyStreamSettings(quality, fps)
        showStreamSettings = false
      },
  )
}
```

## D. Add new `ui/StreamSettingsDialog.kt`

Copy the complete sibling file `StreamSettingsDialog.kt` from this kit into:

```
samples/CameraAccess/app/src/main/java/com/meta/wearable/dat/externalsampleapps/cameraaccess/ui/StreamSettingsDialog.kt
```

This contains two Compose `DropdownMenu`s and an `AlertDialog` with Apply and Cancel.

## E. Version / identity

You may optionally change `app_name` in `res/values/strings.xml` to `Glasses Bridge Test`, and change `versionCode` to 2 and `versionName` to `0.1.0-kilo` in `app/build.gradle.kts`. The script does so for you.

## F. Build and verify

Before building, run `git diff` or use Android Studio's Git comparison. You should see modifications in four source files (including the new dialog), plus the optional docs, version and CI workflow.

Then run the sample on the Tab S9 and compare: requested vs received resolution, FPS, restarts, recording safety. Repeat sequentially on Z Fold 3. If compilation fails, send the **first** Kotlin/Gradle error, not the final `BUILD FAILED` line.
