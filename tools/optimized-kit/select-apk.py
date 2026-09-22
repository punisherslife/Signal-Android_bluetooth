#!/usr/bin/env python3
"""Select the exact release variant and reject incomplete advertised native ABIs."""
import json
import sys
import zipfile
from pathlib import Path


def select(root, archs):
    if archs not in ('arm64', 'all'):
        raise ValueError('Invalid ABI selection')
    candidates = []
    for metadata in (root / 'app/build/outputs/apk').rglob('output-metadata.json'):
        data = json.loads(metadata.read_text())
        if data.get('variantName') != 'githubProdRelease':
            continue
        for item in data.get('elements', []):
            if not item.get('filters'):
                output = (metadata.parent / item['outputFile']).resolve()
                if not output.is_relative_to(metadata.parent.resolve()):
                    raise ValueError('Invalid APK metadata path')
                candidates.append(output)
    if len(candidates) != 1:
        raise ValueError(f'Expected exactly one githubProdRelease universal output, found {len(candidates)}')
    apk = candidates[0]
    expected = {'arm64-v8a'} if archs == 'arm64' else {'armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'}
    with zipfile.ZipFile(apk) as z:
        names = set(z.namelist())
        actual = {p.split('/')[1] for p in names if p.startswith('lib/') and p.endswith('.so')}
        if actual != expected:
            raise ValueError(f'APK native ABIs {actual} differ from native build {expected}')
        for abi in actual:
            for library in ('libringrtc.so', 'libringrtc_rffi.so'):
                if f'lib/{abi}/{library}' not in names:
                    raise ValueError(f'APK missing {library} for {abi}')
        if 'assets/rnnoise-LICENSE.txt' not in names:
            raise ValueError('APK is missing the RNNoise license notice')
    return apk


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: select-apk.py <signal-root> <arm64|all>')
    print(select(Path(sys.argv[1]), sys.argv[2]))
