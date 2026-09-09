#!/usr/bin/env python3
"""Patch Signal's pinned WebRTC checkout with a live software-NS control.

Expected input is the WebRTC source root synced by RingRTC v2.71.0 (7871f).
Changes are deliberately narrow:
- PeerConnectionFactory.java exposes setSoftwareNoiseSuppressionEnabled().
- its JNI owner retains the actual AudioProcessing instance used by the factory.
- JNI toggles the running APM NS flag and fixes the level to kHigh, then reads
  the config back and reports success only if the requested state stuck.
- WebRtcAudioRecord.setNoiseSuppressorEnabled() works both before capture starts
  (set the desired platform effect state) and while capture is active (toggle
  the already-attached Android NoiseSuppressor).

No audio samples are intercepted or copied by this patch.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
PCF_JAVA = ROOT / "sdk/android/api/org/webrtc/PeerConnectionFactory.java"
AUDIO_RECORD = ROOT / "sdk/android/src/java/org/webrtc/audio/WebRtcAudioRecord.java"
OWNER_H = ROOT / "sdk/android/src/jni/pc/owned_factory_and_threads.h"
OWNER_CC = ROOT / "sdk/android/src/jni/pc/owned_factory_and_threads.cc"
PCF_CC = ROOT / "sdk/android/src/jni/pc/peer_connection_factory.cc"


def die(message: str) -> None:
    raise RuntimeError(f"patch-webrtc-live-ns: {message}")


def read(path: Path) -> str:
    if not path.is_file():
        die(f"missing expected WebRTC file: {path}")
    return path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_pcf_java(text: str) -> str:
    if "setSoftwareNoiseSuppressionEnabled" in text:
        die("PeerConnectionFactory.java already patched")

    old = '''  public void dispose() {
    checkPeerConnectionFactoryExists();
    nativeFreeFactory(nativeFactory);
'''
    new = '''  /**
   * Enables/disables WebRTC's running software noise suppressor.
   *
   * The native side applies the change to the AudioProcessing instance owned by
   * this factory and verifies the resulting config. When enabled, the level is
   * fixed to WebRTC's kHigh setting.
   */
  public boolean setSoftwareNoiseSuppressionEnabled(boolean enabled) {
    checkPeerConnectionFactoryExists();
    return nativeSetSoftwareNoiseSuppressionEnabled(nativeFactory, enabled);
  }

  public void dispose() {
    checkPeerConnectionFactoryExists();
    nativeFreeFactory(nativeFactory);
'''
    text = replace_once(text, old, new, "PeerConnectionFactory public API")

    old_native = '''  private static native void nativeStopAecDump(long factory);
  private static native void nativeFreeFactory(long factory);
'''
    new_native = '''  private static native void nativeStopAecDump(long factory);
  private static native boolean nativeSetSoftwareNoiseSuppressionEnabled(
      long factory, boolean enabled);
  private static native void nativeFreeFactory(long factory);
'''
    return replace_once(text, old_native, new_native, "PeerConnectionFactory native declaration")


def patch_audio_record(text: str) -> str:
    old = '''  public boolean setNoiseSuppressorEnabled(boolean enabled) {
    if (!WebRtcAudioEffects.isNoiseSuppressorSupported()) {
      Logging.e(TAG, "Noise suppressor is not supported.");
      return false;
    }
    Logging.w(TAG, "SetNoiseSuppressorEnabled(" + enabled + ")");
    return effects.toggleNS(enabled);
  }
'''
    new = '''  public boolean setNoiseSuppressorEnabled(boolean enabled) {
    if (!WebRtcAudioEffects.isNoiseSuppressorSupported()) {
      Logging.e(TAG, "Noise suppressor is not supported.");
      return false;
    }
    Logging.w(TAG, "SetNoiseSuppressorEnabled(" + enabled + ")");
    if (audioRecord == null) {
      // Before capture starts there is no attached NoiseSuppressor instance yet.
      // Set the desired state so enable(audioSession) creates it correctly.
      return effects.setNS(enabled);
    }
    // During an active capture session, toggle the already-attached effect live.
    return effects.toggleNS(enabled);
  }
'''
    return replace_once(text, old, new, "WebRtcAudioRecord platform NS setter")


def patch_owner_h(text: str) -> str:
    if "audio_processing()" in text or "audio_processing_" in text:
        die("owned_factory_and_threads.h already patched")

    text = replace_once(
        text,
        '#include "api/environment/environment.h"\n',
        '#include "api/audio/audio_processing.h"\n#include "api/environment/environment.h"\n',
        "owner header AudioProcessing include",
    )

    old_ctor = '''      std::unique_ptr<Thread> signaling_thread,
      const Environment& env,
      const scoped_refptr<PeerConnectionFactoryInterface>& factory);
'''
    new_ctor = '''      std::unique_ptr<Thread> signaling_thread,
      const Environment& env,
      const scoped_refptr<PeerConnectionFactoryInterface>& factory,
      const scoped_refptr<AudioProcessing>& audio_processing);
'''
    text = replace_once(text, old_ctor, new_ctor, "owner primary constructor")

    old_getters = '''  PeerConnectionFactoryInterface* factory() { return factory_.get(); }
  SocketFactory* socket_factory() { return socket_factory_.get(); }
'''
    new_getters = '''  PeerConnectionFactoryInterface* factory() { return factory_.get(); }
  AudioProcessing* audio_processing() { return audio_processing_.get(); }
  SocketFactory* socket_factory() { return socket_factory_.get(); }
'''
    text = replace_once(text, old_getters, new_getters, "owner getter")

    old_member = '''  const std::optional<Environment> env_;
  const scoped_refptr<PeerConnectionFactoryInterface> factory_;
'''
    new_member = '''  const std::optional<Environment> env_;
  const scoped_refptr<PeerConnectionFactoryInterface> factory_;
  const scoped_refptr<AudioProcessing> audio_processing_;
'''
    return replace_once(text, old_member, new_member, "owner APM member")


def patch_owner_cc(text: str) -> str:
    if "audio_processing_(" in text:
        die("owned_factory_and_threads.cc already patched")

    text = replace_once(
        text,
        '#include "api/environment/environment.h"\n',
        '#include "api/audio/audio_processing.h"\n#include "api/environment/environment.h"\n',
        "owner cc AudioProcessing include",
    )

    old_primary = '''    std::unique_ptr<Thread> signaling_thread,
    const Environment& env,
    const scoped_refptr<PeerConnectionFactoryInterface>& factory)
    : socket_factory_(std::move(socket_factory)),
      network_thread_(std::move(network_thread)),
      worker_thread_(std::move(worker_thread)),
      signaling_thread_(std::move(signaling_thread)),
      env_(env),
      factory_(factory) {}
'''
    new_primary = '''    std::unique_ptr<Thread> signaling_thread,
    const Environment& env,
    const scoped_refptr<PeerConnectionFactoryInterface>& factory,
    const scoped_refptr<AudioProcessing>& audio_processing)
    : socket_factory_(std::move(socket_factory)),
      network_thread_(std::move(network_thread)),
      worker_thread_(std::move(worker_thread)),
      signaling_thread_(std::move(signaling_thread)),
      env_(env),
      factory_(factory),
      audio_processing_(audio_processing) {}
'''
    text = replace_once(text, old_primary, new_primary, "owner primary implementation")

    old_deprecated = '''      signaling_thread_(std::move(signaling_thread)),
      env_(std::nullopt),
      factory_(factory) {}
'''
    new_deprecated = '''      signaling_thread_(std::move(signaling_thread)),
      env_(std::nullopt),
      factory_(factory),
      audio_processing_(nullptr) {}
'''
    return replace_once(text, old_deprecated, new_deprecated, "owner deprecated implementation")


def patch_pcf_cc(text: str) -> str:
    if "SetSoftwareNoiseSuppressionEnabled" in text:
        die("peer_connection_factory.cc already patched")

    old_scoped_sig = '''    std::unique_ptr<Thread> worker_thread,
    std::unique_ptr<Thread> signaling_thread,
    const Environment& webrtc_env) {
  OwnedFactoryAndThreads* owned_factory = new OwnedFactoryAndThreads(
      std::move(socket_factory), std::move(network_thread),
      std::move(worker_thread), std::move(signaling_thread), webrtc_env, pcf);
'''
    new_scoped_sig = '''    std::unique_ptr<Thread> worker_thread,
    std::unique_ptr<Thread> signaling_thread,
    const Environment& webrtc_env,
    const scoped_refptr<AudioProcessing>& audio_processing) {
  OwnedFactoryAndThreads* owned_factory = new OwnedFactoryAndThreads(
      std::move(socket_factory), std::move(network_thread),
      std::move(worker_thread), std::move(signaling_thread), webrtc_env, pcf,
      audio_processing);
'''
    text = replace_once(text, old_scoped_sig, new_scoped_sig, "NativeToScoped signature")

    old_public_wrapper = '''  return NativeToScopedJavaPeerConnectionFactory(
             jni, pcf, std::move(socket_factory), std::move(network_thread),
             std::move(worker_thread), std::move(signaling_thread), env)
      .Release();
'''
    new_public_wrapper = '''  return NativeToScopedJavaPeerConnectionFactory(
             jni, pcf, std::move(socket_factory), std::move(network_thread),
             std::move(worker_thread), std::move(signaling_thread), env,
             nullptr)
      .Release();
'''
    text = replace_once(text, old_public_wrapper, new_public_wrapper, "NativeToJava wrapper")

    old_builder = '''  dependencies.audio_frame_processor = std::move(audio_frame_processor);
  if (audio_processor != nullptr) {
    dependencies.audio_processing_builder =
        CustomAudioProcessing(std::move(audio_processor));
#ifndef WEBRTC_EXCLUDE_AUDIO_PROCESSING_MODULE
  } else {
    dependencies.audio_processing_builder =
        std::make_unique<BuiltinAudioProcessingBuilder>();
#endif
  }
  dependencies.video_encoder_factory =
'''
    new_builder = '''  dependencies.audio_frame_processor = std::move(audio_frame_processor);
#ifndef WEBRTC_EXCLUDE_AUDIO_PROCESSING_MODULE
  if (audio_processor == nullptr) {
    // Build the normal WebRTC APM explicitly so the Java factory owner can keep
    // a safe reference for live configuration changes after factory creation.
    BuiltinAudioProcessingBuilder builder;
    audio_processor = builder.Build(env);
    RTC_CHECK(audio_processor) << "Failed to create AudioProcessing";
  }
#endif
  scoped_refptr<AudioProcessing> retained_audio_processor = audio_processor;
  if (audio_processor != nullptr) {
    dependencies.audio_processing_builder =
        CustomAudioProcessing(std::move(audio_processor));
  }
  dependencies.video_encoder_factory =
'''
    text = replace_once(text, old_builder, new_builder, "explicit retained APM builder")

    old_return = '''  return NativeToScopedJavaPeerConnectionFactory(
      jni, factory, std::move(socket_server), std::move(network_thread),
      std::move(worker_thread), std::move(signaling_thread), env);
}
'''
    new_return = '''  return NativeToScopedJavaPeerConnectionFactory(
      jni, factory, std::move(socket_server), std::move(network_thread),
      std::move(worker_thread), std::move(signaling_thread), env,
      retained_audio_processor);
}
'''
    text = replace_once(text, old_return, new_return, "factory return with retained APM")

    marker = '''static void JNI_PeerConnectionFactory_FreeFactory(JNIEnv*, jlong j_p) {
'''
    setter = '''static jboolean JNI_PeerConnectionFactory_SetSoftwareNoiseSuppressionEnabled(
    JNIEnv*,
    jlong j_p,
    jboolean enabled) {
  auto* owner = reinterpret_cast<OwnedFactoryAndThreads*>(j_p);
  AudioProcessing* audio_processing = owner->audio_processing();
  if (audio_processing == nullptr) {
    RTC_LOG(LS_ERROR) << "Live NS: PeerConnectionFactory has no AudioProcessing instance";
    return false;
  }

  AudioProcessing::Config config = audio_processing->GetConfig();
  config.noise_suppression.enabled = enabled;
  config.noise_suppression.level =
      AudioProcessing::Config::NoiseSuppression::Level::kHigh;
  audio_processing->ApplyConfig(config);

  const AudioProcessing::Config applied = audio_processing->GetConfig();
  const bool verified =
      applied.noise_suppression.enabled == static_cast<bool>(enabled) &&
      (!enabled ||
       applied.noise_suppression.level ==
           AudioProcessing::Config::NoiseSuppression::Level::kHigh);
  RTC_LOG(LS_INFO) << "Live NS: software=" << static_cast<bool>(enabled)
                   << ", verified=" << verified;
  return verified;
}

static void JNI_PeerConnectionFactory_FreeFactory(JNIEnv*, jlong j_p) {
'''
    return replace_once(text, marker, setter, "native live-NS setter insertion")


originals = {
    PCF_JAVA: read(PCF_JAVA),
    AUDIO_RECORD: read(AUDIO_RECORD),
    OWNER_H: read(OWNER_H),
    OWNER_CC: read(OWNER_CC),
    PCF_CC: read(PCF_CC),
}
patched = {
    PCF_JAVA: patch_pcf_java(originals[PCF_JAVA]),
    AUDIO_RECORD: patch_audio_record(originals[AUDIO_RECORD]),
    OWNER_H: patch_owner_h(originals[OWNER_H]),
    OWNER_CC: patch_owner_cc(originals[OWNER_CC]),
    PCF_CC: patch_pcf_cc(originals[PCF_CC]),
}

# Only write after every strict anchor has validated.
for path, text in patched.items():
    path.write_text(text, encoding="utf-8")

print("LIVE_NS_WEBRTC_PATCHED=1")
print("LIVE_NS_SOFTWARE_LEVEL=kHigh")
print("LIVE_NS_PLATFORM_TOGGLE=pre-capture-and-live")
print("LIVE_NS_APM_SETTER=ApplyConfig+readback-verification")
