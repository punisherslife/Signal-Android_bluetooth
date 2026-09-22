#!/usr/bin/env python3
"""Patch RingRTC Android to install/toggle WebRTC's RNNoise Little processor.

Expected input: RingRTC v2.71.0 source root (or the exact version resolved by
Signal, provided the strict anchors below are unchanged).

Design:
- preserve RingRTC's stock AudioConfig and ADM choice;
- install one native RNNoise AudioFrameProcessor in every PeerConnectionFactory;
- keep the existing Signal-facing method name setStrongNoiseSuppressionEnabled;
- toggling only flips WebRTC's native atomic bypass flag and returns immediately.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CALL_MANAGER = ROOT / "src/android/api/org/signal/ringrtc/CallManager.java"


def die(message: str) -> None:
    raise RuntimeError(f"patch-ringrtc-rnnoise: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


if not CALL_MANAGER.is_file():
    die(f"missing {CALL_MANAGER}")
text = CALL_MANAGER.read_text(encoding="utf-8")

if "setRnnoiseAudioFrameProcessorEnabled" in text or "createRnnoiseAudioFrameProcessor" in text:
    die("CallManager.java already appears RNNoise-patched")
if "setStrongNoiseSuppressionEnabled" in text:
    die("CallManager.java contains the old/custom strong-NS controller; start from clean RingRTC")

old_builder = '''            .setVideoDecoderFactory(decoderFactory)
            .setFieldTrials(fieldTrials)
            .createPeerConnectionFactory();
'''
new_builder = '''            .setVideoDecoderFactory(decoderFactory)
            .setFieldTrials(fieldTrials)
            .setAudioFrameProcessor(PeerConnectionFactory.createRnnoiseAudioFrameProcessor())
            .createPeerConnectionFactory();
'''
text = replace_once(text, old_builder, new_builder, "PeerConnectionFactory RNNoise processor")

marker = '''  private void checkCallManagerExists() {
'''
controller = '''  /**
   * Enables/disables the lightweight RNNoise Little capture processor.
   *
   * The processor is already installed in each factory. This changes only a
   * process-local atomic bypass flag in WebRTC; no ADM/APM/factory is rebuilt.
   */
  public synchronized boolean setStrongNoiseSuppressionEnabled(boolean enabled) {
    checkCallManagerExists();
    PeerConnectionFactory.setRnnoiseAudioFrameProcessorEnabled(enabled);
    Log.i(TAG, "RNNoise Little enabled=" + enabled);
    return true;
  }

  private void checkCallManagerExists() {
'''
text = replace_once(text, marker, controller, "RNNoise toggle controller insertion")

CALL_MANAGER.write_text(text, encoding="utf-8")
print("RNNOISE_RINGRTC_PATCHED=1")
print("RNNOISE_RINGRTC_STOCK_ADM=preserved")
print("RNNOISE_RINGRTC_TOGGLE=atomic-bypass-only")
