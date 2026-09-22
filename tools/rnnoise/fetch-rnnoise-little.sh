#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: fetch-rnnoise-little.sh <webrtc-source-root>" >&2
  exit 2
fi

WEBRTC_ROOT="$(cd "$1" && pwd)"
PIN_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/versions.json"
PIN_VALUES="$(python3 - "$PIN_FILE" <<'PINPY'
import json,re,sys
p=json.load(open(sys.argv[1]))
for key,n in [('rnnoise_commit',40),('model_sha256',64)]:
    if not re.fullmatch('[0-9a-f]{'+str(n)+'}',p[key]): raise SystemExit('Invalid RNNoise pin')
print(p['rnnoise_commit'])
print(p['model_sha256'])
PINPY
)"
RNNOISE_COMMIT="${PIN_VALUES%%$'\n'*}"
MODEL_SHA256="${PIN_VALUES##*$'\n'}"
MODEL_FILE="rnnoise_data-${MODEL_SHA256}.tar.gz"
MODEL_URL="https://media.xiph.org/rnnoise/models/${MODEL_FILE}"
DEST="$WEBRTC_ROOT/third_party/rnnoise_little"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v sha256sum >/dev/null || { echo "sha256sum is required" >&2; exit 1; }

SRC="$TMP/rnnoise"
git init -q "$SRC"
git -C "$SRC" remote add origin https://github.com/xiph/rnnoise.git
git -C "$SRC" fetch -q --depth 1 origin "$RNNOISE_COMMIT"
git -C "$SRC" checkout -q --detach FETCH_HEAD
ACTUAL_COMMIT="$(git -C "$SRC" rev-parse HEAD)"
[[ "$ACTUAL_COMMIT" == "$RNNOISE_COMMIT" ]] || {
  echo "RNNoise source commit mismatch: $ACTUAL_COMMIT" >&2
  exit 1
}

ARCHIVE="$TMP/$MODEL_FILE"
curl -fL --retry 4 --retry-delay 2 --connect-timeout 20 \
  "$MODEL_URL" -o "$ARCHIVE"
echo "$MODEL_SHA256  $ARCHIVE" | sha256sum -c -

tar -xzf "$ARCHIVE" -C "$SRC"

# Follow the model C file's actual header include before normalizing names.
python3 "$(dirname "$PIN_FILE")/select-rnnoise-model.py" "$SRC"

[[ ! -e "$DEST" ]] || { echo "RNNoise vendor destination already exists; use a clean checkout" >&2; exit 1; }
mkdir -p "$DEST"
cp -R "$SRC/include" "$DEST/include"
cp -R "$SRC/src" "$DEST/src"
# The model tarball can contain both regular and little weights. Keep only the
# canonical little model; do not carry unused multi-megabyte models or demos.
find "$DEST/src" -maxdepth 1 -type f \( -name "rnnoise_data_little.*" -o -name "*.bin" -o -name "*.tar.gz" \) -delete
cp "$SRC/COPYING" "$DEST/COPYING"
cp "$SRC/README" "$DEST/README"
cat > "$DEST/SOURCE-PIN.txt" <<EOF
RNNoise source commit: $RNNOISE_COMMIT
RNNoise model archive SHA-256: $MODEL_SHA256
Model: official rnnoise_data_little.c / rnnoise_data_little.h substituted as rnnoise_data.c / rnnoise_data.h
EOF

# Do not carry source-control metadata or unrelated build output.
rm -rf "$DEST/src/x86/.deps" 2>/dev/null || true

test -s "$DEST/include/rnnoise.h"
test -s "$DEST/src/rnnoise_data.c"
test -s "$DEST/src/rnnoise_data.h"
grep -F 'rnnoise_process_frame' "$DEST/include/rnnoise.h" >/dev/null

echo "RNNOISE_SOURCE_COMMIT=$RNNOISE_COMMIT"
echo "RNNOISE_MODEL_SHA256=$MODEL_SHA256"
echo "RNNOISE_VENDOR_DIR=$DEST"
