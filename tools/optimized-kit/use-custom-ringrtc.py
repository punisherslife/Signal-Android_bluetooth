#!/usr/bin/env python3
"""Install a custom RingRTC dependency and align the APK's advertised ABIs."""
from __future__ import annotations
import argparse
import re
import zipfile
from pathlib import Path

ABIS = ('armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64')
NEW_AAR = 'ringrtc-android-hqgain-rnnoise-little.aar'
OLD_AAR = 'ringrtc-android-hqgain-live-ns.aar'


def aar_abis(aar):
    with zipfile.ZipFile(aar) as archive:
        if archive.testzip() is not None:
            raise ValueError('Custom RingRTC archive CRC check failed')
        names = set(archive.namelist())
        abis = {p.split('/')[1] for p in names if p.startswith('jni/') and p.endswith('.so')}
        if not abis or not abis.issubset(ABIS):
            raise ValueError(f'Unexpected custom RingRTC ABIs: {sorted(abis)}')
        for abi in abis:
            for library in ('libringrtc.so', 'libringrtc_rffi.so'):
                name = f'jni/{abi}/{library}'
                if name not in names or archive.getinfo(name).file_size < 20:
                    raise ValueError(f'Missing native library: {name}')
                with archive.open(name) as f:
                    header = f.read(20)
                machine = int.from_bytes(header[18:20], 'little')
                expected = {'arm64-v8a': (2, 183), 'armeabi-v7a': (1, 40),
                            'x86': (1, 3), 'x86_64': (2, 62)}[abi]
                if header[:4] != b'\x7fELF' or header[5] != 1 or (header[4], machine) != expected:
                    raise ValueError(f'Incorrect ELF architecture in {name}')
        return tuple(a for a in ABIS if a in abis)


def install(root, aar_name=None):
    root = Path(root)
    inputs = root / 'app/build/hq-gain'
    version = (inputs / 'ringrtc-version.txt').read_text().strip()
    catalog = (root / 'gradle/libs.versions.toml').read_text()
    matches = re.findall(r'(?m)^\s*signal-ringrtc\s*=\s*"([^"]+)"\s*$', catalog)
    if matches != [f'org.signal:ringrtc-android:{version}']:
        raise ValueError(f'Custom RingRTC version {version!r} does not match Signal catalog {matches}')
    if aar_name is None:
        available = [n for n in (NEW_AAR, OLD_AAR) if (root / 'app/libs' / n).is_file()]
        if len(available) != 1:
            raise ValueError(f'Expected exactly one custom AAR, found {available}')
        aar_name = available[0]
    if aar_name not in (NEW_AAR, OLD_AAR):
        raise ValueError('Unsupported custom AAR filename')
    abis = aar_abis(root / 'app/libs' / aar_name)
    dependencies = (inputs / 'ringrtc-direct-dependencies.txt').read_text().splitlines()
    dependencies = sorted(set(x.strip() for x in dependencies if x.strip()))
    for dep in dependencies:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.+\-]+', dep):
            raise ValueError(f'Invalid Maven dependency: {dep!r}')
        if dep.startswith('org.signal:ringrtc-android:'):
            raise ValueError('Direct dependency must not reintroduce the stock RingRTC AAR')
    path = root / 'app/build.gradle.kts'
    text = path.read_text()
    anchor = '  implementation(libs.signal.ringrtc)'
    if text.count(anchor) != 1:
        raise ValueError('Expected one stock RingRTC dependency; start from a clean checkout')
    lines = [f'  implementation(files("libs/{aar_name}"))']
    lines += [f'  implementation("{dep}")' for dep in dependencies]
    text = text.replace(anchor, '\n'.join(lines), 1)
    # A universal APK otherwise contains other dependencies' x86/arm libraries
    # without RingRTC for those ABIs, leading to installable but crashing APKs.
    original = ', '.join(f'"{a}"' for a in ABIS)
    selected = ', '.join(f'"{a}"' for a in abis)
    for old, new in ((f'abiFilters += listOf({original})', f'abiFilters += listOf({selected})'),
                     (f'include({original})', f'include({selected})')):
        if text.count(old) != 1:
            raise ValueError(f'Unexpected Signal ABI configuration: {old}')
        text = text.replace(old, new, 1)
    path.write_text(text, encoding='utf-8')
    print(f'Custom RingRTC {version}; APK ABIs={",".join(abis)}; direct dependencies={len(dependencies)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--aar', choices=(NEW_AAR, OLD_AAR))
    args = parser.parse_args()
    install(args.root, args.aar)


if __name__ == '__main__':
    main()
