#!/usr/bin/env python3
"""Select native ABIs and bound concurrent native compile jobs."""
import argparse
import re
from pathlib import Path


def configure(root, mode, jobs):
    path = root / 'bin/build-aar.py'
    text = path.read_text()
    pattern = r"(?m)^ARCHS = \[(?:'arm', 'arm64', 'x86', 'x64'|'arm64')\]$"
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('Unexpected RingRTC architecture declaration')
    replacement = "ARCHS = ['arm64']" if mode == 'arm64' else "ARCHS = ['arm', 'arm64', 'x86', 'x64']"
    text = re.sub(pattern, replacement, text)
    pattern = r"('ninja', )(?:(?:'-j', '\d+', )?)(('-C', webrtc_output_dir))"
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('Unexpected RingRTC siso/ninja build command')
    text = re.sub(pattern, lambda m: m[1] + f"'-j', '{jobs}', " + m[2], text)
    path.write_text(text)
    print(f'Native ABIs={mode}; compiler jobs={jobs}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('mode', choices=('arm64', 'all'))
    parser.add_argument('--jobs', type=int, choices=range(1, 17), default=2)
    args = parser.parse_args()
    configure(args.root, args.mode, args.jobs)


if __name__ == '__main__':
    main()
