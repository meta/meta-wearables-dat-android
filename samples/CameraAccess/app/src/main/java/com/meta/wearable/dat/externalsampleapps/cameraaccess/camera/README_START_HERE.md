# Kilo Glasses Bridge v0.1 — hands-on build kit

This kit is prepared for [`deadman2496/glasses-bridge`](https://github.com/deadman2496/glasses-bridge), based on its `main` branch as inspected on 2026-11-08. It does **not** include the full upstream SDK or an APK. You already have those source files in your local clone.

## What we are adding

- A **Tune** (sliders) button on the CameraAccess screen
- Dropdowns for requested **Low / Medium / High** and **15 / 24 / 30 FPS**
- **Apply**: saves settings per Android device, stops preview **only if running**, and restarts preview after normal SDK cleanup
- Real **received width × height** and approximately one-second-sampled **received FPS**
- A safety guard: Apply is disabled while recording, taking a photo, transitioning, or paused
- Existing HEVC preview, mic, still-photo, and recording code are left intact

No streaming to OBS, server API, or offline capability is added in v0.1. Those come after this test.

## Recommended method to learn *and* save time

1. In **PowerShell**, navigate to the root of your local `glasses-bridge` checkout (the folder containing `samples/CameraAccess`):

   ```powershell
   git status
   git switch -c feature/stream-controls
   ```

2. If you have uncommitted adjustments to HIGH / 30 FPS, **save or commit those first** so you don't lose them. The script accepts either the original MEDIUM / 24 settings or the local HIGH / 30 combination.

3. Copy `apply_stream_controls.py` into that checkout's root. Review its `transform()` function: it modifies only specific source anchors; if an anchor is missing, it stops *before* writing any files.

4. Run:

   ```powershell
   py apply_stream_controls.py .
   ```

5. **Study the generated code before building**:

   ```powershell
   git diff -- samples/CameraAccess
   git status
   ```

   See `MANUAL_EDIT_GUIDE.md` to understand each insertion and the new `StreamSettingsDialog.kt` file.

6. Open `samples/CameraAccess` in Android Studio and run **Build > Make Project**. If successful, run **Build > Build Bundle(s) / APK(s) > Build APK(s)**, or:

   ```powershell
   cd samples/CameraAccess
   .\gradlew.bat :app:assembleDebug
   ```

   APK output: `samples/CameraAccess/app/build/outputs/apk/debug/app-debug.apk` (relative to repository root).

7. Install on Tab S9 first using Android Studio's **Run**. Once tested, install the same APK on the Z Fold 3 (`adb install -r ...` is another option). The camera connects to one companion device at a time, so test sequentially.

8. Commit only after inspecting the changes:

   ```powershell
   git add -- samples/CameraAccess/app/src/main/java samples/CameraAccess/app/src/main/res/values/strings.xml samples/CameraAccess/app/build.gradle.kts samples/CameraAccess/KILO_STREAM_CONTROLS.md .github/workflows/cameraaccess-debug-apk.yml
   git diff --cached --stat
   git commit -m "CameraAccess: add stream quality and FPS test controls"
   git push -u origin feature/stream-controls
   ```

   If `origin` points to Meta's upstream instead of your fork, add a remote called `kilo` and push there instead. Use `git remote -v` to check.

## Quality test plan

1. Wear the glasses and keep them unfolded so the device does not enter idle.
2. Open the camera session and start Preview.
3. Tap **Tune**, choose **High, 30 FPS**, then **Apply**. Preview should stop and restart by itself.
4. Confirm the dialog now shows *received* resolution and FPS (which may be lower than requested).
5. Try Medium/24 and High/15. Record brief clips. Do **not** apply while recording.
6. Test stopping Preview, changing settings, then manually starting Preview.
7. Repeat on the Fold 3 after separately transferring the glasses connection.
8. At the end, disconnect tablet Wi-Fi / cellular for a short local test. Record what functions fail offline: startup, registration, preview, capture, or recording. Do not assume this SDK is offline-independent.

## Limitations and safety

- **No APK is included** because this environment does not have the required Android SDK/Gradle dependency cache or a successful Android build. Build and validate locally in Android Studio.
- Camera transport, Meta registration, on-glasses toolkit installation, and offline support are SDK/platform dependencies; this app does not bypass them.
- The settings dialog is *not* a true dynamic reconfigure of the same running stream. The app does a controlled stop/restart, as requested.
- This test app intentionally retains the original application ID. Reinstalling with a different signing key may require uninstalling the earlier version (which can reset app registration).
- Do not commit `local.properties`, signing keys, personal captures, or stream credentials. The script does not touch credentials.
