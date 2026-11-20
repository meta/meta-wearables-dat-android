/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 */

package com.meta.pixelandtexel.birdspotter.features.settings

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.CreationExtras
import com.meta.pixelandtexel.birdspotter.domain.GlassesAccess
import com.meta.pixelandtexel.birdspotter.domain.GlassesCompatibility
import com.meta.pixelandtexel.birdspotter.domain.GlassesDeviceInfo
import com.meta.pixelandtexel.birdspotter.domain.GlassesPermission
import com.meta.pixelandtexel.birdspotter.domain.GlassesRegistrationState
import com.meta.pixelandtexel.birdspotter.domain.GlassesSessionRepository
import com.meta.wearable.dat.core.Wearables
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn

/**
 * When a grant is worth re-reading: every time the link changes, and every time something asks.
 *
 * **The link is the trigger, because DAT's answer depends on it.** `access()` reads the grant off a
 * connected pair, so the same phone and the same Meta AI account answer differently before and
 * after the glasses connect. A single read at construction froze the row on whichever of the two
 * was true when the screen opened — the reason connecting the glasses appeared to change nothing
 * until the app was restarted.
 *
 * Reachability, not the whole device: a pair that renames itself is not news to a permission. The
 * suspend lives inside [combine] deliberately, which serialises the readings, so a link that
 * flickers cannot land an older answer on top of a newer one.
 *
 * Internal so the mirrored tests can pin the policy without a dispatcher under `viewModelScope` —
 * the same seam `RealtimeViewModel.deliverAnswer` keeps.
 */
internal fun accessStream(
    glassesSession: GlassesSessionRepository,
    permission: GlassesPermission,
    refreshes: Flow<Int>,
): Flow<GlassesAccess> = combine(
    glassesSession.deviceInfoStream().map { it?.isAvailable == true }.distinctUntilChanged(),
    refreshes,
) { _, _ ->
  glassesSession.access(permission)
}

/**
 * What the glasses settings screen reports: where registration stands, which glasses Meta AI knows
 * about, and whether each of Meta AI's grants can be read and has been given.
 *
 * Mostly reads. The raises — the grant flows, unlinking — live in the screen, because Android can
 * only raise either from an Activity; see [SettingsViewModel] for the same split and
 * [com.meta.pixelandtexel.birdspotter.domain.PermissionsController] for the rule it follows. The
 * firmware update raise is the exception: it lives here, taking the Activity the screen hands it.
 */
class GlassesSettingsViewModel(
    private val glassesSession: GlassesSessionRepository,
) : ViewModel() {

  /** Where registration stands — `null` until the first reading lands. */
  val registrationState: StateFlow<GlassesRegistrationState?> =
      glassesSession
          .registrationStateStream()
          .stateIn(viewModelScope, SharingStarted.WhileSubscribed(), null)

  /** The first pair Meta AI lists — `null` while unread, and `null` when there are none. */
  // docs:glasses-device-info:begin
  val deviceInfo: StateFlow<GlassesDeviceInfo?> =
      glassesSession
          .deviceInfoStream()
          .stateIn(viewModelScope, SharingStarted.WhileSubscribed(), null)
  // docs:glasses-device-info:end

  val requiresFirmwareUpdate: StateFlow<Boolean> =
      deviceInfo
          .map { it?.compatibility == GlassesCompatibility.DEVICE_UPDATE_REQUIRED }
          .stateIn(viewModelScope, SharingStarted.WhileSubscribed(), false)

  private val _firmwareUpdateFailure = MutableStateFlow<String?>(null)
  val firmwareUpdateFailure: StateFlow<String?> = _firmwareUpdateFailure

  private val _isLaunchingFirmwareUpdate = MutableStateFlow(false)
  val isLaunchingFirmwareUpdate: StateFlow<Boolean> = _isLaunchingFirmwareUpdate

  /** Bumped by [refreshAccess] to re-run the checks without a link change. */
  private val refreshes = MutableStateFlow(0)

  /**
   * Where the DAT camera grant stands — `null` until the first check answers, and re-read on every
   * link change thereafter. [accessStream] holds the why.
   */
  val cameraAccess: StateFlow<GlassesAccess?> =
      accessStream(glassesSession, GlassesPermission.CAMERA, refreshes)
          .stateIn(viewModelScope, SharingStarted.WhileSubscribed(), null)

  /** Where the DAT microphone grant stands, on the same terms as [cameraAccess]. */
  val microphoneAccess: StateFlow<GlassesAccess?> =
      accessStream(glassesSession, GlassesPermission.MICROPHONE, refreshes)
          .stateIn(viewModelScope, SharingStarted.WhileSubscribed(), null)

  /**
   * Asks again, for every grant the screen shows. They are given in the Meta AI app, off in another
   * process, so there is no stream to follow — the screen calls this when one of its grant flows
   * returns, and the link itself drives the rest.
   *
   * **Both are re-read whichever flow returned**, off the one counter. Meta AI shows the grants
   * together, so somebody sent there to allow the microphone can allow the camera on the same
   * screen, and a row that only re-read the grant it raised would go on reporting the other one
   * stale.
   */
  fun refreshAccess() {
    refreshes.value += 1
  }

  fun openFirmwareUpdate(activity: Activity) {
    if (_isLaunchingFirmwareUpdate.value) return
    _isLaunchingFirmwareUpdate.value = true
    try {
      Wearables.openFirmwareUpdate(activity)
          .fold(
              onSuccess = { _firmwareUpdateFailure.value = null },
              onFailure = { error, _ -> _firmwareUpdateFailure.value = error.description },
          )
    } catch (error: Exception) {
      _firmwareUpdateFailure.value =
          error.localizedMessage?.takeIf { it.isNotBlank() } ?: "The update could not be opened."
    } finally {
      _isLaunchingFirmwareUpdate.value = false
    }
  }

  companion object {
    fun factory(
        glassesSession: GlassesSessionRepository,
    ): ViewModelProvider.Factory =
        object : ViewModelProvider.Factory {
          override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T {
            @Suppress("UNCHECKED_CAST")
            return GlassesSettingsViewModel(glassesSession) as T
          }
        }
  }
}
