#!/usr/bin/env python3
"""Apply Kilo Glasses Bridge v0.1 modifications to the Meta CameraAccess sample.

Run from anywhere: python apply_stream_controls.py /path/to/meta-wearables-dat-android
Designed against deadman2496/glasses-bridge main as inspected 2026-11-08.
Checks all exact source anchors before writing any files; refuses if already patched.
"""
from pathlib import Path
import sys

PREFIX = Path('samples/CameraAccess')
SOURCES = PREFIX / 'app/src/main/java/com/meta/wearable/dat/externalsampleapps/cameraaccess'


def replace_once(s: str, old: str, new: str, name: str) -> str:
    # Some local working copies already changed the sample to HIGH/30 before v0.1.
    # Permit exactly one of the known clean/local alternatives, but never guess.
    if isinstance(old, (tuple, list)):
        matched = [part for part in old if s.count(part) == 1]
        if len(matched) != 1:
            raise RuntimeError(f'{name}: expected one known source variant, found {len(matched)}. Nothing changed.')
        old = matched[0]
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: expected exactly one matching anchor; found {count}. Nothing changed.')
    return s.replace(old, new, 1)


def transform(root: Path):
    originals = {}
    changed = {}

    def edit(relative, modifications):
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f'Missing file: {path}')
        raw = path.read_text(encoding='utf-8')
        originals[path] = raw
        result = raw
        for n, (old, new) in enumerate(modifications, 1):
            result = replace_once(result, old, new, f'{relative} anchor {n}')
        changed[path] = result

    edit(SOURCES/'camera/CameraUiState.kt', [
        ('import com.meta.wearable.dat.camera.types.StreamState\n',
         'import com.meta.wearable.dat.camera.types.StreamState\nimport com.meta.wearable.dat.camera.types.VideoQuality\n'),
        ('    val isStartingStream: Boolean = false,\n',
         '    val isStartingStream: Boolean = false,\n'
         '    // Requested settings persist per Android device. Actual values may be downgraded by DAT.\n'
         '    val requestedVideoQuality: VideoQuality = VideoQuality.HIGH,\n'
         '    val requestedFrameRate: Int = 30,\n'
         '    val actualWidth: Int = 0,\n'
         '    val actualHeight: Int = 0,\n'
         '    val observedFrameRate: Float = 0f,\n'),
    ])

    edit(SOURCES/'camera/CameraViewModel.kt', [
        ('import android.app.Application\n', 'import android.app.Application\nimport android.content.Context\nimport android.os.SystemClock\n'),
        (('    private const val FRAME_RATE = 24\n', '    private const val FRAME_RATE = 30\n'), ''),
        ('  private val _uiState = MutableStateFlow(CameraUiState())\n',
         '  private val streamPreferences = application.getSharedPreferences(\n'
         '      "kilo_glasses_stream_settings", Context.MODE_PRIVATE)\n'
         '  private val _uiState = MutableStateFlow(\n'
         '      CameraUiState(\n'
         '          requestedVideoQuality = when (streamPreferences.getString("quality", "HIGH")) {\n'
         '            "LOW" -> VideoQuality.LOW\n'
         '            "MEDIUM" -> VideoQuality.MEDIUM\n'
         '            else -> VideoQuality.HIGH\n'
         '          },\n'
         '          requestedFrameRate = streamPreferences.getInt("fps", 30).let {\n'
         '            if (it in listOf(15, 24, 30)) it else 30\n'
         '          },\n'
         '      ),\n'
         '  )\n'),
        ('  private var streamErrorJob: Job? = null\n',
         '  private var streamErrorJob: Job? = null\n'
         '\n'
         '  // A settings change stops only the camera capability, not the glasses session.\n'
         '  private var restartPreviewAfterSettings = false\n'
         '  // Updated on frameDispatcher. These represent received, not requested, frames.\n'
         '  private var frameWindowStartedAtMs = 0L\n'
         '  private var frameCountInWindow = 0\n'),
        ('  fun endSession() {\n    val current = session ?: return\n',
         '  fun endSession() {\n    restartPreviewAfterSettings = false\n    val current = session ?: return\n'),
        ('  private fun cleanupSession() {\n',
         '  private fun cleanupSession() {\n    restartPreviewAfterSettings = false\n'),
        (('                videoQuality = VideoQuality.MEDIUM,\n                frameRate = FRAME_RATE,\n',
          '                videoQuality = VideoQuality.HIGH,\n                frameRate = FRAME_RATE,\n'),
         '                videoQuality = _uiState.value.requestedVideoQuality,\n'
         '                frameRate = _uiState.value.requestedFrameRate,\n'),
        ('  /** Stops the camera stream but keeps the [DeviceSession] connected. */\n',
         '  /**\n'
         '   * Save camera settings for this phone/tablet. If preview is active, stop the camera stream\n'
         '   * and restart after the sample has released the existing camera capability. We do not\n'
         '   * interrupt an in-progress photo or MP4 recording, and never end the device session.\n'
         '   */\n'
         '  fun applyStreamSettings(quality: VideoQuality, frameRate: Int) {\n'
         '    val state = _uiState.value\n'
         '    if (frameRate !in listOf(15, 24, 30) || state.isBusy || state.isRecording ||\n'
         '        state.isCapturingPhoto || state.isPaused) return\n'
         '    if (state.requestedVideoQuality == quality && state.requestedFrameRate == frameRate) return\n'
         '    val qualityValue = when (quality) {\n'
         '      VideoQuality.LOW -> "LOW"\n'
         '      VideoQuality.MEDIUM -> "MEDIUM"\n'
         '      else -> "HIGH"\n'
         '    }\n'
         '    streamPreferences.edit().putString("quality", qualityValue).putInt("fps", frameRate).apply()\n'
         '    _uiState.update { it.copy(requestedVideoQuality = quality, requestedFrameRate = frameRate) }\n'
         '    if (state.hasStream && state.isStreaming) {\n'
         '      restartPreviewAfterSettings = true\n'
         '      stopStreaming()\n'
         '    }\n'
         '  }\n'
         '\n'
         '  /** Stops the camera stream but keeps the [DeviceSession] connected. */\n'),
        ('    if (!videoFrame.isCodecConfig && !_uiState.value.hasReceivedFirstFrame) {\n'
         '      _uiState.update { it.copy(hasReceivedFirstFrame = true) }\n'
         '    }\n',
         '    if (!videoFrame.isCodecConfig) {\n'
         '      // Low-frequency UI telemetry to avoid recomposing for every HEVC frame.\n'
         '      val now = SystemClock.elapsedRealtime()\n'
         '      if (frameWindowStartedAtMs == 0L) frameWindowStartedAtMs = now\n'
         '      frameCountInWindow++\n'
         '      val elapsedMs = now - frameWindowStartedAtMs\n'
         '      val reportFps = elapsedMs >= 1_000L\n'
         '      val fps = if (reportFps) frameCountInWindow * 1000f / elapsedMs else 0f\n'
         '      val previous = _uiState.value\n'
         '      if (!previous.hasReceivedFirstFrame || previous.actualWidth != width ||\n'
         '          previous.actualHeight != height || reportFps) {\n'
         '        _uiState.update {\n'
         '          it.copy(\n'
         '              hasReceivedFirstFrame = true,\n'
         '              actualWidth = width,\n'
         '              actualHeight = height,\n'
         '              observedFrameRate = if (reportFps) fps else it.observedFrameRate,\n'
         '          )\n'
         '        }\n'
         '      }\n'
         '      if (reportFps) {\n'
         '        frameCountInWindow = 0\n'
         '        frameWindowStartedAtMs = now\n'
         '      }\n'
         '    }\n'),
        ('      clearStreamResources()\n    }\n  }\n\n  private fun clearStreamResources() {\n',
         '      clearStreamResources()\n'
         '      val shouldRestart = restartPreviewAfterSettings\n'
         '      restartPreviewAfterSettings = false\n'
         '      if (shouldRestart && _uiState.value.isSessionActive) startStreaming()\n'
         '    }\n  }\n\n  private fun clearStreamResources() {\n'),
        ('    csdCollector.reset()\n    StreamingService.stop(getApplication())\n',
         '    csdCollector.reset()\n'
         '    frameWindowStartedAtMs = 0L\n'
         '    frameCountInWindow = 0\n'
         '    StreamingService.stop(getApplication())\n'),
        ('    _uiState.update { it.copy(streamState = StreamState.STOPPED, hasReceivedFirstFrame = false) }\n',
         '    _uiState.update {\n'
         '      it.copy(\n'
         '          streamState = StreamState.STOPPED, hasReceivedFirstFrame = false,\n'
         '          actualWidth = 0, actualHeight = 0, observedFrameRate = 0f)\n'
         '    }\n'),
        ('  private fun handleUnregistered() {\n    session?.stop()\n',
         '  private fun handleUnregistered() {\n    restartPreviewAfterSettings = false\n    session?.stop()\n'),
    ])

    edit(SOURCES/'ui/CameraScreen.kt', [
        ('import androidx.compose.material.icons.filled.Stop\n',
         'import androidx.compose.material.icons.filled.Stop\nimport androidx.compose.material.icons.filled.Tune\n'),
        ('  var showSettingsMenu by remember { mutableStateOf(false) }\n',
         '  var showSettingsMenu by remember { mutableStateOf(false) }\n'
         '  var showStreamSettings by remember { mutableStateOf(false) }\n'),
        ('          onToggleSettings = { showSettingsMenu = !showSettingsMenu },\n',
         '          onToggleSettings = { showSettingsMenu = !showSettingsMenu },\n'
         '          onOpenStreamSettings = { showStreamSettings = true },\n'),
        ('    if (ui.showCameraPermissionRedirectConfirm) {\n',
         '    if (showStreamSettings) {\n'
         '      StreamSettingsDialog(\n'
         '          ui = ui,\n'
         '          onDismiss = { showStreamSettings = false },\n'
         '          onApply = { quality, fps ->\n'
         '            cameraViewModel.applyStreamSettings(quality, fps)\n'
         '            showStreamSettings = false\n'
         '          },\n'
         '      )\n'
         '    }\n'
         '\n'
         '    if (ui.showCameraPermissionRedirectConfirm) {\n'),
        ('    showSettingsMenu: Boolean,\n    onToggleSettings: () -> Unit,\n',
         '    showSettingsMenu: Boolean,\n    onToggleSettings: () -> Unit,\n'
         '    onOpenStreamSettings: () -> Unit,\n'),
        ('    Spacer(modifier = Modifier.weight(1f))\n\n    Box {\n',
         '    Spacer(modifier = Modifier.weight(1f))\n\n'
         '    Icon(\n'
         '        imageVector = Icons.Filled.Tune,\n'
         '        contentDescription = "Video settings",\n'
         '        tint = Color.White,\n'
         '        modifier = Modifier.size(28.dp).clickable(onClick = onOpenStreamSettings)\n'
         '            .testTag("stream_settings_button"),\n'
         '    )\n'
         '    Spacer(modifier = Modifier.width(18.dp))\n\n    Box {\n'),
    ])

    edit(PREFIX/'app/build.gradle.kts', [
        ('    versionCode = 1\n    versionName = "1.0"\n',
         '    versionCode = 2\n    versionName = "0.1.0-kilo"\n'),
    ])
    edit(PREFIX/'app/src/main/res/values/strings.xml', [
        ('<string name="app_name" description="Launcher label / app name">Camera Access</string>',
         '<string name="app_name" description="Launcher label / app name">Glasses Bridge Test</string>'),
    ])

    dialog_path = root/SOURCES/'ui/StreamSettingsDialog.kt'
    if dialog_path.exists():
        raise FileExistsError(f'Already exists: {dialog_path}. Nothing changed.')
    changed[dialog_path] = DIALOG_CONTENT

    manual = root/PREFIX/'KILO_STREAM_CONTROLS.md'
    if manual.exists():
        raise FileExistsError(f'Already exists: {manual}. Nothing changed.')
    changed[manual] = GUIDE_CONTENT

    workflow = root/'.github/workflows/cameraaccess-debug-apk.yml'
    if workflow.exists():
        raise FileExistsError(f'Already exists: {workflow}. Nothing changed.')
    changed[workflow] = WORKFLOW_CONTENT

    # All transformations / anchor checks succeeded. Only now write files.
    for path, content in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return list(changed)


DIALOG_CONTENT = '''/*
 * Kilo Glasses Bridge test controls, based on Meta CameraAccess sample.
 */
package com.meta.wearable.dat.externalsampleapps.cameraaccess.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.externalsampleapps.cameraaccess.camera.CameraUiState
import java.util.Locale

@Composable
internal fun StreamSettingsDialog(
    ui: CameraUiState,
    onDismiss: () -> Unit,
    onApply: (VideoQuality, Int) -> Unit,
) {
  var chosenQuality by remember { mutableStateOf(ui.requestedVideoQuality) }
  var chosenFps by remember { mutableStateOf(ui.requestedFrameRate) }
  var qualityMenuOpen by remember { mutableStateOf(false) }
  var fpsMenuOpen by remember { mutableStateOf(false) }
  val canApply = !ui.isBusy && !ui.isRecording && !ui.isCapturingPhoto && !ui.isPaused

  AlertDialog(
      onDismissRequest = onDismiss,
      title = { Text("Glasses Bridge v0.1") },
      text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Text("Video quality (requested)")
          Box {
            OutlinedButton(onClick = { qualityMenuOpen = true }) {
              Text(qualityLabel(chosenQuality))
              Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
            }
            DropdownMenu(
                expanded = qualityMenuOpen,
                onDismissRequest = { qualityMenuOpen = false },
            ) {
              listOf(VideoQuality.HIGH, VideoQuality.MEDIUM, VideoQuality.LOW).forEach { option ->
                DropdownMenuItem(
                    text = { Text(qualityLabel(option)) },
                    onClick = { chosenQuality = option; qualityMenuOpen = false },
                )
              }
            }
          }

          Text("Target frame rate")
          Box {
            OutlinedButton(onClick = { fpsMenuOpen = true }) {
              Text("$chosenFps FPS")
              Icon(Icons.Filled.ArrowDropDown, contentDescription = null)
            }
            DropdownMenu(expanded = fpsMenuOpen, onDismissRequest = { fpsMenuOpen = false }) {
              listOf(30, 24, 15).forEach { option ->
                DropdownMenuItem(
                    text = { Text("$option FPS") },
                    onClick = { chosenFps = option; fpsMenuOpen = false },
                )
              }
            }
          }

          val resolution = if (ui.actualWidth > 0 && ui.actualHeight > 0) {
            "${ui.actualWidth} x ${ui.actualHeight}"
          } else "Waiting for video"
          val observed = if (ui.observedFrameRate > 0f) {
            String.format(Locale.US, "%.1f FPS", ui.observedFrameRate)
          } else "Waiting for video"
          Text("Received: $resolution | $observed")
          Text("Session: ${ui.sessionStateText} | Stream: ${ui.streamStateText}")
          Text("Apply restarts the preview when it is running. Recordings cannot be interrupted. " +
              "Actual quality may fall below the requested setting.")
        }
      },
      confirmButton = {
        TextButton(onClick = { onApply(chosenQuality, chosenFps) }, enabled = canApply) {
          Text("Apply")
        }
      },
      dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
  )
}

private fun qualityLabel(quality: VideoQuality): String = when (quality) {
  VideoQuality.LOW -> "Low (360 x 640)"
  VideoQuality.MEDIUM -> "Medium (504 x 896)"
  else -> "High (720 x 1280)"
}
'''

GUIDE_CONTENT = '''# Kilo Glasses Bridge v0.1 — test instructions

This is a minimally modified version of the **Meta CameraAccess Android sample**.
It keeps the SDK registration, HEVC preview, photo capture, MP4 recording and audio
paths intact. In the camera screen, tap the **sliders / Tune** icon at the top.

## Controls

- Choose **High / Medium / Low** requested video quality.
- Choose **30 / 24 / 15 FPS**.
- Tap **Apply**. If preview is streaming, the app stops **only the camera stream**,
  waits for the sample's normal cleanup, and starts preview again with new settings.
  It leaves the device session connected. If preview is stopped, simply press
  Preview to start it using the saved settings.
- Settings persist independently on each Android device using SharedPreferences.
- The dialog shows the latest **received frame dimensions** and approximately
  **1-second sampled frame rate**. These are not necessarily the requested values.
- Apply is disabled while a photo is being captured, recording is active, the
  stream/session is transitioning, or the device has paused the camera.
- HEVC `compressVideo=true` is intentionally unchanged; turning it off requires
  modifying the decoder and MP4 recording paths first.

## Build / install

Open `samples/CameraAccess` in Android Studio and build `app` as usual.
Or run from that project directory:

```powershell
.\\gradlew.bat :app:assembleDebug
```

APK: `samples/CameraAccess/app/build/outputs/apk/debug/app-debug.apk`.
Install via Android Studio or `adb install -r <path-to-apk>`.

The project uses the same application ID as CameraAccess; with the same debug
signing certificate it can update the existing sample. For a different development
PC / signing key, Android may require an uninstall (which clears app registration).

## Outdoor and offline tests

1. Test Tab S9 on Wi-Fi, then on LTE/5G, then with internet disabled while the
   phone/tablet remains paired. Record *whether SDK registration/session can start*;
   offline operation is **not guaranteed by this patch**.
2. Repeat on Z Fold 3 after deliberate pairing/connection handoff, not concurrently.
3. Record requested/actual video resolution, observed FPS, stable duration, and
   whether the on-glasses DAT component remains available after idle.
4. Keep the glasses on/unfolded. Do not reset the glasses or change firmware.

## Security / scope

No new network service, internet publishing, keys, or device permissions are added.
Only source and UI controls are changed; the app still depends on Meta's toolkit.
For v0.2, the next milestone will be an authenticated encoder/transport bridge to
our OVH relay and OBS.
'''

WORKFLOW_CONTENT = '''name: CameraAccess test APK
on:
  push:
    branches: [feature/stream-controls]
    paths:
      - 'samples/CameraAccess/**'
      - '.github/workflows/cameraaccess-debug-apk.yml'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  debug-apk:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'
      - name: Set up Android SDK 36
        run: |
          "${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager" 'platforms;android-36' 'build-tools;36.0.0'
      - name: Generate local developer-mode settings (no secrets)
        working-directory: samples/CameraAccess
        run: |
          printf 'mwdat_application_id=0\\nmwdat_client_token=0\\n' > local.properties
      - name: Build debug APK
        working-directory: samples/CameraAccess
        run: bash gradlew :app:assembleDebug --no-daemon
      - name: Publish test APK artifact
        uses: actions/upload-artifact@v4
        with:
          name: glasses-bridge-v0.1-debug-apk
          path: samples/CameraAccess/app/build/outputs/apk/debug/app-debug.apk
'''


def find_root(candidate: Path) -> Path:
    here = candidate.resolve()
    for path in [here, *here.parents]:
        if (path/PREFIX/'app/build.gradle.kts').is_file():
            return path
    raise FileNotFoundError('Cannot find samples/CameraAccess/app/build.gradle.kts. Supply the repository root.')


if __name__ == '__main__':
    candidate = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    try:
        root = find_root(candidate)
        paths = transform(root)
        print('Kilo Glasses Bridge v0.1 applied to:', root)
        for path in paths:
            print('  ', path.relative_to(root))
        print('Next: open samples/CameraAccess in Android Studio and build the debug APK.')
    except Exception as error:
        print('ERROR:', error, file=sys.stderr)
        sys.exit(1)
