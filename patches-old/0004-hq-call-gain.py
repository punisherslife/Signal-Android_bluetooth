#!/usr/bin/env python3
"""Add the lightweight HQ-Bluetooth call gain slider experiment.

This patch is intentionally layered on top of the production v18 patch set:
  0001-hq-bluetooth.py
  0002-proximity-toggle.py
  0003-video-phone-speaker.py

Runtime design:
- no PCM/sample processing loop
- WebRTC's Android AudioTrack is registered once when playout starts
- 0..100% uses AudioTrack's per-track linear gain
- >100% uses any direct AudioTrack gain first, then Android LoudnessEnhancer
  for only the remaining gain on that AudioTrack's own audio session
- saved value is a tiny local SharedPreferences integer

The patch is strict: if the final v18-generated source shape is not present,
it aborts instead of guessing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
POPUP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt"
AUDIO = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/SignalAudioManager.kt"
AUDIO31 = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/FullSignalAudioManagerApi31.kt"
BRIDGE = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt"


def die(message: str) -> None:
    raise RuntimeError(f"0004-hq-call-gain: {message}")


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
    import_indexes = [i for i, line in enumerate(lines) if line.startswith("import ")]
    if not import_indexes:
        die("AdditionalActionsPopup.kt: import block not found")

    start = import_indexes[0]
    end = import_indexes[-1] + 1
    current = {line for line in lines[start:end] if line.startswith("import ")}
    current |= {f"import {item}" for item in imports}

    def import_order(line: str) -> tuple[int, str]:
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

    lines[start:end] = sorted(current, key=import_order)
    return "\n".join(lines) + "\n"


def patch_popup(text: str) -> str:
    if "isHighQualityBluetoothAudioEnabled" not in text or "isProximitySensorEnabled" not in text:
        die("AdditionalActionsPopup.kt does not look like production patches 0001+0002 were applied")
    if "HqCallGainSlider" in text or "HqCallGainBridge" in text:
        die("AdditionalActionsPopup.kt already appears to contain the gain experiment")

    text = add_imports(
        text,
        [
            "androidx.compose.material3.Slider",
            "androidx.compose.runtime.getValue",
            "androidx.compose.runtime.mutableIntStateOf",
            "androidx.compose.runtime.remember",
            "androidx.compose.runtime.setValue",
            "androidx.compose.ui.platform.LocalContext",
            "kotlin.math.roundToInt",
            "org.thoughtcrime.securesms.webrtc.audio.HqCallGainBridge",
        ],
    )

    old_hq_block = '''    if (displayHighQualityBluetoothToggle) {
      CallScreenMenuToggle(
        title = stringResource(R.string.CallOverflowPopupWindow__high_quality_bluetooth_audio),
        checked = isHighQualityBluetoothAudioEnabled,
        onCheckedChange = onHighQualityBluetoothAudioClick
      )
    }
    CallScreenMenuToggle(
      title = stringResource(R.string.CallOverflowPopupWindow__proximity_sensor),
      checked = isProximitySensorEnabled,
      onCheckedChange = onProximitySensorClick
    )
'''
    new_hq_block = '''    if (displayHighQualityBluetoothToggle) {
      CallScreenMenuToggle(
        title = stringResource(R.string.CallOverflowPopupWindow__high_quality_bluetooth_audio),
        checked = isHighQualityBluetoothAudioEnabled,
        onCheckedChange = onHighQualityBluetoothAudioClick
      )
      if (isHighQualityBluetoothAudioEnabled) {
        HqCallGainSlider()
      }
    }
    CallScreenMenuToggle(
      title = stringResource(R.string.CallOverflowPopupWindow__proximity_sensor),
      checked = isProximitySensorEnabled,
      onCheckedChange = onProximitySensorClick
    )
'''
    text = replace_once(text, old_hq_block, new_hq_block, "HQ/proximity menu block")

    marker = "@Composable\nprivate fun CallScreenMenuToggle(\n"
    slider = '''@Composable
private fun HqCallGainSlider() {
  val context = LocalContext.current
  var gainPercent by remember(context) {
    mutableIntStateOf(HqCallGainBridge.getSavedGainPercent(context))
  }

  Row(
    horizontalArrangement = spacedBy(12.dp),
    verticalAlignment = Alignment.CenterVertically,
    modifier = Modifier
      .fillMaxWidth()
      .padding(horizontal = 16.dp, vertical = 6.dp)
  ) {
    Slider(
      value = gainPercent.toFloat(),
      onValueChange = { value ->
        val snapped = ((value / 5f).roundToInt() * 5).coerceIn(0, 200)
        if (snapped != gainPercent) {
          gainPercent = snapped
          HqCallGainBridge.previewGainPercent(snapped)
        }
      },
      onValueChangeFinished = {
        HqCallGainBridge.saveGainPercent(context, gainPercent)
      },
      valueRange = 0f..200f,
      steps = 39,
      modifier = Modifier.weight(1f)
    )
    Text(
      text = "$gainPercent%",
      style = MaterialTheme.typography.bodyMedium,
      color = MaterialTheme.colorScheme.onSurface
    )
  }
}

@Composable
private fun CallScreenMenuToggle(
'''
    text = replace_once(text, marker, slider, "CallScreenMenuToggle insertion point")
    return text


def inject_hq_assignments(
    text: str,
    *,
    label: str,
    expected: dict[str, int],
) -> str:
    if "HqCallGainBridge.setHqEnabled" in text:
        die(f"{label} already appears to contain the gain experiment")

    out: list[str] = []
    counts = {key: 0 for key in expected}
    for line in text.splitlines():
        out.append(line)
        stripped = line.strip()
        match = re.fullmatch(r"hqBluetoothAudioEnabled\s*=\s*(enabled|true|false)", stripped)
        if match:
            value = match.group(1)
            if value not in expected:
                die(f"{label}: unexpected HQ assignment value {value!r}")
            indent = re.match(r"\s*", line).group(0)
            out.append(f"{indent}HqCallGainBridge.setHqEnabled(context, {value})")
            counts[value] += 1

    if counts != expected:
        die(f"{label}: unexpected HQ assignment shape; expected {expected}, found {counts}")
    return "\n".join(out) + "\n"


def patch_audio(text: str) -> str:
    if "hqBluetoothAudioEnabled" not in text:
        die("SignalAudioManager.kt is missing the final v9+ hqBluetoothAudioEnabled property")

    # Exact shape produced by the uploaded production 0001 patch:
    # base + legacy implementation each assign the incoming 'enabled' value.
    text = inject_hq_assignments(
        text,
        label="SignalAudioManager.kt",
        expected={"enabled": 2},
    )

    old_stop = "        is AudioManagerCommand.Stop -> stop(command.playDisconnect)\n"
    new_stop = '''        is AudioManagerCommand.Stop -> {
          HqCallGainBridge.setHqEnabled(context, false)
          stop(command.playDisconnect)
        }
'''
    text = replace_once(text, old_stop, new_stop, "AudioManagerCommand.Stop")

    old_shutdown = '''  fun shutdown() {
    handler.post {
'''
    new_shutdown = '''  fun shutdown() {
    HqCallGainBridge.setHqEnabled(context, false)
    handler.post {
'''
    text = replace_once(text, old_shutdown, new_shutdown, "SignalAudioManager.shutdown")
    return text


def patch_audio31(text: str) -> str:
    if "hqBluetoothAudioEnabled" not in text or "highQualityBluetoothDeviceId" not in text:
        die("FullSignalAudioManagerApi31.kt does not look like production patch 0001 was applied")

    # Exact shape produced by the uploaded production 0001 patch:
    # enable path = true; explicit disable + disappeared-device fallback = false twice.
    return inject_hq_assignments(
        text,
        label="FullSignalAudioManagerApi31.kt",
        expected={"true": 1, "false": 2},
    )


BRIDGE_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.webrtc.audio

import android.content.Context
import android.media.AudioTrack
import android.media.audiofx.LoudnessEnhancer
import org.signal.core.util.logging.Log
import kotlin.math.log10
import kotlin.math.roundToInt

/**
 * Process-local controller for the HQ Bluetooth receive gain experiment.
 *
 * There is deliberately no PCM processing loop here. WebRTC registers its Android AudioTrack
 * once at playout start. Slider/HQ-state changes update that track directly.
 */
object HqCallGainBridge {
  private val TAG = Log.tag(HqCallGainBridge::class.java)
  private const val PREFS_NAME = "hq_call_gain"
  private const val PREF_GAIN_PERCENT = "gain_percent"
  private const val DEFAULT_GAIN_PERCENT = 100
  private const val MIN_GAIN_PERCENT = 0
  private const val MAX_GAIN_PERCENT = 200

  private val lock = Any()

  private var hqEnabled = false
  private var desiredGainPercent = DEFAULT_GAIN_PERCENT
  private var currentTrack: AudioTrack? = null
  private var enhancer: LoudnessEnhancer? = null
  private var enhancerSessionId = -1
  private var failedEnhancerSessionId = -1

  @JvmStatic
  fun getSavedGainPercent(context: Context): Int {
    val stored = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
      .getInt(PREF_GAIN_PERCENT, DEFAULT_GAIN_PERCENT)
    return snap(stored)
  }

  @JvmStatic
  fun setHqEnabled(context: Context, enabled: Boolean) {
    synchronized(lock) {
      hqEnabled = enabled
      desiredGainPercent = if (enabled) getSavedGainPercent(context) else DEFAULT_GAIN_PERCENT
      applyGainLocked()
    }
  }

  @JvmStatic
  fun previewGainPercent(percent: Int) {
    synchronized(lock) {
      desiredGainPercent = snap(percent)
      if (hqEnabled) {
        applyGainLocked()
      }
    }
  }

  @JvmStatic
  fun saveGainPercent(context: Context, percent: Int) {
    val snapped = snap(percent)
    context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
      .edit()
      .putInt(PREF_GAIN_PERCENT, snapped)
      .apply()
    previewGainPercent(snapped)
  }

  /** Called by the tiny RingRTC/WebRTC bytecode hook immediately before AudioTrack.play(). */
  @JvmStatic
  fun registerAudioTrack(track: AudioTrack) {
    synchronized(lock) {
      if (currentTrack !== track) {
        resetCurrentTrackLocked()
        currentTrack = track
        failedEnhancerSessionId = -1
      }
      applyGainLocked()
    }
  }

  /** Called by the hook immediately before WebRTC stops that same AudioTrack. */
  @JvmStatic
  fun unregisterAudioTrack(track: AudioTrack) {
    synchronized(lock) {
      if (currentTrack === track) {
        resetCurrentTrackLocked()
        currentTrack = null
        failedEnhancerSessionId = -1
      }
    }
  }

  private fun applyGainLocked() {
    val track = currentTrack ?: return
    val percent = if (hqEnabled) desiredGainPercent else DEFAULT_GAIN_PERCENT
    val requestedLinearGain = percent / 100f

    if (requestedLinearGain <= 1f) {
      releaseEnhancerLocked()
      setTrackGain(track, requestedLinearGain)
      return
    }

    // Some Android implementations expose direct per-track gain above unity. Use that first.
    // Any remainder is handled by the session-scoped LoudnessEnhancer.
    val directMax = AudioTrack.getMaxVolume().coerceAtLeast(1f)
    val directGain = requestedLinearGain.coerceAtMost(directMax)
    setTrackGain(track, directGain)

    val remainingGain = requestedLinearGain / directGain
    if (remainingGain <= 1.0001f) {
      releaseEnhancerLocked()
      return
    }

    val effect = getOrCreateEnhancerLocked(track) ?: return
    val targetGainMb = (2000.0 * log10(remainingGain.toDouble()))
      .roundToInt()
      .coerceAtLeast(0)

    try {
      effect.setTargetGain(targetGainMb)
      effect.setEnabled(true)
    } catch (e: RuntimeException) {
      Log.w(TAG, "Unable to update LoudnessEnhancer for audio session ${track.audioSessionId}", e)
      releaseEnhancerLocked()
      failedEnhancerSessionId = track.audioSessionId
    }
  }

  private fun getOrCreateEnhancerLocked(track: AudioTrack): LoudnessEnhancer? {
    val sessionId = track.audioSessionId
    if (failedEnhancerSessionId == sessionId) {
      return null
    }
    if (enhancer != null && enhancerSessionId == sessionId) {
      return enhancer
    }

    releaseEnhancerLocked()
    return try {
      LoudnessEnhancer(sessionId).also {
        enhancer = it
        enhancerSessionId = sessionId
      }
    } catch (e: RuntimeException) {
      Log.w(TAG, "LoudnessEnhancer unavailable for audio session $sessionId", e)
      failedEnhancerSessionId = sessionId
      null
    }
  }

  private fun setTrackGain(track: AudioTrack, gain: Float) {
    val result = track.setVolume(gain)
    if (result < 0) {
      Log.w(TAG, "AudioTrack.setVolume($gain) returned $result")
    }
  }

  private fun resetCurrentTrackLocked() {
    releaseEnhancerLocked()
    currentTrack?.let { track ->
      try {
        track.setVolume(1f)
      } catch (e: RuntimeException) {
        Log.w(TAG, "Unable to restore AudioTrack unity gain", e)
      }
    }
  }

  private fun releaseEnhancerLocked() {
    enhancer?.let { effect ->
      try {
        effect.setEnabled(false)
      } catch (_: RuntimeException) {
      }
      try {
        effect.release()
      } catch (_: RuntimeException) {
      }
    }
    enhancer = null
    enhancerSessionId = -1
  }

  private fun snap(percent: Int): Int {
    val clamped = percent.coerceIn(MIN_GAIN_PERCENT, MAX_GAIN_PERCENT)
    return (((clamped + 2) / 5) * 5).coerceIn(MIN_GAIN_PERCENT, MAX_GAIN_PERCENT)
  }
}
'''

if BRIDGE.exists():
    die(f"bridge file already exists: {BRIDGE}")

# Validate every source transformation before writing anything. If any strict
# anchor changed upstream, this leaves the checkout untouched.
patched_popup = patch_popup(read(POPUP))
patched_audio = patch_audio(read(AUDIO))
patched_audio31 = patch_audio31(read(AUDIO31))

write(POPUP, patched_popup)
write(AUDIO, patched_audio)
write(AUDIO31, patched_audio31)
write(BRIDGE, BRIDGE_SOURCE)

print("0004-hq-call-gain: added 0-200% / 5% slider below HQ Bluetooth")
print("0004-hq-call-gain: wired HQ lifecycle to lightweight per-track gain controller")
print("0004-hq-call-gain: added HqCallGainBridge.kt (no PCM processing loop)")
