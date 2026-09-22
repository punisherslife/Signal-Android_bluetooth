#!/usr/bin/env python3
"""Check complete kit inventory, SHA-256, and Python/Bash syntax offline."""
import ast
import hashlib
from pathlib import Path
import subprocess
import sys


def verify(root):
    if sys.version_info < (3,11):raise SystemExit('Python 3.11+ is required')
    required = {f'patches/{n}' for n in __import__('runpy').run_path(str(root/'tools/optimized-kit/apply-existing-patches.py'))['PATCHES']}
    required |= {
        '.github/workflows/hq-gain10-rnnoise-little-resilient-4job.yml',
        '.github/actions/prepare-signal/action.yml',
        'tools/optimized-kit/validate-signal-shape.sh',
        'tools/optimized-kit/validate-signal-shape.py',
        'tools/optimized-kit/native-handoff.py',
        'tools/rnnoise/rnnoise_audio_frame_processor.h',
        'tools/rnnoise/versions.json',
        'licenses/RNNOISE-BSD-3-CLAUSE.txt',
    }
    records={}
    for line in (root/'MANIFEST.sha256').read_text().splitlines():
        digest,rel=line.split('  ',1)
        if rel in records or Path(rel).is_absolute() or '..' in Path(rel).parts:raise ValueError('Unsafe/duplicate manifest entry')
        records[rel]=digest
    if not required.issubset(records):raise ValueError(f'Manifest missing required files: {required-records.keys()}')
    for rel,digest in records.items():
        p=root/rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError(f'Missing or modified package file: {rel}')
        if p.suffix=='.py':ast.parse(p.read_text(),filename=rel)
        if p.suffix=='.sh':subprocess.run(['bash','-n',str(p)],check=True)
    print(f'PACKAGE_VERIFY_PASS: {len(records)} files, checksums and script syntax')


if __name__=='__main__':verify(Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1]))
