#!/usr/bin/env bash
set -euo pipefail

eval "$(python - <<'PY'
import tomllib
with open('gradle/libs.versions.toml', 'rb') as f:
    v = tomllib.load(f)['versions']
print('NDK_VERSION=' + repr(v['ndk']))
print('BUILD_TOOLS_VERSION=' + repr(v['buildTools']))
print('COMPILE_SDK=' + repr(v['compileSdk']))
PY
)"

SDK_LIST="$(mktemp)"
trap 'rm -f "$SDK_LIST"' EXIT
sdkmanager --list --channel=3 --include_obsolete > "$SDK_LIST"

mapfile -t PLATFORM_CANDIDATES < <(
  awk -F '|' -v api="$COMPILE_SDK" '
    {
      pkg=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", pkg)
      if (pkg == "platforms;android-" api || pkg ~ ("^platforms;android-" api "\\.[0-9]+$")) print pkg
    }
  ' "$SDK_LIST" | sort -V -u
)

PLATFORM_PACKAGE=""
for candidate in "${PLATFORM_CANDIDATES[@]}"; do
  if [[ "$candidate" == "platforms;android-$COMPILE_SDK" ]]; then PLATFORM_PACKAGE="$candidate"; break; fi
done
if [[ -z "$PLATFORM_PACKAGE" ]]; then
  for candidate in "${PLATFORM_CANDIDATES[@]}"; do
    if [[ "$candidate" == "platforms;android-$COMPILE_SDK.0" ]]; then PLATFORM_PACKAGE="$candidate"; break; fi
  done
fi
if [[ -z "$PLATFORM_PACKAGE" && ${#PLATFORM_CANDIDATES[@]} -gt 0 ]]; then
  PLATFORM_PACKAGE="${PLATFORM_CANDIDATES[0]}"
fi
[[ -n "$PLATFORM_PACKAGE" ]] || { echo "No SDK platform for compileSdk $COMPILE_SDK" >&2; exit 1; }

echo "Using Android platform package: $PLATFORM_PACKAGE"
sdkmanager --channel=3 "$PLATFORM_PACKAGE" "build-tools;$BUILD_TOOLS_VERSION" "ndk;$NDK_VERSION"
