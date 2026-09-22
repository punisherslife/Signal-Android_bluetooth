#!/usr/bin/env python3
"""Install maintenance files with a rollback manifest; never patch Signal in place."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

KIT=Path(__file__).resolve().parents[1]


def install(repo):
    actual=Path(subprocess.check_output(['git','-C',str(repo),'rev-parse','--show-toplevel'],text=True).strip()).resolve()
    if actual!=repo:raise ValueError('Choose the root of the maintenance Git checkout')
    if not (repo/'patches').is_dir() and not (repo/'gradlew').is_file():raise ValueError('Target does not look like the Signal maintenance repository')
    files=[]
    for name in ('patches','tools','tests','.github/actions'):
        files += [(p,p.relative_to(KIT)) for p in (KIT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    files += [(KIT/'.github/workflows/hq-gain10-rnnoise-little-resilient-4job.yml',Path('.github/workflows/hq-gain10-rnnoise-little-resilient-4job.yml'))]
    files += [(KIT/'licenses/RNNOISE-BSD-3-CLAUSE.txt',Path('licenses/RNNOISE-BSD-3-CLAUSE.txt')),
              (KIT/'README.md',Path('README-RNNOISE-KIT.md')),
              (KIT/'VALIDATION.md',Path('VALIDATION-RNNOISE-KIT.md'))]
    for source,rel in files:
        target=repo/rel
        if not source.is_file():raise ValueError(f'Missing kit input: {source}')
        if target.is_symlink() or not target.resolve().is_relative_to(repo):raise ValueError(f'Unsafe install target: {target}')
        if target.exists() and not target.is_file():raise ValueError(f'Install target is not a file: {target}')
    # Keep backups in Git's own directory so they cannot be accidentally added
    # to a commit. Works with ordinary checkouts and Git worktrees.
    gitdir=Path(subprocess.check_output(['git','-C',str(repo),'rev-parse','--absolute-git-dir'],text=True).strip())
    backup=gitdir/'rnnoise-kit-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True)
    records=[]
    for source,rel in files:
        target=repo/rel;previous=backup/'files'/rel
        exists=target.is_file()
        if exists:previous.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,previous)
        records.append({'path':rel.as_posix(),'existed':exists,'installed_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    (backup/'rollback.json').write_text(json.dumps({'repo':str(repo),'files':records},indent=2)+'\n')
    shutil.copyfile(KIT/'scripts/restore-install.py',backup/'restore-install.py')
    try:
        for source,rel in files:
            target=repo/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    except BaseException:
        for record in records:
            rel=record['path'];target=repo/rel
            if record['existed']:shutil.copy2(backup/'files'/rel,target)
            else:target.unlink(missing_ok=True)
        raise
    print(f'Installed {len(files)} maintenance files. No commit, push, build, or release was started.')
    print(f'Rollback: python3 "{backup}/restore-install.py" "{backup}"')
    print('Run the RNNoise workflow on your test branch. Older live-NS workflows use incompatible native tooling.')


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: install-into-repo.py <maintenance-repo>')
    install(Path(sys.argv[1]).resolve())
