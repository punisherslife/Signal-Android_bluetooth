#!/usr/bin/env python3
"""Create/verify a checksummed native checkpoint tied to exact source and tools."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import zipfile

AAR = 'ringrtc-android-hqgain-rnnoise-little.aar'
FILES = (AAR, 'ringrtc-version.txt', 'ringrtc-direct-dependencies.txt', 'provenance.json')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def control_hash(root):
    h = hashlib.sha256()
    files = []
    for name in ('patches', 'tools', '.github/actions'):
        files += [p for p in (root / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    files += list((root / '.github/workflows').glob('hq-gain10-rnnoise-little-resilient-4job.yml'))
    for p in sorted(files):
        h.update(p.relative_to(root).as_posix().encode() + b'\0')
        h.update(bytes.fromhex(sha256(p)))
    return h.hexdigest()


def head(root):
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()


def inspect_aar(path):
    helper = runpy.run_path(str(Path(__file__).with_name('use-custom-ringrtc.py')))
    abis = helper['aar_abis'](path)
    wanted = {
        'org/webrtc/PeerConnectionFactory.class': [b'nativeCreateRnnoiseAudioFrameProcessor', b'nativeSetRnnoiseAudioFrameProcessorEnabled'],
        'org/webrtc/audio/WebRtcAudioTrack.class': [b'HqCallGainBridge', b'registerAudioTrack', b'unregisterAudioTrack'],
        'org/signal/ringrtc/CallManager.class': [b'setStrongNoiseSuppressionEnabled', b'createRnnoiseAudioFrameProcessor'],
    }
    counts = {n: 0 for n in wanted}
    with zipfile.ZipFile(path) as aar:
        for entry in aar.namelist():
            if not entry.endswith('.jar'):
                continue
            with zipfile.ZipFile(io.BytesIO(aar.read(entry))) as jar:
                for name, markers in wanted.items():
                    if name in jar.namelist():
                        counts[name] += 1
                        data = jar.read(name)
                        if not data.startswith(b'\xca\xfe\xba\xbe') or any(m not in data for m in markers):
                            raise ValueError(f'Missing compiled hook in {name}')
    if any(count != 1 for count in counts.values()):
        raise ValueError(f'Expected exactly one of each patched class: {counts}')
    return abis


def verify(directory, kit, source=None):
    hashes = json.loads((directory / 'SHA256SUMS.json').read_text())
    if set(hashes) != set(FILES):
        raise ValueError('Native checkpoint file inventory mismatch')
    for name, expected in hashes.items():
        if sha256(directory / name) != expected:
            raise ValueError(f'Native checkpoint checksum mismatch: {name}')
    meta = json.loads((directory / 'provenance.json').read_text())
    pins = json.loads((kit / 'tools/rnnoise/versions.json').read_text())
    if meta['pins'] != pins or meta['control_sha256'] != control_hash(kit):
        raise ValueError('Native checkpoint belongs to different source pins or kit tools')
    if source is not None and head(source) != pins['signal_commit']:
        raise ValueError('Signal checkout differs from native checkpoint')
    if (directory / 'ringrtc-version.txt').read_text().strip() != pins['ringrtc_version']:
        raise ValueError('Native checkpoint RingRTC version mismatch')
    if meta['archs'] not in ('arm64', 'all'):
        raise ValueError('Invalid native architecture selection')
    actual = inspect_aar(directory / AAR)
    expected = ('arm64-v8a',) if meta['archs'] == 'arm64' else ('armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64')
    if actual != expected:
        raise ValueError(f'AAR ABIs {actual} do not match requested {expected}')
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('create', 'verify', 'install'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('kit', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--ringrtc', type=Path)
    parser.add_argument('--webrtc', type=Path)
    parser.add_argument('--archs', choices=('arm64', 'all'))
    args = parser.parse_args()
    directory, kit = args.directory.resolve(), args.kit.resolve()
    if args.command == 'create':
        if not all((args.source, args.ringrtc, args.webrtc, args.archs)):
            parser.error('create requires --source --ringrtc --webrtc --archs')
        pins = json.loads((kit / 'tools/rnnoise/versions.json').read_text())
        for root, key in ((args.source, 'signal_commit'), (args.ringrtc, 'ringrtc_commit'), (args.webrtc, 'webrtc_commit')):
            if head(root) != pins[key]:
                raise ValueError(f'Unexpected {key} in {root}')
        source_pin = (args.webrtc / 'third_party/rnnoise_little/SOURCE-PIN.txt').read_text()
        if pins['rnnoise_commit'] not in source_pin or pins['model_sha256'] not in source_pin:
            raise ValueError('RNNoise vendor provenance mismatch')
        directory.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(args.source / 'app/libs' / AAR, directory / AAR)
        for name in FILES[1:3]:
            shutil.copyfile(args.source / 'app/build/hq-gain' / name, directory / name)
        meta = {'pins': pins, 'archs': args.archs, 'control_sha256': control_hash(kit)}
        (directory / 'provenance.json').write_text(json.dumps(meta, indent=2) + '\n')
        (directory / 'SHA256SUMS.json').write_text(json.dumps({n: sha256(directory / n) for n in FILES}, indent=2) + '\n')
    meta = verify(directory, kit, args.source)
    if args.command == 'install':
        if args.source is None:
            parser.error('install requires --source')
        for subdir in ('app/libs', 'app/build/hq-gain'):
            (args.source / subdir).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(directory / AAR, args.source / 'app/libs' / AAR)
        for name in FILES[1:3]:
            shutil.copyfile(directory / name, args.source / 'app/build/hq-gain' / name)
        helper = Path(__file__).with_name('use-custom-ringrtc.py')
        runpy.run_path(str(helper))['install'](args.source, AAR)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'commit={meta["pins"]["signal_commit"]}\ntag={meta["pins"]["signal_tag"]}\narchs={meta["archs"]}\n')
    print(f'Native checkpoint verified: {meta["pins"]["signal_tag"]}, {meta["archs"]}')


if __name__ == '__main__':
    main()
