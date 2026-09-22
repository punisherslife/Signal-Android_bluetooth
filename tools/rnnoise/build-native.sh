#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 4 ]] || { echo 'usage: build-native.sh <deps|sync|patch|build> <signal-root> <work-dir> <arm64|all>' >&2; exit 2; }
PHASE="$1"
SIGNAL="$(realpath "$2")"
WORK="$(realpath -m "$3")"
ARCHS="$4"
[[ "$ARCHS" == arm64 || "$ARCHS" == all ]] || exit 2
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RINGRTC="$WORK/ringrtc"
WEBRTC="$RINGRTC/src/webrtc/src"
export PATH="$WORK/depot_tools:$PATH"

# Pins are repository-controlled data; validate their shape before shell use.
PIN_VARS="$(python3 - "$KIT/tools/rnnoise/versions.json" <<'PY'
import json,re,sys
p=json.load(open(sys.argv[1]))
for key in ('ringrtc_version','ringrtc_commit','webrtc_tag','webrtc_commit'):
    if not re.fullmatch(r'[A-Za-z0-9.]+',p[key]): raise SystemExit('Invalid source pin')
    print(key.upper()+'='+p[key])
PY
)"
eval "$PIN_VARS"

case "$PHASE" in
  deps)
    mkdir -p "$WORK"
    sudo apt-get update
    sudo apt-get install -y protobuf-compiler make pkg-config
    sdkmanager --channel=3 'platforms;android-34' 'ndk;28.0.13004108'
    [[ "$(cat "$SIGNAL/app/build/hq-gain/ringrtc-version.txt")" == "$RINGRTC_VERSION" ]] || {
      echo 'Resolved Signal RingRTC differs from the audited source pin' >&2; exit 1;
    }
    git clone --depth 1 --branch "v$RINGRTC_VERSION" https://github.com/signalapp/ringrtc.git "$RINGRTC"
    [[ "$(git -C "$RINGRTC" rev-parse HEAD)" == "$RINGRTC_COMMIT" ]] || exit 1
    TOOLCHAIN="$(cat "$RINGRTC/rust-toolchain")"
    TARGETS=aarch64-linux-android
    if [[ "$ARCHS" == all ]]; then TARGETS+=,armv7-linux-androideabi,x86_64-linux-android,i686-linux-android; fi
    rustup toolchain install "$TOOLCHAIN" --profile minimal --target "$TARGETS"
    ;;
  sync)
    git clone --depth 1 https://chromium.googlesource.com/chromium/tools/depot_tools.git "$WORK/depot_tools"
    cd "$RINGRTC"
    bash bin/prepare-workspace android
    [[ "$(git -C "$WEBRTC" rev-parse HEAD)" == "$WEBRTC_COMMIT" ]] || {
      echo 'RingRTC synced an unexpected WebRTC commit' >&2; exit 1;
    }
    ;;
  patch)
    bash "$KIT/tools/rnnoise/fetch-rnnoise-little.sh" "$WEBRTC"
    python3 "$KIT/tools/rnnoise/patch-webrtc-rnnoise.py" "$WEBRTC"
    python3 "$KIT/tools/rnnoise/patch-ringrtc-rnnoise.py" "$RINGRTC"
    python3 "$KIT/tools/rnnoise/configure-ringrtc-archs.py" "$RINGRTC" "$ARCHS" --jobs 2
    git -C "$RINGRTC" diff --check
    git -C "$WEBRTC" diff --check
    ;;
  build)
    export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/28.0.13004108"
    export CARGO_BUILD_JOBS=2
    cd "$RINGRTC"
    bash bin/build-aar --release
    mapfile -t AARS < <(find out -type f -path '*/outputs/aar/*.aar' -name '*release*.aar' | sort)
    [[ ${#AARS[@]} -eq 1 ]] || { echo "Expected one release AAR; found ${#AARS[@]}" >&2; exit 1; }
    mkdir -p "$SIGNAL/app/libs"
    bash "$KIT/tools/hq-gain/patch-ringrtc-aar.sh" "${AARS[0]}" \
      "$SIGNAL/app/libs/ringrtc-android-hqgain-rnnoise-little.aar"
    ;;
  *) echo "Unknown phase: $PHASE" >&2; exit 2 ;;
esac
