# Validation and audit record

## Evidence basis

Inputs were the attached RNNoise ZIP, prior chat export, patches, and helpers. The maintenance repository was read through its connected GitHub access:

- `punisherslife/Signal-Android_bluetooth`: `615cb47e92b3e3b7d4407d258fdb3becc30b8272`.
- Signal v8.26.4: `15e5d644924352fa03900969ad6de0e648e5e2d0`.
- RingRTC 2.71.0: `4c5fdb312d3c0d6b8e4091e4be5271c020f5792d`.
- WebRTC 7871f: `3a5cb5f6ea8d223a7b05e4e22ce3f9b77a740f8a`.
- RNNoise: `70f1d256acd4b34a572f999a05c87bf00b67730d`.
- Model archive SHA-256: `0a8755f8e2d834eff6a54714ecc7d75f9932e845df35f8b59bc52a7cfe6e8b37`.

The base patch/helper attachments matched the maintenance repository's Git blob IDs. The RNNoise ZIP's replacement `0005` was intentionally different. The missing validator was present in that repository and used as the compatibility baseline for its restored replacement.

Historical Actions results in the chat were treated as historical context, **not evidence that this revision builds or runs**. No new GitHub Actions run, repository commit, APK publication, or phone test was performed during this revision.

## Definite failures reproduced in the old archive

1. Applying `0001` through `0009` to actual Signal v8.26.4 files succeeded. `0010` then failed at `SignalAudioManager HQ-state getter: expected exactly one match, found 0`. Its anchor omitted the gain call inserted by `0004`. The revised anchor preserves that setter body.
2. The RNNoise GN patch expected `rtc_static_library("peerconnection_jni")`. Actual pinned WebRTC declares `rtc_library("peerconnection_jni")`. The revised patch targets that exact declaration and supplies the previously undeclared frame/header dependencies.
3. The archive's installer directly executed a non-guaranteed-executable helper, and the supposedly complete package omitted several base patches/tools. The replacement ships the actual files and uses explicit interpreters.
4. The ARM64 native option did not restrict Signal's four-ABI packaging. The new dependency installer rewrites both ABI filters and split inputs, and release selection verifies the APK's ABI inventory.

## Local checks completed

| Check | Result and scope |
|---|---|
| Ten-patch composition | Pass on actual fetched Signal v8.26.4 target files; all current revised patches applied in order. |
| Signal integration guards | Pass, including gain setter preservation, live-state restoration, camera controls, and RNNoise preference bridge. |
| Patch failures | Pass: already-patched refusal, missing-file preflight, and deliberate late `0010` source drift all preserve/restore source bytes. |
| WebRTC/RingRTC transforms | Pass on actual pinned Java/C++/GN/build-script files; repeated/changed shapes reject before applying an invalid transformation. Vendor model placeholders were used only for this patch-shape test. |
| Native wrapper | Compiled and executed with g++ and undefined-behavior/float-cast sanitizers. The **shipped processor header** is tested with small explicit WebRTC and RNNoise doubles. |
| Native cases | Bypass, first enable, repeated enable, rapid OFF/ON, reset after format/mute gaps, saturation/rounding, NaN/Inf, allocation/init failure, no wrapper malloc during processing, concurrent frames/toggles, and sink removal pass. |
| Gain bytecode | The actual patcher compiled and transformed a Java lifecycle fixture; JVM `-Xverify:all` execution verified play/stop/release and failed-play cleanup. Duplicate/missing/already-patched targets preserve the existing AAR on failure. |
| Packaging regressions | 14 offline tests pass: ABI filtering/ELF architecture, empty direct dependency list, dependency validation/version mismatch, checkpoint tampering/control mismatch, APK ABI mismatch, CI heap flags, architecture reconfiguration, and both canonical/little model-header naming conventions. |
| Workflow/scripts | YAML structure, all embedded Bash blocks, standalone Bash, and Python syntax checked. Four jobs and both release validation gates retained. |
| Installation | Test repository installation, backup restoration, and refusal to overwrite subsequent user edits checked with helper executable bits removed. |

## Not completed locally

- Full GN generation/linking of WebRTC/RingRTC with the actual RNNoise weights.
- Actual-model smoke/CPU diagnostics (the native job performs them after fetching the checksummed model).
- Signal Gradle CI, screenshot validation, Android compilation/R8, APK signing/alignment execution.
- RNNoise suppression quality, live toggle artifacts, native memory/battery use, JNI linkage, and device call stability.

This environment has neither the complete Android/native dependency checkout nor the downloaded weight archive/signing environment. Host doubles and source-shape tests do not replace those gates. The four-job workflow keeps those remaining checks explicit. APK-size, CPU, battery, or crash-rate improvements have not been measured.

## Design decisions retained

The old live-NS tools retain mutable factory/APM references and switch platform/software suppression during calls. They are not used by the revised RNNoise workflow. This is a design-risk reduction; without a crash trace it does not establish the cause of any previously reported crash.

The native wrapper retains synchronization because the pinned AudioFrameProcessor contract requires a thread-safe SetSink. Its callback runs under the same lock so unregistering the sink cannot race a call into a destroyed WebRTC consumer. This was checked against the pinned AsyncAudioProcessing implementation, whose sink posts a task rather than reentering the processor.

The RNNoise control uses one atomic word, avoiding a separate-enable/separate-reset-generation ordering window. The wrapper lazily initializes preallocated model storage, retains format/mute boundaries, and refuses non-finite output before touching the original samples. Java factory descriptors create a fresh native pointer at ownership transfer, avoiding reuse of one pointer across builder invocations.

The official little model is more sparse; “little” does not mean an order-of-magnitude smaller state or free computation. The stock processing chain remains to preserve bypass behavior, so real voice testing of combined suppression is still required.

## Primary source references

- [Pinned WebRTC AudioFrameProcessor contract](https://github.com/signalapp/webrtc/blob/3a5cb5f6ea8d223a7b05e4e22ce3f9b77a740f8a/api/audio/audio_frame_processor.h)
- [Pinned asynchronous processor lifetime](https://github.com/signalapp/webrtc/blob/3a5cb5f6ea8d223a7b05e4e22ce3f9b77a740f8a/modules/async_audio_processing/async_audio_processing.cc)
- [Pinned capture/stock-APM order](https://github.com/signalapp/webrtc/blob/3a5cb5f6ea8d223a7b05e4e22ce3f9b77a740f8a/audio/audio_transport_impl.cc)
- [Pinned RNNoise allocation/initialization](https://github.com/xiph/rnnoise/blob/70f1d256acd4b34a572f999a05c87bf00b67730d/src/denoise.c)
- [Pinned RNNoise vector dispatch](https://github.com/xiph/rnnoise/blob/70f1d256acd4b34a572f999a05c87bf00b67730d/src/vec.h)
- [Android zipalign: 16 KiB shared-library alignment](https://developer.android.com/tools/zipalign)

The full source/model pins and a SHA-256 manifest ship with this kit. Keep the native provenance artifact with test APKs when reporting build/device failures.
