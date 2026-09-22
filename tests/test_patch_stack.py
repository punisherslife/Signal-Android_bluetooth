#!/usr/bin/env python3
"""Exercise patch composition and rollback on files from the real pinned source.

Usage: python3 tests/test_patch_stack.py /path/to/clean/Signal-v8.26.4
Only the patch-target files are copied. The supplied checkout is never edited.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

KIT=Path(__file__).resolve().parents[1]
if len(sys.argv)!=2:raise SystemExit(__doc__)
SOURCE=Path(sys.argv[1]).resolve()
targets=set()
for p in (KIT/'patches').glob('*.py'):
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('app/') and '\n' not in n.value:
            targets.add(n.value)


def snapshot(root):
    return {p:(root/p).read_bytes() if (root/p).is_file() else None for p in targets}


def apply(root, control=KIT, success=True):
    p=subprocess.run([sys.executable,str(KIT/'tools/optimized-kit/apply-existing-patches.py'),str(root),str(control)],capture_output=True,text=True)
    if (p.returncode==0)!=success:raise AssertionError(p.stdout+p.stderr)


with tempfile.TemporaryDirectory() as t:
    tmp=Path(t);root=tmp/'source';root.mkdir()
    for rel in targets:
        if (SOURCE/rel).is_file():
            p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/rel,p)
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    original=snapshot(root)
    apply(root)
    subprocess.run(['bash',str(KIT/'tools/optimized-kit/validate-signal-shape.sh'),str(root),'--rnnoise'],check=True)
    audio=(root/'app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/SignalAudioManager.kt').read_text()
    assert 'HqCallGainBridge.setHqEnabled(context, enabled)' in audio
    manager=(root/'app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java').read_text()
    assert 'Unable to toggle RNNoise Little' in manager
    applied=snapshot(root);apply(root,success=False);assert applied==snapshot(root)
    # Restore fixture, introduce late source drift, then ensure 0001..0009 writes
    # are rolled back along with generated files when 0010 refuses the shape.
    for rel,data in original.items():
        p=root/rel
        if data is None:p.unlink(missing_ok=True)
        else:p.write_bytes(data)
    p=root/'app/src/main/java/org/thoughtcrime/securesms/service/webrtc/ActiveCallManager.kt'
    p.write_text(p.read_text().replace('fun sendAudioManagerCommand(context: Context, command: AudioManagerCommand)',
                                      'fun sendAudioManagerCommand(context: Context, command: AudioManagerCommand /* upstream drift */)'))
    drifted=snapshot(root);apply(root,success=False);assert drifted==snapshot(root)
    # All files are preflighted before the first patch touches source.
    control=tmp/'control';shutil.copytree(KIT/'patches',control/'patches')
    (control/'patches/0010-preview-proximity-state-fix.py').unlink()
    apply(root,control,success=False);assert drifted==snapshot(root)
print('PASS: ten patches on real source; gain/UI integration; safe repeat refusal; late-failure rollback; missing-file preflight')
