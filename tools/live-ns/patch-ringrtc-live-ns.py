#!/usr/bin/env python3
"""Patch RingRTC Android CallManager with a live strong-NS controller.

Expected input: RingRTC v2.71.0 source root.

For this experimental build we deliberately force the Java ADM. That is the
only Android ADM in the pinned WebRTC stack whose platform NoiseSuppressor can
be toggled at runtime. The WebRTC source patch makes that toggle work both
before and during capture, and adds PeerConnectionFactory's verified live APM
software-NS setter.

Per factory we remember Signal's original suppression choice:
- stock hardware NS -> OFF = hardware on + software off
- stock software NS -> OFF = hardware off + software kHigh
ON is always hardware off + software kHigh.

The controller is persistent only at the Signal app layer; RingRTC itself keeps
an in-memory requested state and applies it to every factory created later.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CALL_MANAGER = ROOT / "src/android/api/org/signal/ringrtc/CallManager.java"


def die(message: str) -> None:
    raise RuntimeError(f"patch-ringrtc-live-ns: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


if not CALL_MANAGER.is_file():
    die(f"missing {CALL_MANAGER}")
text = CALL_MANAGER.read_text(encoding="utf-8")
if "setStrongNoiseSuppressionEnabled" in text or "FactoryAudioState" in text:
    die("CallManager.java already appears patched")

# This test variant always uses Java ADM so the platform NS effect has a real
# pre-capture + in-call control surface. Remove the now-unused Oboe import.
text = replace_once(
    text,
    "import org.webrtc.audio.OboeAudioDeviceModule;\n",
    "",
    "remove Oboe import",
)
text = replace_once(
    text,
    "import java.util.UUID;\n",
    "import java.util.UUID;\nimport java.util.WeakHashMap;\n",
    "WeakHashMap import",
)

old_fields = '''  @Nullable
  private PeerConnectionFactory               groupFactory;

  @NonNull
  private static String                       fieldTrials;
'''
new_fields = '''  @Nullable
  private PeerConnectionFactory               groupFactory;

  /**
   * Weak keys avoid extending a one-to-one CallContext/factory lifetime. The
   * value intentionally keeps the Java ADM wrapper alive so its AudioRecord
   * NoiseSuppressor can be toggled after adm.release() drops only our native ref.
   */
  @NonNull
  private final Map<PeerConnectionFactory, FactoryAudioState> factoryAudioStates = new WeakHashMap<>();

  private boolean strongNoiseSuppressionEnabled;

  @NonNull
  private static String                       fieldTrials;

  private static final class FactoryAudioState {
    @NonNull final AudioDeviceModule audioDeviceModule;
             final boolean           stockHardwareNoiseSuppressor;
             final boolean           stockSoftwareNoiseSuppressor;
             boolean                 strongNoiseSuppressionEnabled;

    FactoryAudioState(@NonNull AudioDeviceModule audioDeviceModule,
                      boolean stockHardwareNoiseSuppressor,
                      boolean stockSoftwareNoiseSuppressor) {
      this.audioDeviceModule = audioDeviceModule;
      this.stockHardwareNoiseSuppressor = stockHardwareNoiseSuppressor;
      this.stockSoftwareNoiseSuppressor = stockSoftwareNoiseSuppressor;
      this.strongNoiseSuppressionEnabled = false;
    }
  }
'''
text = replace_once(text, old_fields, new_fields, "CallManager live-NS fields")

old_adm = '''    AudioDeviceModule adm;

    if (audioConfig.useOboe) {
      // Use the Oboe Audio Device Module.
      adm = OboeAudioDeviceModule.builder()
        .setUseSoftwareAcousticEchoCanceler(audioConfig.useSoftwareAec)
        .setUseSoftwareNoiseSuppressor(audioConfig.useSoftwareNs)
        .setExclusiveSharingMode(true)
        .setInputLowLatency(audioConfig.useInputLowLatency)
        .setInputVoiceCommPreset(audioConfig.useInputVoiceComm)
        .createAudioDeviceModule();
    } else {
      // Use the Java Audio Device Module.
      adm = JavaAudioDeviceModule.builder(context)
        .setUseHardwareAcousticEchoCanceler(!audioConfig.useSoftwareAec)
        .setUseHardwareNoiseSuppressor(!audioConfig.useSoftwareNs)
        .createAudioDeviceModule();
    }

    PeerConnectionFactory factory = PeerConnectionFactory.builder()
            .setOptions(new PeerConnectionFactoryOptions())
            .setAudioDeviceModule(adm)
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .setFieldTrials(fieldTrials)
            .createPeerConnectionFactory();
    adm.release();
    return factory;
'''
new_adm = '''    // The live-NS experiment always uses Java ADM. Oboe's Android wrapper
    // deliberately does not implement setNoiseSuppressorEnabled(), so using it
    // would make a claimed live hardware/software handoff impossible.
    if (audioConfig.useOboe) {
      Log.w(TAG, "Live NS experiment: overriding useOboe=true with Java ADM");
    }

    final boolean stockHardwareNoiseSuppressor =
        !audioConfig.useSoftwareNs && JavaAudioDeviceModule.isBuiltInNoiseSuppressorSupported();
    final boolean stockSoftwareNoiseSuppressor = !stockHardwareNoiseSuppressor;

    AudioDeviceModule adm = JavaAudioDeviceModule.builder(context)
        .setUseHardwareAcousticEchoCanceler(!audioConfig.useSoftwareAec)
        .setUseHardwareNoiseSuppressor(!audioConfig.useSoftwareNs)
        .createAudioDeviceModule();

    PeerConnectionFactory factory = PeerConnectionFactory.builder()
            .setOptions(new PeerConnectionFactoryOptions())
            .setAudioDeviceModule(adm)
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .setFieldTrials(fieldTrials)
            .createPeerConnectionFactory();

    FactoryAudioState audioState = new FactoryAudioState(
        adm,
        stockHardwareNoiseSuppressor,
        stockSoftwareNoiseSuppressor);
    synchronized (this) {
      factoryAudioStates.put(factory, audioState);
      if (strongNoiseSuppressionEnabled &&
          !applyStrongNoiseSuppression(factory, audioState, true)) {
        Log.e(TAG, "Live NS experiment: failed to apply requested state to new factory; keeping stock processing");
      }
    }

    // The PeerConnectionFactory owns the native ADM ref. Keep the Java wrapper
    // in FactoryAudioState because its AudioRecord effect control remains useful.
    adm.release();
    return factory;
'''
text = replace_once(text, old_adm, new_adm, "CallManager ADM/factory construction")

# Add the controller immediately before checkCallManagerExists().
marker = '''  private void checkCallManagerExists() {
'''
controller = '''  /**
   * Requests the strong-NS state for existing and future Android factories.
   *
   * Returns false if an already-live factory cannot complete the transition;
   * any factories changed earlier in the same request are rolled back.
   */
  public synchronized boolean setStrongNoiseSuppressionEnabled(boolean enabled) {
    checkCallManagerExists();

    boolean previous = strongNoiseSuppressionEnabled;
    ArrayList<Map.Entry<PeerConnectionFactory, FactoryAudioState>> changed = new ArrayList<>();
    ArrayList<Map.Entry<PeerConnectionFactory, FactoryAudioState>> snapshot =
        new ArrayList<>(factoryAudioStates.entrySet());

    for (Map.Entry<PeerConnectionFactory, FactoryAudioState> entry : snapshot) {
      FactoryAudioState state = entry.getValue();
      if (state.strongNoiseSuppressionEnabled == enabled) {
        continue;
      }

      if (!applyStrongNoiseSuppression(entry.getKey(), state, enabled)) {
        Log.e(TAG, "Live NS experiment: transition failed; rolling back");
        for (int i = changed.size() - 1; i >= 0; i--) {
          Map.Entry<PeerConnectionFactory, FactoryAudioState> changedEntry = changed.get(i);
          if (!applyStrongNoiseSuppression(changedEntry.getKey(), changedEntry.getValue(), previous)) {
            Log.e(TAG, "Live NS experiment: rollback failed for a factory");
          }
        }
        return false;
      }
      changed.add(entry);
    }

    strongNoiseSuppressionEnabled = enabled;
    Log.i(TAG, "Live NS experiment: requested=" + enabled + ", factories=" + snapshot.size());
    return true;
  }

  /** Must be called while holding this CallManager monitor. */
  private boolean applyStrongNoiseSuppression(@NonNull PeerConnectionFactory factory,
                                               @NonNull FactoryAudioState state,
                                               boolean enabled) {
    if (state.strongNoiseSuppressionEnabled == enabled) {
      return true;
    }

    if (enabled) {
      if (state.stockHardwareNoiseSuppressor &&
          !state.audioDeviceModule.setNoiseSuppressorEnabled(false)) {
        Log.e(TAG, "Live NS experiment: failed to disable platform NoiseSuppressor");
        return false;
      }

      if (!factory.setSoftwareNoiseSuppressionEnabled(true)) {
        Log.e(TAG, "Live NS experiment: failed to enable verified WebRTC kHigh NS");
        if (state.stockHardwareNoiseSuppressor &&
            !state.audioDeviceModule.setNoiseSuppressorEnabled(true)) {
          Log.e(TAG, "Live NS experiment: failed to restore platform NoiseSuppressor after software failure");
        }
        return false;
      }

      state.strongNoiseSuppressionEnabled = true;
      return true;
    }

    // Restore the exact suppression family that this factory would have used
    // in unmodified Signal.
    if (!factory.setSoftwareNoiseSuppressionEnabled(state.stockSoftwareNoiseSuppressor)) {
      Log.e(TAG, "Live NS experiment: failed to restore stock WebRTC NS state");
      return false;
    }

    if (state.stockHardwareNoiseSuppressor &&
        !state.audioDeviceModule.setNoiseSuppressorEnabled(true)) {
      Log.e(TAG, "Live NS experiment: failed to restore platform NoiseSuppressor");
      // Avoid leaving the call with neither suppressor after a failed restore.
      factory.setSoftwareNoiseSuppressionEnabled(true);
      return false;
    }

    state.strongNoiseSuppressionEnabled = false;
    return true;
  }

  private void checkCallManagerExists() {
'''
text = replace_once(text, marker, controller, "live-NS controller insertion")

old_close = '''    ringrtcClose(nativeCallManager);
    nativeCallManager = 0;
'''
new_close = '''    ringrtcClose(nativeCallManager);
    synchronized (this) {
      factoryAudioStates.clear();
    }
    nativeCallManager = 0;
'''
text = replace_once(text, old_close, new_close, "CallManager close cleanup")

CALL_MANAGER.write_text(text, encoding="utf-8")
print("LIVE_NS_RINGRTC_PATCHED=1")
print("LIVE_NS_ADM=Java-for-test-guarantee")
print("LIVE_NS_OFF=restore-stock-family")
print("LIVE_NS_ON=platform-off+WebRTC-kHigh")
