#!/usr/bin/env python3
"""Limit RingRTC's Android AAR build to arm64 for faster device testing."""
from __future__ import annotations

import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: configure-ringrtc-archs.py <ringrtc-root> <arm64|all>")
root = Path(sys.argv[1]).resolve()
mode = sys.argv[2]
path = root / "bin/build-aar.py"
text = path.read_text(encoding="utf-8")
old = "ARCHS = ['arm', 'arm64', 'x86', 'x64']"
if text.count(old) != 1:
    raise SystemExit(f"expected one RingRTC ARCHS declaration, found {text.count(old)}")
if mode == "all":
    print("LIVE_NS_RINGRTC_ARCHS=arm,arm64,x86,x64")
    raise SystemExit(0)
if mode != "arm64":
    raise SystemExit(f"unsupported mode: {mode}")
path.write_text(text.replace(old, "ARCHS = ['arm64']", 1), encoding="utf-8")
print("LIVE_NS_RINGRTC_ARCHS=arm64")
