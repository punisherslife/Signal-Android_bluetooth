#!/usr/bin/env python3
"""Apply the current known-good Signal patch stack in its original order.

This driver intentionally does not rewrite the runtime patches.  The goal of the
optimized kit is to reduce CI duplication and preserve expensive native build
outputs without changing the final app semantics.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: apply-existing-patches.py <signal-root> <control-root>")

signal_root = Path(sys.argv[1]).resolve()
control_root = Path(sys.argv[2]).resolve()
patch_root = control_root / "patches"

patches = [
    "0001-hq-bluetooth.py",
    "0002-proximity-toggle.py",
    "0003-video-phone-speaker.py",
    "0004-hq-call-gain.py",
    "0005-strong-noise-suppression.py",
    "0006-hq-call-gain-10db-compressed.py",
    "0007-hide-self-camera-system-pip.py",
    "0008-one-to-one-video-swap.py",
    "0009-self-preview-menu.py",
]

for name in patches:
    patch = patch_root / name
    if not patch.is_file():
        raise SystemExit(f"missing required patch: {patch}")
    print(f"==> applying {name}", flush=True)
    subprocess.run([sys.executable, str(patch), str(signal_root)], check=True)

subprocess.run(["git", "-C", str(signal_root), "diff", "--check"], check=True)
print("optimized-kit: all nine patches applied in original order")
