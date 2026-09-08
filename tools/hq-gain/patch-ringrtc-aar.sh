#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: patch-ringrtc-aar.sh <input.aar> <output.aar>" >&2
  exit 2
fi

INPUT="$(realpath "$1")"
OUTPUT="$(realpath -m "$2")"
TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/aar" "$TMP/tool-classes"
unzip -q "$INPUT" -d "$TMP/aar"

javac \
  --add-exports java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED \
  --add-exports java.base/jdk.internal.org.objectweb.asm.tree=ALL-UNNAMED \
  -d "$TMP/tool-classes" \
  "$TOOL_DIR/PatchWebRtcAudioTrack.java"

REGISTER_TOTAL=0
UNREGISTER_TOTAL=0

while IFS= read -r -d '' JAR; do
  PATCHED="$TMP/$(basename "$JAR").patched"
  OUTPUT_TEXT="$(java \
    --add-exports java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED \
    --add-exports java.base/jdk.internal.org.objectweb.asm.tree=ALL-UNNAMED \
    -cp "$TMP/tool-classes" \
    PatchWebRtcAudioTrack "$JAR" "$PATCHED")"

  REGISTER_COUNT="$(sed -n 's/^REGISTER_CALLS=//p' <<<"$OUTPUT_TEXT")"
  UNREGISTER_COUNT="$(sed -n 's/^UNREGISTER_CALLS=//p' <<<"$OUTPUT_TEXT")"
  REGISTER_COUNT="${REGISTER_COUNT:-0}"
  UNREGISTER_COUNT="${UNREGISTER_COUNT:-0}"

  if (( REGISTER_COUNT > 0 || UNREGISTER_COUNT > 0 )); then
    mv "$PATCHED" "$JAR"
    REGISTER_TOTAL=$((REGISTER_TOTAL + REGISTER_COUNT))
    UNREGISTER_TOTAL=$((UNREGISTER_TOTAL + UNREGISTER_COUNT))
  else
    rm -f "$PATCHED"
  fi
done < <(find "$TMP/aar" -type f -name '*.jar' -print0)

if (( REGISTER_TOTAL == 0 )); then
  echo "Could not find WebRtcAudioTrack AudioTrack.play() in the resolved RingRTC AAR." >&2
  exit 1
fi
if (( UNREGISTER_TOTAL == 0 )); then
  echo "Could not find WebRtcAudioTrack AudioTrack.stop() in the resolved RingRTC AAR." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
(
  cd "$TMP/aar"
  zip -q -r "$OUTPUT" .
)
unzip -tq "$OUTPUT" >/dev/null

printf 'Patched WebRTC playout lifecycle: %d play hook(s), %d stop hook(s)\n' \
  "$REGISTER_TOTAL" "$UNREGISTER_TOTAL"
printf 'Output: %s\n' "$OUTPUT"
