#!/usr/bin/env python3
"""Apply patches 0001..0010 in order; restore touched files on any failure."""
from __future__ import annotations
import ast
import subprocess
import sys
from pathlib import Path

PATCHES = (
    '0001-hq-bluetooth.py', '0002-proximity-toggle.py',
    '0003-video-phone-speaker.py', '0004-hq-call-gain.py',
    '0005-strong-noise-suppression.py', '0006-hq-call-gain-10db-compressed.py',
    '0007-hide-self-camera-system-pip.py', '0008-one-to-one-video-swap.py',
    '0009-self-preview-menu.py', '0010-preview-proximity-state-fix.py',
)


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: apply-existing-patches.py <signal-root> <kit-root>')
    root, control = map(lambda s: Path(s).resolve(), sys.argv[1:])
    files = [control / 'patches' / name for name in PATCHES]
    targets = set()
    for path in files:
        if not path.is_file():
            raise SystemExit(f'Missing required patch: {path}')
        source = path.read_text(encoding='utf-8')
        compile(source, str(path), 'exec')
        # The reviewed scripts declare their touched app paths as literals.
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                rel = node.value
                if rel.startswith('app/') and '\n' not in rel:
                    target = root / rel
                    if not target.resolve().is_relative_to(root) or target.is_symlink():
                        raise SystemExit(f'Unsafe patch target: {target}')
                    targets.add(target)
    snapshots = {p: p.read_bytes() if p.exists() else None for p in targets}
    try:
        for path in files:
            print(f'Applying {path.name}', flush=True)
            subprocess.run([sys.executable, str(path), str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'diff', '--check'], check=True)
    except BaseException:
        for path, original in snapshots.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        print('Patch stack failed; restored all declared app files.', file=sys.stderr)
        raise
    print('Applied all ten patches; source whitespace check passed.')


if __name__ == '__main__':
    main()
