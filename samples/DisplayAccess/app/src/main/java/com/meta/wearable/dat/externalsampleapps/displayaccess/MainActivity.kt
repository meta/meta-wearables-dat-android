/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 */

package com.meta.wearable.dat.externalsampleapps.displayaccess

import android.Manifest.permission.BLUETOOTH
import android.Manifest.permission.BLUETOOTH_CONNECT
import android.Manifest.permission.INTERNET
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions
import androidx.activity.viewModels
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.externalsampleapps.displayaccess.ui.AppScaffold
import com.meta.wearable.dat.externalsampleapps.displayaccess.ui.DisplayAccessTheme
import com.meta.wearable.dat.externalsampleapps.displayaccess.wearables.WearablesRepository
import com.meta.wearable.dat.externalsampleapps.displayaccess.wearables.WearablesViewModel
import com.meta.wearable.dat.mockdevice.MockDeviceKit

class MainActivity : ComponentActivity() {
  companion object {
    private const val TAG = "DisplayAccessMain"

    private const val EXTRA_UI_TESTING = "mwdat_ui_testing"

    private val PERMISSIONS = arrayOf(BLUETOOTH, BLUETOOTH_CONNECT, INTERNET)
  }

  private val wearablesViewModel: WearablesViewModel by viewModels()
  private val permissionsLauncher =
      registerForActivityResult(RequestMultiplePermissions()) { results ->
        if (results.entries.all { it.value }) {
          Wearables.initialize(this)
          wearablesViewModel.startObserving()
        } else {
          Toast.makeText(this, "All permissions are required", Toast.LENGTH_SHORT).show()
        }
      }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    maybeStartMockDeviceTestServer()
    enableEdgeToEdge()
    setContent { DisplayAccessTheme { AppScaffold(wearablesViewModel = wearablesViewModel) } }
  }

  override fun onStart() {
    super.onStart()
    permissionsLauncher.launch(PERMISSIONS)
  }

  private fun maybeStartMockDeviceTestServer() {
    if (!BuildConfig.DEBUG || !intent.getBooleanExtra(EXTRA_UI_TESTING, false)) {
      return
    }
    val mockDeviceKit = MockDeviceKit.getInstance(applicationContext)
    mockDeviceKit.enable()
    mockDeviceKit
        .startTestServer(WearablesRepository.MOCK_TEST_SERVER_PORT)
        .fold(
            onSuccess = { Log.i(TAG, "MockDevice test server started") },
            onFailure = { error, _ ->
              Log.w(TAG, "Failed to start MockDevice test server: ${error.description}")
            },
        )
  }
}
