#!/usr/bin/env python3
"""Verify and install the prepared custom RingRTC AAR dependency into Signal."""
from __future__ import annotations

import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: use-custom-ringrtc.py <signal-root>")

root = Path(sys.argv[1]).resolve()
version_file = root / "app/build/hq-gain/ringrtc-version.txt"
deps_file = root / "app/build/hq-gain/ringrtc-direct-dependencies.txt"
aar = root / "app/libs/ringrtc-android-hqgain-live-ns.aar"
catalog_file = root / "gradle/libs.versions.toml"
gradle_file = root / "app/build.gradle.kts"

for path in (version_file, deps_file, aar, catalog_file, gradle_file):
    if not path.is_file() or (path == aar and path.stat().st_size == 0):
        raise SystemExit(f"missing required RingRTC input: {path}")

version = version_file.read_text(encoding="utf-8").strip()
catalog = catalog_file.read_text(encoding="utf-8")
match = re.search(r'(?m)^\s*signal-ringrtc\s*=\s*"([^"]+)"\s*$', catalog)
if not match:
    raise SystemExit("Could not read signal-ringrtc coordinate from version catalog")
expected = f"org.signal:ringrtc-android:{version}"
if match.group(1) != expected:
    raise SystemExit(f"RingRTC mismatch: custom={expected}, Signal={match.group(1)}")

direct_deps = [line.strip() for line in deps_file.read_text(encoding="utf-8").splitlines() if line.strip()]
text = gradle_file.read_text(encoding="utf-8")
old = '  implementation(libs.signal.ringrtc)'
if text.count(old) != 1:
    raise SystemExit(f"Expected exactly one Signal RingRTC dependency line, found {text.count(old)}")
replacement = ['  implementation(files("libs/ringrtc-android-hqgain-live-ns.aar"))']
replacement += [f'  implementation("{coordinate}")' for coordinate in direct_deps]
gradle_file.write_text(text.replace(old, "\n".join(replacement), 1), encoding="utf-8")
print(f"Using custom RingRTC {version}; preserved {len(direct_deps)} direct dependencies")
