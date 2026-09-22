# Signal RNNoise Little — complete revised kit

This is a self-contained **source/build kit**, including all ten patches, HQ gain tools, RNNoise integration, the missing shape validator, tests, and one manual four-job workflow. It targets **Signal v8.26.4 / RingRTC 2.71.0 / WebRTC 7871f** at exact commits in `tools/rnnoise/versions.json`.

**Status:** actual-source patch tests and host regression tests pass. The revised Android native build, full Signal CI/R8 build, and phone behavior have **not** been run here. Do not treat this archive as a device-proven release. Read `VALIDATION.md` for evidence and remaining checks.

## Install and run

Use a test branch of your maintenance repository first. Its existing scheduled release workflows use the old native stack; the RNNoise workflow is the one intended for these replacement patches.

```bash
# In your maintenance repository:
git switch -c rnnoise-little-test

# From this extracted kit (Python 3.11+, Bash, Git):
bash install.sh /path/to/Signal-Android_bluetooth
```

The installer verifies checksums, copies the complete maintenance files, and backs up every overwritten file. It prints a rollback command. It does not commit, push, modify checked-out Signal application source, or start a build. No executable-file bits are required for kit helpers.

Review and commit the installed changes, then push your test branch. GitHub normally needs a manually dispatched workflow to exist on the default branch before it appears in the Actions UI. If this workflow is new, add its reviewed workflow file to the default branch, then select your test branch in **Run workflow**. Keep its helper/patch changes on the test branch until the test build succeeds.

Run **“HQ gain 10 dB + RNNoise Little — validated source kit”**:

- `upstream_tag`: `v8.26.4` (strictly checked; no drifting “latest”).
- `native_archs`: `arm64` for a smaller ARM64 phone build; `all` for four Android ABIs.
- Existing secrets: `FORK_KEYSTORE_B64`, `FORK_KEYSTORE_PASSWORD`, `FORK_KEY_ALIAS`, and `FORK_KEY_PASSWORD` for non-PKCS12 keys.

The four jobs remain: native AAR → separate Signal CI and screenshot jobs → release/signing after both pass. The native checkpoint uploads before either validation job starts. Use **Re-run failed jobs** while the 14-day artifact still exists to reuse a successful native job. A rerun of the whole workflow rebuilds native code.

The workflow only uploads test artifacts. It does not publish a GitHub Release, move tags, or update a stable branch. Runner shutdowns cannot be eliminated; job separation and the checkpoint limit lost work.

## What changed

| Area | Revision |
|---|---|
| Completeness | All `0001`–`0010` patches and tools are included; no bootstrap download of missing maintenance files. |
| Missing validator | Restored `tools/optimized-kit/validate-signal-shape.sh`, with diagnostic Python checks and a `--rnnoise` mode. |
| UI patch compatibility | Fixed `0010`'s stale anchor that failed after `0004`; retained live toggle restoration and stock camera controls. |
| RNNoise build | Fixed the nonexistent GN target match; declared native headers and direct audio-frame dependency correctly. |
| Native ownership | Allocate each processor when its pointer transfers to a factory, avoiding leaked/reused pointers from an eager Java wrapper. |
| Native processing | One coherent atomic control word, one mutex per frame, fixed 480-float scratch, no wrapper frame allocations/JNI calls, reset after bypass/mute/format gaps. |
| Failure behavior | Preserve muted frames and original audio on invalid DSP output, state allocation failure, or initialization failure. |
| Gain | Keep session-based +10 dB gain with no PCM loop; skip repeated slider values, handle AudioTrack exceptions, release on failed play, reject duplicate bytecode hooks. |
| APK architecture | ARM64 builds restrict Signal's ABI filters/splits and verify packaged native libraries, preventing unsupported-ABI APKs. |
| CI overhead | Shared source setup replaces four copies of workflow logic; bound Java heaps/native build concurrency; avoid recompressing AAR/APK artifacts. |
| Reproducibility | Checkpoint checksums cover AAR and metadata; source pins and patch/tool hashes must match across jobs. |
| Recovery | Missing patches are caught before edits; normal patch failures restore touched source files; installation has backups and guarded rollback. |

Base Bluetooth routing, proximity behavior, video handset/speaker selection, PiP self-preview settings, 1:1 swap, and the 0–200% gain slider are retained. Patches `0001`, `0002`, `0003`, `0004`, `0007`, `0008`, and `0009` are byte-identical to your attachments/repository. `0005`, `0006`, and `0010` carry the targeted changes.

## Runtime cost and limits

RNNoise uses the pinned official **little** weights and the upstream architecture-selected vector implementation, including NEON where the compiler/target supports it. There is no extra neural runtime, Android service, per-frame Java bridge, custom resampler, or receive-audio DSP loop.

The wrapper reserves one RNNoise state and 1,920 bytes of float scratch per installed factory. It initializes the model only on the first eligible enabled frame and after a reset. OFF bypasses RNNoise computation and leaves sample data unchanged. WebRTC's installed asynchronous frame queue and callback synchronization still have overhead while OFF; this is **not zero-cost bypass**.

Processing is limited to **48 kHz, mono, 480-sample frames**. Other formats pass through without suppression and trigger a history reset before supported frames resume. The enabled path adds RNNoise's own algorithmic delay; live toggles can have a brief transition artifact. No phone CPU, battery, thermal, audio-quality, or latency improvement percentage is claimed.

Stock AEC/AGC/noise suppression and the Java/Oboe device-module choice remain. RNNoise runs after stock processing and before encoding, so enabled calls can have **two suppression stages**. Removing the stock stage dynamically would reintroduce the live reconfiguration we are avoiding. Evaluate voice quality on the actual phone/routes before making this your daily build.

RNNoise allocation/init/non-finite failures fall back to unmodified audio for that processor's lifetime. The preference switch records the requested state; it is not a DSP health meter. Factory recreation provides a fresh processor.

## Useful commands

```bash
# Archive integrity and script syntax:
bash scripts/verify-package.sh

# Fast offline tests (Python 3.11+, g++, JDK, zip/unzip):
python3 tests/test_kit.py
python3 tests/test_native_processor.py
python3 tests/test_gain_hook.py

# Real upstream patch composition and rollback; input checkout stays untouched:
python3 tests/test_patch_stack.py /path/to/clean/Signal-v8.26.4
python3 tests/test_native_patches.py /path/to/WebRTC-7871f /path/to/RingRTC-2.71.0

# Full RNNoise source-shape check after patching:
bash tools/optimized-kit/validate-signal-shape.sh /path/to/patched/Signal --rnnoise
```

The validator's default mode preserves the old nine-patch checks for the previous helper interface. The new workflow explicitly requires `--rnnoise` and all ten patches. Run patches through the driver so source rollback is available. Strict patches deliberately reject an already-patched or incompatible checkout.

The native job also compiles and exercises the **actual downloaded RNNoise model** using `tools/rnnoise/test-vendored-rnnoise.sh`. It prints host state-size/CPU diagnostics; those are not Android phone measurements.

## Device acceptance before promotion

Check voice/video calls with RNNoise OFF and ON, rapid toggles, mute/unmute, route changes, Bluetooth connect/disconnect, and a new call. Confirm gain at 0/100/200%, PiP close/reopen without false switch resets, proximity resets on actual route/new-call transitions, both camera directions while swapped, hidden self-preview, and screen sharing. Then run a sustained call while observing voice artifacts, CPU/temperature, and crashes.

Do not combine `tools/live-ns` with this build. Those old files may remain in your repository for comparison; they are excluded from the new workflow. APK signing retains your supplied key, which is necessary for normal updates of an existing installation.
