#!/usr/bin/env python3
"""Install RNNoise into the verified WebRTC 7871f Android source layout.

Strict transformations are computed before writes. The native processor lives
in a separate header so the exact shipped implementation can be host-tested.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

C_SOURCES = ('celt_lpc.c', 'denoise.c', 'kiss_fft.c', 'nnet.c', 'nnet_default.c',
             'parse_lpcnet_weights.c', 'pitch.c', 'rnn.c', 'rnnoise_data.c',
             'rnnoise_tables.c')
HEADER = 'sdk/android/src/jni/pc/rnnoise_audio_frame_processor.h'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise ValueError(f'{label}: expected one match, found {count}')
    return text.replace(old, new, 1)


def patch_neon(text):
    # Baseline ARM64 supports NEON but need not define the optional dot-product
    # macro. Preserve upstream's fallback without disabling -Wundef or forcing
    # newer CPU instructions on devices that do not support them.
    return replace_once(text, '#if __ARM_FEATURE_DOTPROD\n',
        '#if defined(__ARM_FEATURE_DOTPROD) && __ARM_FEATURE_DOTPROD\n',
        'RNNoise NEON dot-product feature guard')


def patch_java(text):
    if 'setAudioFrameProcessor(AudioFrameProcessor audioFrameProcessor)' not in text:
        raise ValueError('WebRTC lacks the AudioFrameProcessor builder API')
    if 'createRnnoiseAudioFrameProcessor' in text:
        raise ValueError('WebRTC is already RNNoise-patched; use a clean checkout')
    # Allocate at native ownership transfer, not when configuring the builder.
    # Each builder reuse gets a fresh pointer; exceptions before transfer cannot
    # leak an eagerly allocated processor or reuse an already-owned pointer.
    methods = '''  /** Creates a descriptor that supplies one fresh native processor per factory. */
  public static AudioFrameProcessor createRnnoiseAudioFrameProcessor() {
    return PeerConnectionFactory::nativeCreateRnnoiseAudioFrameProcessor;
  }

  /** Changes only the native bypass flag; the call's audio graph stays intact. */
  public static void setRnnoiseAudioFrameProcessorEnabled(boolean enabled) {
    nativeSetRnnoiseAudioFrameProcessorEnabled(enabled);
  }

'''
    text = replace_once(text, '  public void dispose() {\n', methods + '  public void dispose() {\n', 'Java API')
    anchor = '  private static native void nativeFreeFactory(long factory);'
    return replace_once(text, anchor,
        '  private static native long nativeCreateRnnoiseAudioFrameProcessor();\n'
        '  private static native void nativeSetRnnoiseAudioFrameProcessorEnabled(boolean enabled);\n' + anchor,
        'JNI declarations')


def patch_cc(text):
    if 'TakeOwnershipOfUniquePtr<AudioFrameProcessor>' not in text:
        raise ValueError('WebRTC lacks unique native AudioFrameProcessor ownership')
    text = replace_once(text, '#include "api/audio/audio_frame_processor.h"\n',
        '#include "api/audio/audio_frame_processor.h"\n'
        '#include "sdk/android/src/jni/pc/rnnoise_audio_frame_processor.h"\n', 'C++ include')
    anchor = 'static void JNI_PeerConnectionFactory_FreeFactory(JNIEnv*, jlong j_p) {'
    methods = '''static jlong JNI_PeerConnectionFactory_CreateRnnoiseAudioFrameProcessor(JNIEnv*) {
  return reinterpret_cast<jlong>(new RnnoiseAudioFrameProcessor());
}

static void JNI_PeerConnectionFactory_SetRnnoiseAudioFrameProcessorEnabled(
    JNIEnv*, jboolean enabled) {
  SetRnnoiseEnabled(static_cast<bool>(enabled));
}

'''
    return replace_once(text, anchor, methods + anchor, 'JNI definitions')


def patch_build(text, vendor):
    # The actual pinned target is rtc_library, not rtc_static_library.
    marker = '  rtc_library("peerconnection_jni") {'
    if text.count(marker) != 1 or 'rtc_library("rnnoise_little")' in text:
        raise ValueError('Unexpected or already patched peerconnection_jni GN target')
    start = text.index(marker)
    # Only edit within this target, preserving its surrounding Android guard.
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise ValueError('Unclosed peerconnection_jni target')
    block = text[start:end]
    block = replace_once(block, '    sources = [\n',
        '    sources = [\n      "src/jni/pc/rnnoise_audio_frame_processor.h",\n', 'processor source')
    block = replace_once(block, '    deps = [\n',
        '    deps = [\n      ":rnnoise_little",\n      "../../api/audio:audio_frame_api",\n', 'processor dependencies')
    files = ['src/' + name for name in C_SOURCES]
    files += sorted(p.relative_to(vendor).as_posix() for p in vendor.rglob('*.h'))
    sources = ''.join(f'      "../../third_party/rnnoise_little/{p}",\n' for p in files)
    target = '''  # Pinned upstream RNNoise, statically linked; no model-loading service.
  rtc_library("rnnoise_little") {
    visibility = [ ":peerconnection_jni" ]
    sources = [
''' + sources + '''    ]
    include_dirs = [
      "../../third_party/rnnoise_little/include",
      "../../third_party/rnnoise_little/src",
    ]
    # Hide the statically linked C API; keep unused loader/demo code removable.
    defines = [ "RNNOISE_BUILD", "RNNOISE_EXPORT=", "DISABLE_DEBUG_FLOAT" ]
    suppressed_configs += [ "//build/config/compiler:chromium_code" ]
    configs += [ "//build/config/compiler:no_chromium_code" ]
  }

'''
    return text[:start] + target + block + text[end:]


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: patch-webrtc-rnnoise.py <webrtc-source-root>')
    root = Path(sys.argv[1]).resolve()
    vendor = root / 'third_party/rnnoise_little'
    required = ['include/rnnoise.h', 'src/rnnoise_data.h', 'src/vec_neon.h', 'COPYING'] + ['src/' + p for p in C_SOURCES]
    for name in required:
        if not (vendor / name).is_file():
            raise ValueError(f'Missing RNNoise vendor file: {name}; fetch the pinned model first')
    if not (root / 'sdk/android/api/org/webrtc/AudioFrameProcessor.java').is_file():
        raise ValueError('Missing WebRTC AudioFrameProcessor Java API')
    header = root / HEADER
    if header.exists():
        raise ValueError('Native processor already exists; use a clean checkout')
    java = root / 'sdk/android/api/org/webrtc/PeerConnectionFactory.java'
    cc = root / 'sdk/android/src/jni/pc/peer_connection_factory.cc'
    build = root / 'sdk/android/BUILD.gn'
    neon = vendor / 'src/vec_neon.h'
    writes = [(java, patch_java(java.read_text())), (cc, patch_cc(cc.read_text())),
              (build, patch_build(build.read_text(), vendor)),
              (neon, patch_neon(neon.read_text())),
              (header, Path(__file__).with_name('rnnoise_audio_frame_processor.h').read_text())]
    for path, content in writes:
        path.write_text(content, encoding='utf-8')
    print('RNNOISE_WEBRTC_PATCHED=1; native 48kHz/mono/480; one lock; no frame allocations in wrapper')


if __name__ == '__main__':
    main()
