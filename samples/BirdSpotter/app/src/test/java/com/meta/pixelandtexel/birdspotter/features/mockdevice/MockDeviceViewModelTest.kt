/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 */

package com.meta.pixelandtexel.birdspotter.features.mockdevice

import android.content.Context
import android.net.Uri
import android.os.Looper
import android.view.View
import com.meta.pixelandtexel.birdspotter.domain.GlassesAccess
import com.meta.pixelandtexel.birdspotter.domain.GlassesPermission
import com.meta.pixelandtexel.birdspotter.domain.GlassesThermalLevel
import com.meta.pixelandtexel.birdspotter.domain.MockCameraFacing
import com.meta.pixelandtexel.birdspotter.domain.MockCapturePress
import com.meta.pixelandtexel.birdspotter.domain.MockDeviceInfo
import com.meta.pixelandtexel.birdspotter.domain.MockDeviceRepository
import com.meta.pixelandtexel.birdspotter.domain.MockGlassesModel
import com.meta.pixelandtexel.birdspotter.domain.MockMotionPose
import com.meta.pixelandtexel.birdspotter.domain.MockNavDirection
import com.meta.pixelandtexel.birdspotter.domain.MockSpeechSource
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf

/**
 * The mock panel's one piece of policy: **which pair the controls are aimed at** as pairs come and
 * go.
 *
 * The kit holds up to a handful of simulated pairs and reports the list whole, so every change is a
 * fresh list rather than an event, and the panel has to decide where its controls point from the
 * list alone. The rule under test: stay on the pair being driven for as long as it exists, fall to
 * the latest pair when it does not, and point at nothing when there is nothing.
 *
 * Scenario names are fixed by the testing-parity rule.
 */
@RunWith(RobolectricTestRunner::class)
class MockDeviceViewModelTest {

  @Test
  fun requiringAnUpdate_reportsItToTheSelectedPair() {
    // The toggle flips the panel's reading and tells the pair in the same call.
    val mock = FakeMockDeviceRepository()
    val viewModel = MockDeviceViewModel(mock)
    idleMainLooper()
    mock.devices.value = listOf(rayBan)
    idleMainLooper()
    viewModel.select(rayBan.id)

    viewModel.setDATAppUpdateRequired(true)
    viewModel.setFirmwareUpdateRequired(true)

    assertTrue(viewModel.uiState.value.datAppUpdateRequired)
    assertTrue(viewModel.uiState.value.firmwareUpdateRequired)
    assertEquals(listOf(rayBan.id to true), mock.datAppCalls)
    assertEquals(listOf(rayBan.id to true), mock.firmwareCalls)

    viewModel.setDATAppUpdateRequired(false)

    assertFalse(viewModel.uiState.value.datAppUpdateRequired)
    assertEquals(listOf(rayBan.id to true, rayBan.id to false), mock.datAppCalls)
  }

  @Test
  fun requiringAnUpdate_withNoPairSelected_keepsTheToggleForTheNextPair() {
    // Nothing to tell yet: the state flips and no call goes out, so pairing later
    // picks the toggle up instead of losing it.
    val mock = FakeMockDeviceRepository()
    val viewModel = MockDeviceViewModel(mock)
    idleMainLooper()

    viewModel.setFirmwareUpdateRequired(true)

    assertTrue(viewModel.uiState.value.firmwareUpdateRequired)
    assertTrue(mock.firmwareCalls.isEmpty())
  }

  @Test
  fun pairing_carriesTogglesLeftOn_overToTheFreshPair() {
    // A fresh pair reports current versions, so toggles left on from the last pair
    // are re-applied to the pair just made.
    val mock = FakeMockDeviceRepository()
    val viewModel = MockDeviceViewModel(mock)
    idleMainLooper()
    mock.devices.value = listOf(rayBan)
    idleMainLooper()
    viewModel.select(rayBan.id)
    viewModel.setDATAppUpdateRequired(true)
    viewModel.setFirmwareUpdateRequired(true)
    mock.datAppCalls.clear()
    mock.firmwareCalls.clear()

    viewModel.pair()
    idleMainLooper()

    assertEquals(listOf("mock-2" to true), mock.datAppCalls)
    assertEquals(listOf("mock-2" to true), mock.firmwareCalls)
  }

  private fun idleMainLooper() = shadowOf(Looper.getMainLooper()).idle()

  @Test
  fun pairingSelectsTheNewPair() {
    // Nothing was selected; the first pair to arrive is the one the controls take.
    assertEquals(rayBan.id, selectedDeviceId(listOf(rayBan), current = null))
  }

  @Test
  fun aNewPairDoesNotStealTheSelection() {
    // Somebody is driving the Ray-Ban when a second pair arrives. The controls stay put: a
    // slider mid-drag must not switch glasses under the thumb.
    assertEquals(rayBan.id, selectedDeviceId(listOf(rayBan, display), current = rayBan.id))
  }

  @Test
  fun unpairingTheSelectedPairFallsBackToTheLatest() {
    // The pair being driven is unpaired. The latest remaining one is the closest thing to
    // where the controls were.
    assertEquals(display.id, selectedDeviceId(listOf(rayBan, display), current = "gone"))
  }

  @Test
  fun noPairsMeansNoSelection() {
    // The kit holds nothing — disabled, or every pair unpaired. Nothing to aim at.
    assertNull(selectedDeviceId(emptyList(), current = rayBan.id))
  }

  private val rayBan = MockDeviceInfo(id = "mock-1", model = MockGlassesModel.RAY_BAN_META)
  private val display = MockDeviceInfo(id = "mock-2", model = MockGlassesModel.META_RAY_BAN_DISPLAY)
}

private class FakeMockDeviceRepository : MockDeviceRepository {
  val devices = MutableStateFlow<List<MockDeviceInfo>>(emptyList())
  val datAppCalls = mutableListOf<Pair<String, Boolean>>()
  val firmwareCalls = mutableListOf<Pair<String, Boolean>>()

  override val isEnabled: Boolean = false

  override fun isEnabledStream(): Flow<Boolean> = flowOf(false)

  override suspend fun setEnabled(enabled: Boolean) = Unit

  override fun devicesStream(): Flow<List<MockDeviceInfo>> = devices

  override suspend fun pair(model: MockGlassesModel): MockDeviceInfo {
    val paired = MockDeviceInfo(id = "mock-2", model = model)
    devices.value += paired
    return paired
  }

  override fun unpair(id: String) {
    devices.value = devices.value.filterNot { it.id == id }
  }

  override fun powerOn(id: String) = Unit

  override fun powerOff(id: String) = Unit

  override fun don(id: String) = Unit

  override fun doff(id: String) = Unit

  override fun fold(id: String) = Unit

  override fun unfold(id: String) = Unit

  override fun setBatteryLevel(id: String, level: Int) = Unit

  override fun setCharging(id: String, isCharging: Boolean) = Unit

  override fun setThermal(id: String, level: GlassesThermalLevel) = Unit

  override fun setAccess(permission: GlassesPermission, access: GlassesAccess) = Unit

  override fun setRequestResult(permission: GlassesPermission, access: GlassesAccess) = Unit

  override fun setCameraFeed(id: String, fileUri: Uri) = Unit

  override fun setCameraFeed(id: String, facing: MockCameraFacing) = Unit

  override fun setCapturedPhoto(id: String, fileUri: Uri) = Unit

  override fun simulateCaptureFailure(id: String) = Unit

  override fun tap(id: String) = Unit

  override fun tapAndHold(id: String) = Unit

  override fun navigate(id: String, direction: MockNavDirection) = Unit

  override fun select(id: String) = Unit

  override fun back(id: String) = Unit

  override fun pressCapture(id: String, press: MockCapturePress) = Unit

  override fun pressActionButton(id: String) = Unit

  override fun setSpeechSource(id: String, source: MockSpeechSource) = Unit

  override fun simulateTranscription(id: String, text: String, isFinal: Boolean) = Unit

  override fun simulateSpeechError(id: String, message: String) = Unit

  override fun simulateSpeechCompletion(id: String) = Unit

  override fun setMotionPose(id: String, pose: MockMotionPose) = Unit

  override fun setDATAppUpdateRequirementEnabled(id: String, enabled: Boolean) {
    datAppCalls += id to enabled
  }

  override fun setFirmwareUpdateRequirementEnabled(id: String, enabled: Boolean) {
    firmwareCalls += id to enabled
  }

  override suspend fun startDisplayServer(): Int? = null

  override fun stopDisplayServer() = Unit

  override fun displayPreview(id: String, context: Context): View? = null

  override fun sendDisplayClick(id: String, identifier: String): Boolean = false

  override fun simulateVoiceLaunch(id: String): String? = null
}
