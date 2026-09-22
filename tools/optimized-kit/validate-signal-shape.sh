#!/usr/bin/env bash
set -euo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$TOOLS/validate-signal-shape.py" "$@"
