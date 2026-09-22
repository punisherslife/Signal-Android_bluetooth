#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 1 ]] || { echo 'usage: test-vendored-rnnoise.sh <rnnoise-source>' >&2; exit 2; }
SRC="$(realpath "$1")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
sources=(celt_lpc denoise kiss_fft nnet nnet_default parse_lpcnet_weights pitch rnn rnnoise_data rnnoise_tables)
args=()
for s in "${sources[@]}"; do args+=("$SRC/src/$s.c"); done
cc -O2 -DRNNOISE_BUILD -DRNNOISE_EXPORT= -DDISABLE_DEBUG_FLOAT \
  -I "$SRC/include" -I "$SRC/src" "${args[@]}" \
  "$HERE/rnnoise_smoke.c" -lm -o "$TMP/rnnoise-smoke"
"$TMP/rnnoise-smoke"
