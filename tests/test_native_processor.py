#!/usr/bin/env python3
"""Compile/execute the real wrapper with explicit API/model test doubles."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    binary = Path(tmp) / 'native-processor-test'
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++17', '-O1', '-g', '-pthread',
        '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined,float-cast-overflow',
        '-fno-sanitize-recover=all', '-Wl,--wrap=malloc',
        '-I', str(ROOT / 'tests/stubs'), '-I', str(ROOT / 'tools/rnnoise'),
        str(ROOT / 'tests/native_processor_test.cc'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=30)
