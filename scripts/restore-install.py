#!/usr/bin/env python3
"""Undo a kit installation, refusing to overwrite subsequent user edits."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def restore(backup):
    data=json.loads((backup/'rollback.json').read_text());repo=Path(data['repo']).resolve()
    for item in data['files']:
        rel=Path(item['path']);target=repo/rel
        if rel.is_absolute() or '..' in rel.parts or not target.resolve().is_relative_to(repo):raise ValueError('Unsafe rollback target')
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=item['installed_sha256']:
            raise ValueError(f'Refusing to overwrite a changed/missing installed file: {target}')
        if item['existed'] and not (backup/'files'/rel).is_file():raise ValueError(f'Missing backup for {rel}')
    for item in data['files']:
        target=repo/item['path']
        if item['existed']:shutil.copy2(backup/'files'/item['path'],target)
        else:target.unlink()
    print('Original maintenance files restored; files added by the kit removed.')


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: restore-install.py <backup-directory>')
    restore(Path(sys.argv[1]).resolve())
