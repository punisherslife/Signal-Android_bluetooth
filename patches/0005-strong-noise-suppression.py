#!/usr/bin/env python3
"""Add a persistent live RNNoise-Little strong-noise-suppression toggle.

Layering:
  0001-hq-bluetooth.py
  0002-proximity-toggle.py
  0003-video-phone-speaker.py
  0004-hq-call-gain.py
  0005-strong-noise-suppression.py   (this file)

Runtime design:
- OFF preserves stock effects and audio samples; the installed frame queue remains.
- ON enables an additional RNNoise Little AudioFrameProcessor on captured audio.
- the processor is installed once when each PeerConnectionFactory is created.
- toggling does not rebuild factories or switch Android/WebRTC suppressors live;
  RingRTC only flips the processor's native atomic bypass flag.
- RNNoise runs natively before encoding and off WebRTC's realtime capture path.
- the preference is persistent and restored before new call factories are made.

The matching custom RingRTC/WebRTC AAR is built by tools/rnnoise.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
POPUP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt"
SIGNAL_CALL_MANAGER = ROOT / "app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java"
PREF = ROOT / "app/src/main/java/org/thoughtcrime/securesms/service/webrtc/StrongNoiseSuppressionPreference.kt"
STRINGS = ROOT / "app/src/main/res/values/strings.xml"


def die(message: str) -> None:
    raise RuntimeError(f"0005-strong-noise-suppression: {message}")


def read(path: Path) -> str:
    if not path.exists():
        die(f"missing expected Signal source file: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def add_imports(text: str, imports: list[str]) -> str:
    lines = text.splitlines()
    indexes = [i for i, line in enumerate(lines) if line.startswith("import ")]
    if not indexes:
        die("AdditionalActionsPopup.kt: import block not found")

    start = indexes[0]
    end = indexes[-1] + 1
    current = {line for line in lines[start:end] if line.startswith("import ")}
    current |= {f"import {item}" for item in imports}

    def order(line: str) -> tuple[int, str]:
        path = line.removeprefix("import ")
        if " as " in path:
            return (4, path)
        if path.startswith("java."):
            return (1, path)
        if path.startswith("javax."):
            return (2, path)
        if path.startswith("kotlin."):
            return (3, path)
        return (0, path)

    lines[start:end] = sorted(current, key=order)
    return "\n".join(lines) + "\n"


def patch_popup(text: str) -> str:
    if "HqCallGainSlider" not in text or "isProximitySensorEnabled" not in text:
        die("AdditionalActionsPopup.kt does not look like patches 0001-0004 were applied")
    if "StrongNoiseSuppressionToggle" in text or "StrongNoiseSuppressionPreference" in text:
        die("AdditionalActionsPopup.kt already appears to contain patch 0005")

    text = add_imports(
        text,
        [
            "androidx.compose.runtime.mutableStateOf",
            "org.thoughtcrime.securesms.dependencies.AppDependencies",
            "org.thoughtcrime.securesms.service.webrtc.StrongNoiseSuppressionPreference",
        ],
    )

    old_proximity = '''    CallScreenMenuToggle(
      title = stringResource(R.string.CallOverflowPopupWindow__proximity_sensor),
      checked = isProximitySensorEnabled,
      onCheckedChange = onProximitySensorClick
    )
'''
    new_proximity = '''    CallScreenMenuToggle(
      title = stringResource(R.string.CallOverflowPopupWindow__proximity_sensor),
      checked = isProximitySensorEnabled,
      onCheckedChange = onProximitySensorClick
    )
    StrongNoiseSuppressionToggle()
'''
    text = replace_once(text, old_proximity, new_proximity, "proximity menu block")

    marker = '''@Composable
private fun HqCallGainSlider() {
'''
    toggle = '''@Composable
private fun StrongNoiseSuppressionToggle() {
  var enabled by remember {
    mutableStateOf(StrongNoiseSuppressionPreference.isEnabled())
  }

  CallScreenMenuToggle(
    title = stringResource(R.string.CallOverflowPopupWindow__strong_noise_suppression),
    checked = enabled,
    onCheckedChange = { value ->
      if (AppDependencies.signalCallManager.setStrongNoiseSuppressionEnabled(value)) {
        enabled = value
      }
    }
  )
}

@Composable
private fun HqCallGainSlider() {
'''
    return replace_once(text, marker, toggle, "HqCallGainSlider insertion point")


def patch_signal_call_manager(text: str) -> str:
    if "setStrongNoiseSuppressionEnabled" in text or "StrongNoiseSuppressionPreference" in text:
        die("SignalCallManager.java already appears to contain patch 0005")

    old_assignment = '''    this.callManager = callManager;

    this.serviceState = new WebRtcServiceState(new IdleActionProcessor(new WebRtcInteractor(this.context,
'''
    new_assignment = '''    this.callManager = callManager;

    if (this.callManager != null) {
      boolean strongNoiseSuppressionEnabled = StrongNoiseSuppressionPreference.isEnabled();
      try {
        if (!this.callManager.setStrongNoiseSuppressionEnabled(strongNoiseSuppressionEnabled)) {
          Log.w(TAG, "Unable to restore RNNoise Little preference");
        }
      } catch (RuntimeException e) {
        Log.w(TAG, "Unable to restore RNNoise Little preference", e);
      }
    }

    this.serviceState = new WebRtcServiceState(new IdleActionProcessor(new WebRtcInteractor(this.context,
'''
    text = replace_once(text, old_assignment, new_assignment, "SignalCallManager constructor")

    marker = '''  public void startPreJoinCall(@NonNull Recipient recipient) {
'''
    method = '''  /**
   * Persist and toggle the native RNNoise Little capture processor.
   *
   * The processor itself is installed once per PeerConnectionFactory. This call
   * changes only its native bypass flag; it does not rebuild or reconfigure the
   * active Android/WebRTC audio graph.
   */
  public boolean setStrongNoiseSuppressionEnabled(boolean enabled) {
    if (callManager == null) {
      return false;
    }

    try {
      boolean applied = callManager.setStrongNoiseSuppressionEnabled(enabled);
      if (applied) {
        StrongNoiseSuppressionPreference.setEnabled(enabled);
      }
      return applied;
    } catch (RuntimeException e) {
      Log.w(TAG, "Unable to toggle RNNoise Little", e);
      return false;
    }
  }

  public void startPreJoinCall(@NonNull Recipient recipient) {
'''
    return replace_once(text, marker, method, "SignalCallManager public method insertion")


def patch_strings(text: str) -> str:
    if "CallOverflowPopupWindow__strong_noise_suppression" in text:
        die("strings.xml already appears to contain patch 0005")

    old = '''    <string name="CallOverflowPopupWindow__proximity_sensor">Proximity sensor</string>
'''
    new = '''    <string name="CallOverflowPopupWindow__proximity_sensor">Proximity sensor</string>
    <string name="CallOverflowPopupWindow__strong_noise_suppression">Strong noise suppression</string>
'''
    return replace_once(text, old, new, "noise suppression string anchor")


PREF_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.service.webrtc

import android.content.Context
import org.thoughtcrime.securesms.dependencies.AppDependencies

/** Persistent opt-in state for the native RNNoise Little capture processor. */
object StrongNoiseSuppressionPreference {
  private const val PREFS_NAME = "strong_noise_suppression"
  private const val PREF_ENABLED = "enabled"

  @JvmStatic
  fun isEnabled(): Boolean {
    return preferences().getBoolean(PREF_ENABLED, false)
  }

  @JvmStatic
  fun setEnabled(enabled: Boolean) {
    preferences()
      .edit()
      .putBoolean(PREF_ENABLED, enabled)
      .apply()
  }

  private fun preferences() = AppDependencies.application
    .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}
'''

if PREF.exists():
    die(f"preference file already exists: {PREF}")

# Validate every transform before writing anything.
patched_popup = patch_popup(read(POPUP))
patched_manager = patch_signal_call_manager(read(SIGNAL_CALL_MANAGER))
patched_strings = patch_strings(read(STRINGS))

write(POPUP, patched_popup)
write(SIGNAL_CALL_MANAGER, patched_manager)
write(STRINGS, patched_strings)
write(PREF, PREF_SOURCE)

print("0005-strong-noise-suppression: added persistent RNNoise Little toggle")
print("0005-strong-noise-suppression: OFF keeps stock Signal processing; ON adds native RNNoise")
print("0005-strong-noise-suppression: live toggle changes only a native bypass flag")
print("0005-strong-noise-suppression: requires tools/rnnoise custom RingRTC/WebRTC AAR")
