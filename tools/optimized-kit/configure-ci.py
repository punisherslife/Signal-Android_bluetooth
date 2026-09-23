#!/usr/bin/env python3
"""Cap CI Java heaps to available RAM while retaining upstream R8 flags."""
import re
import sys
from pathlib import Path


def configure(root, memory_mb):
    heap = min(6144, max(2048, memory_mb * 45 // 100))
    # Signal's main Kotlin compilation exhausted the previous 1536 MiB cap.
    # Restore up to its upstream 4 GiB heap, scaling down on smaller runners.
    kotlin = min(4096, max(512, memory_mb * 30 // 100))
    # Give the compiler room without overlapping independent Gradle workers.
    workers = 1
    path = root / 'gradle.properties'
    text = path.read_text()
    for key, size in (('org.gradle.jvmargs', heap), ('kotlin.daemon.jvmargs', kotlin)):
        pattern = re.compile(rf'(?m)^({re.escape(key)}=)(.+)$')
        matches = list(pattern.finditer(text))
        if len(matches) != 1 or len(re.findall(r'-Xmx\S+', matches[0][2])) != 1:
            raise ValueError(f'Unexpected JVM options for {key}')
        # Keep Signal's deterministic R8 settings and all other JVM switches.
        text = pattern.sub(lambda m: m[1] + re.sub(r'-Xmx\S+', f'-Xmx{size}m', m[2]), text)
    text = re.sub(r'(?m)^org.gradle.workers.max=.*\n?', '', text)
    text += f'\n# RNNoise kit: bound parallel memory use on hosted runners.\norg.gradle.workers.max={workers}\n'
    path.write_text(text)
    print(f'CI memory budget: available={memory_mb} MiB, Gradle={heap}, Kotlin={kotlin}, workers={workers}')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: configure-ci.py <signal-root>')
    memory_mb = int(re.search(r'MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text())[1]) // 1024
    for name in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        p = Path(name)
        if p.is_file() and p.read_text().strip().isdigit():
            memory_mb = min(memory_mb, int(p.read_text()) // 1024 // 1024)
    if memory_mb < 6000:
        raise SystemExit('At least 6 GiB runner RAM is required for this Android build')
    configure(Path(sys.argv[1]), memory_mb)


if __name__ == '__main__':
    main()
