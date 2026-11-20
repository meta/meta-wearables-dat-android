---
name: mockdevice-mcp
description: Use this to drive a simulated wearable in an Android DAT app for self-verification — pair glasses, power/wear/fold, cap-touch, set a camera feed or captured image, inject inputs, motion, and speech, and read or click the glasses display — via the MockDevice MCP server, then observe the app with the Android screenshot/logcat tools.
---

# MockDevice MCP (Android)

Use this skill when you want to verify DAT app behavior without physical glasses by
controlling a simulated device over the MockDevice MCP server. The MCP is a client
of the app's in-app HTTP test server; it drives device state, and you observe the
result with the existing Android screenshot / UI / logcat tools.

No third-party dependencies — the server runs on the Python 3.8+ standard
library, launched with `python3`. The MCP server is
`mcp/mockdevice/mockdevice_mcp_server.py`.

## Prerequisite: the app must start its MockDevice test server

The test server starts when the app calls `startTestServer` — typically a debug build
launched with the `mwdat_ui_testing` intent extra, which also puts MockDeviceKit into
mock mode, as the DAT sample apps (e.g. `CameraAccess`) do. You are driving a *simulated*
device, not real glasses.

Launch (or relaunch) the app that way with adb, e.g.:

```
adb shell am start -n <package>/<launcher-activity> --ez mwdat_ui_testing true
```

If `mock_connect` reports no server, relaunch with that extra and try again.

## Normal agent loop

1. Make sure the app is running its MockDevice test server (sample apps: launch with the
   `mwdat_ui_testing` extra, see above).
2. `mock_connect(bundle_id="<your app package>", platform="android")` — auto-detects
   the attached device, forwards a local port to the app's fixed test-server
   loopback port over `adb`, and verifies health. Pass `udid` (the device serial)
   if more than one
   device/emulator is attached.
3. Drive device state, e.g.:
   - `mock_pair_device()`, then `mock_power_on()` and `mock_don()` — pairs Ray-Ban Meta,
     powers it on, and wears it. A newly paired device is off, folded, and not worn.
   - `mock_set_camera_feed(resource_name="plant", ext="mp4")` — the app must bundle
     the feed as an asset, for example `app/src/debug/assets/plant.mp4`.
   - `mock_power_off` / `mock_power_on`, `mock_doff` / `mock_don`,
     `mock_fold` / `mock_unfold`, `mock_captouch_tap`.
4. Observe the effect with the Android screenshot / UI / logcat tools and
   `mock_device_state`.

`device_id` is optional on device commands — it is auto-resolved when exactly one
device is paired.

## Tools

The server advertises every tool with its arguments and a description of how to verify
its effect, so read them from your tool list. Each tool name starts with `mock_`.

## Notes

- Camera feeds name an asset **bundled in the app**, by name and extension — not an
  arbitrary file path, and not a `res/raw` resource. The app's test server opens
  `<resource_name>.<ext>` with `AssetManager`, so a file outside `assets/` is reported
  as `resource not found`. The same applies to captured images and motion feeds.
- `mock_connect` refuses an app whose DAT SDK serves a different MockDevice route
  contract than this MCP calls, and says whether to update the app or the plugin.
  Relay that to the developer rather than retrying.
- `mock_connect` also reports the routes the attached app advertises. A tool added in
  a later SDK release than the app uses reports that it is unavailable instead of
  failing opaquely.
- Apart from `mock_display_content`, which reads the display back, these tools drive
  device state only. To assert other outcomes (a stream started, a photo was
  captured), read the app with the Android screenshot / UI / logcat tools.
- Display tools need a display-capable device: pair with
  `mock_pair_device(model="metaRayBanDisplay")`, not the default `rayBanMeta`.
  `mock_display_content` returns the display content the app sent, as a node tree — the
  semantic content, not a rendered image. It is a debug payload rather than a stable API,
  so read the document you get back instead of assuming field names. For pixels, host the
  SDK's own preview view and screenshot it; that renders the same content on the phone and
  is what a developer looks at. Click identifiers are content-derived and change on every
  redraw — take a fresh one from the tree each time. A `mock_display_click` ok means the
  tap was delivered, not that it matched an element, so confirm by re-reading and checking
  the revision moved.
