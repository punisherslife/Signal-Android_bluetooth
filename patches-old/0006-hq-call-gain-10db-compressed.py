#!/usr/bin/env python3
"""Retune the existing HQ call-gain slider so 200% means +10 dB.

Layering:
  0001-hq-bluetooth.py
  0002-proximity-toggle.py
  0003-video-phone-speaker.py
  0004-hq-call-gain.py
  0005-strong-noise-suppression.py
  0006-hq-call-gain-10db-compressed.py  (this file)

Runtime design stays deliberately light:
- no PCM/sample processing loop
- no new native code or DSP library
- <=100% keeps AudioTrack's per-track attenuation
- >100% keeps AudioTrack at unity and uses Android's session-scoped
  LoudnessEnhancer only on Signal/WebRTC call playout
- 100..200% maps linearly to 0..+10 dB (5% slider step = 0.5 dB)
- LoudnessEnhancer compresses samples that would exceed the platform sample range,
  avoiding simple hard sample clipping from a raw >1.0 multiplier

The patch replaces only HqCallGainBridge.kt, which is our own file from 0004.
It aborts if the expected 0004 bridge shape is not present.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
BRIDGE = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt"


def die(message: str) -> None:
    raise RuntimeError(f"0006-hq-call-gain-10db-compressed: {message}")


if not BRIDGE.exists():
    die(f"missing expected 0004 bridge: {BRIDGE}")

old = BRIDGE.read_text(encoding="utf-8")
required_markers = [
    "object HqCallGainBridge",
    'private const val PREFS_NAME = "hq_call_gain"',
    "private const val MAX_GAIN_PERCENT = 200",
    "private var enhancer: LoudnessEnhancer? = null",
    "val requestedLinearGain = percent / 100f",
    "2000.0 * log10(remainingGain.toDouble())",
    "fun registerAudioTrack(track: AudioTrack)",
    "fun unregisterAudioTrack(track: AudioTrack)",
]
for marker in required_markers:
    if marker not in old:
        die(f"HqCallGainBridge.kt is not the expected 0004 shape; missing {marker!r}")

if "MAX_BOOST_DB" in old or "gainAboveUnityDb" in old:
    die("HqCallGainBridge.kt already appears to contain patch 0006")

BRIDGE_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.webrtc.audio

import android.content.Context
import android.media.AudioTrack
import android.media.audiofx.LoudnessEnhancer
import org.signal.core.util.logging.Log

/**
 * Process-local controller for the HQ Bluetooth receive-gain experiment.
 *
 * There is deliberately no PCM processing loop here. WebRTC registers its Android AudioTrack
 * once at playout start. Slider/HQ-state changes update that track/session only.
 *
 * Slider mapping:
 * - 0..100%: AudioTrack attenuation from silence to unity
 * - 100..200%: 0..+10 dB session gain through LoudnessEnhancer
 *
 * Android documents LoudnessEnhancer as compressing amplified samples that would otherwise
 * exceed the platform sample range. The AudioTrack itself is therefore kept at unity above
 * 100%, instead of applying a raw >1.0 track multiplier before the effect.
 */
object HqCallGainBridge {
  private val TAG = Log.tag(HqCallGainBridge::class.java)
  private const val PREFS_NAME = "hq_call_gain"
  private const val PREF_GAIN_PERCENT = "gain_percent"
  private const val DEFAULT_GAIN_PERCENT = 100
  private const val MIN_GAIN_PERCENT = 0
  private const val MAX_GAIN_PERCENT = 200
  private const val MAX_BOOST_DB = 10f
  private const val MILLIBELS_PER_DB = 100f

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

    if (percent <= DEFAULT_GAIN_PERCENT) {
      releaseEnhancerLocked()
      setTrackGain(track, percent / 100f)
      return
    }

    // Keep the raw AudioTrack at unity above 100%. The session effect handles the boost
    // and compresses samples that would otherwise exceed the supported sample range.
    setTrackGain(track, 1f)

    val gainAboveUnityDb = ((percent - DEFAULT_GAIN_PERCENT) / 100f) * MAX_BOOST_DB
    val targetGainMb = (gainAboveUnityDb * MILLIBELS_PER_DB).toInt()
      .coerceIn(0, (MAX_BOOST_DB * MILLIBELS_PER_DB).toInt())

    val effect = getOrCreateEnhancerLocked(track) ?: return
    try {
      effect.setTargetGain(targetGainMb)
      val result = effect.setEnabled(true)
      if (result < 0) {
        Log.w(TAG, "LoudnessEnhancer.setEnabled(true) returned $result")
      }
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
    val result = track.setVolume(gain.coerceIn(0f, 1f))
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

BRIDGE.write_text(BRIDGE_SOURCE, encoding="utf-8")
print("0006-hq-call-gain-10db-compressed: kept slider 0-200% / 5%")
print("0006-hq-call-gain-10db-compressed: remapped 100-200% to 0..+10 dB")
print("0006-hq-call-gain-10db-compressed: uses session LoudnessEnhancer compression; no PCM loop")
