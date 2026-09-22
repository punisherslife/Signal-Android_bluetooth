#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 3 ]] || { echo 'usage: sign-apk.sh <prepare|sign> <signal-root> <handoff>' >&2; exit 2; }
PHASE="$1"
SIGNAL="$(realpath "$2")"
HANDOFF="$(realpath "$3")"
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KEY="$RUNNER_TEMP/rnnoise-fork-signing.jks"
TYPE_FILE="$RUNNER_TEMP/rnnoise-keystore-type"
: "${FORK_KEYSTORE_PASSWORD:?Missing FORK_KEYSTORE_PASSWORD}"
: "${FORK_KEY_ALIAS:?Missing FORK_KEY_ALIAS}"

if [[ "$PHASE" == prepare ]]; then
  : "${FORK_KEYSTORE_B64:?Missing FORK_KEYSTORE_B64}"
  umask 077
  printf '%s' "$FORK_KEYSTORE_B64" | base64 --decode > "$KEY"
  keytool -J-Duser.language=en -list -keystore "$KEY" \
    -storepass:env FORK_KEYSTORE_PASSWORD -alias "$FORK_KEY_ALIAS" >/dev/null
  KEY_INFO="$(keytool -J-Duser.language=en -list -keystore "$KEY" -storepass:env FORK_KEYSTORE_PASSWORD)"
  TYPE="$(awk -F': ' '/^Keystore type:/ {print $2; exit}' <<< "$KEY_INFO")"
  [[ -n "$TYPE" ]] || { echo 'Could not identify keystore type' >&2; exit 1; }
  if [[ "$TYPE" != PKCS12 ]]; then : "${FORK_KEY_PASSWORD:?Missing FORK_KEY_PASSWORD}"; fi
  printf '%s\n' "$TYPE" > "$TYPE_FILE"
elif [[ "$PHASE" == sign ]]; then
  trap 'rm -f "$KEY" "$TYPE_FILE" "$KIT/dist/aligned-unsigned.apk"' EXIT
  BUILD_TOOLS="$(python3 - "$SIGNAL/gradle/libs.versions.toml" <<'PY'
import sys,tomllib
with open(sys.argv[1],'rb') as f: print(tomllib.load(f)['versions']['buildTools'])
PY
)"
  ARCHS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["archs"])' "$HANDOFF/provenance.json")"
  APK="$(python3 "$KIT/tools/optimized-kit/select-apk.py" "$SIGNAL" "$ARCHS")"
  TYPE="$(cat "$TYPE_FILE")"
  if [[ "$TYPE" == PKCS12 ]]; then
    export EFFECTIVE_KEY_PASSWORD="$FORK_KEYSTORE_PASSWORD"
  else
    : "${FORK_KEY_PASSWORD:?Missing FORK_KEY_PASSWORD}"
    export EFFECTIVE_KEY_PASSWORD="$FORK_KEY_PASSWORD"
  fi
  ZIPALIGN="$ANDROID_HOME/build-tools/$BUILD_TOOLS/zipalign"
  APKSIGNER="$ANDROID_HOME/build-tools/$BUILD_TOOLS/apksigner"
  mkdir -p "$KIT/dist"
  ALIGNED="$KIT/dist/aligned-unsigned.apk"
  OUT="$KIT/dist/Signal-v8.26.4-hq-rnnoise-little-${ARCHS}.apk"
  "$ZIPALIGN" -f -P 16 4 "$APK" "$ALIGNED"
  "$APKSIGNER" sign --ks "$KEY" --ks-key-alias "$FORK_KEY_ALIAS" \
    --ks-pass env:FORK_KEYSTORE_PASSWORD --key-pass env:EFFECTIVE_KEY_PASSWORD \
    --out "$OUT" "$ALIGNED"
  "$APKSIGNER" verify --verbose --print-certs "$OUT"
  "$ZIPALIGN" -c -P 16 4 "$OUT"
  cp "$HANDOFF/provenance.json" "$KIT/dist/provenance.json"
  cp "$KIT/licenses/RNNOISE-BSD-3-CLAUSE.txt" "$KIT/dist/"
  (cd "$KIT/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
else
  echo "Unknown phase: $PHASE" >&2; exit 2
fi
