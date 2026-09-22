#!/usr/bin/env python3
"""Exercise install/restore in disposable Git roots with 0644 helper scripts."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

KIT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as t:
    root=Path(t);kit=root/'kit';shutil.copytree(KIT,kit,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for p in kit.rglob('*'):
        if p.is_file():p.chmod(0o644)
    repo=root/'repo';repo.mkdir();(repo/'patches').mkdir()
    (repo/'patches/0005-strong-noise-suppression.py').write_text('previous original\n')
    subprocess.run(['git','init','-q',str(repo)],check=True)
    baseline={p.relative_to(repo):p.read_bytes() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts}
    subprocess.run(['bash',str(kit/'install.sh'),str(repo)],check=True)
    backup=next((repo/'.git/rnnoise-kit-backups').iterdir())
    data=json.loads((backup/'rollback.json').read_text())
    assert (repo/'tools/optimized-kit/validate-signal-shape.sh').is_file()
    assert not (repo/'scripts/fetch-pinned-base.sh').exists()
    changed=repo/'patches/0005-strong-noise-suppression.py';installed=changed.read_bytes();changed.write_text('subsequent user edit\n')
    r=subprocess.run([sys.executable,str(backup/'restore-install.py'),str(backup)],capture_output=True)
    assert r.returncode!=0 and changed.read_text()=='subsequent user edit\n'
    changed.write_bytes(installed)
    subprocess.run([sys.executable,str(backup/'restore-install.py'),str(backup)],check=True)
    restored={p.relative_to(repo):p.read_bytes() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts}
    assert restored==baseline
print('PASS: complete installer with non-executable helpers; backup/restore; post-install edits protected')
