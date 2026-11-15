/*
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
