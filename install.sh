#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -eq 1 ]] || { echo 'usage: bash install.sh /path/to/Signal-Android_bluetooth' >&2; exit 2; }
bash "$ROOT/scripts/verify-package.sh"
python3 "$ROOT/scripts/install-into-repo.py" "$1"
