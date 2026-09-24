#!/usr/bin/env python3
"""Exercise patch composition and rollback on files from the real pinned source.

Usage: python3 tests/test_patch_stack.py /path/to/clean/Signal-v8.26.4
Only the patch-target files are copied. The supplied checkout is never edited.
"""
import ast
from collections import Counter
from pathlib import Path
import re
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
    assert 'callManager.setStrongNoiseSuppressionEnabled(enabled)' in manager
    assert 'Log.w(TAG, "Unable to toggle RNNoise Little"' not in manager
    assert 'AudioDevice.NONE\n\n  @Volatile\n' in audio
    # Only fixed failure messages are allowed beyond stock diagnostics: no
    # identifiers, interpolation, exception text, or successful-toggle logs.
    expected_logs={
        'webrtc/audio/FullSignalAudioManagerApi31.kt': Counter({
            'Log.w(TAG, "HQ Bluetooth request unavailable")': 1,
        }),
        'service/webrtc/SignalCallManager.java': Counter({
            'Log.w(TAG, "RNNoise preference restore failed");': 2,
            'Log.w(TAG, "RNNoise request failed");': 3,
        }),
        'webrtc/audio/HqCallGainBridge.kt': Counter({
            'private val TAG = Log.tag(HqCallGainBridge::class.java)': 1,
            'Log.w(TAG, "HQ gain effect update failed")': 2,
            'Log.w(TAG, "HQ gain effect unavailable")': 1,
        }),
    }
    for rel, before in original.items():
        if not rel.endswith(('.java', '.kt')):
            continue
        def log_lines(data):
            return Counter(line.strip() for line in (data or b'').decode().splitlines()
                           if re.search(r'\b(?:Log|Logger|Logging)\.[a-zA-Z]+\s*\(', line))
        added_logs=log_lines((root/rel).read_bytes())-log_lines(before)
        suffix=rel.removeprefix('app/src/main/java/org/thoughtcrime/securesms/')
        assert added_logs==expected_logs.get(suffix,Counter()), (rel, added_logs)
    screen=(root/'app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt').read_text()
    # Source integration guards, not a substitute for Compose/device tests.
    assert 'if (oneToOneSwapActive) {\n                LargeLocalVideoRenderer(' in screen
    assert 'oneToOneSwapActive = showSelfPreviewInCall &&' in screen
    for guard in ('!callControlsState.isGroupCall', '!callScreenState.isLocalScreenSharing',
                  '!localParticipant.isScreenSharing', 'localParticipant.isVideoEnabled',
                  'singleRemoteParticipant != null', '!singleRemoteParticipant.isScreenSharing'):
        assert guard in screen
    assert 'callParticipantsPagerState.callParticipants.singleOrNull()' in screen
    assert 'remember(oneToOneSwapActive, oneToOneRemoteParticipant?.callParticipantId)' in screen
    renderer=(root/'app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableRemoteVideoRenderer.kt').read_text()
    assert 'rememberSelfPipSize(previewRenderState)' in renderer
    assert '.clickable(onClick = onClick)' in renderer
    assert 'if (expanded) {\n        IconButton(' in renderer
    assert 'onClick = onSwapClick' in renderer
    assert 'onClick = onToggleCameraDirectionClick' in renderer
    assert 'WebRtcLocalRenderState.FOCUSED' not in renderer
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
    # 0010 must validate the remote renderer before changing its other targets.
    for rel,data in original.items():
        p=root/rel
        if data is None:p.unlink(missing_ok=True)
        else:p.write_bytes(data)
    for patch in sorted((KIT/'patches').glob('000*.py')):
        subprocess.run([sys.executable,str(patch),str(root)],check=True,capture_output=True)
    p=root/'app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableRemoteVideoRenderer.kt'
    p.write_text(p.read_text().replace('.clip(RoundedCornerShape(16.dp))', '.clip(RoundedCornerShape(17.dp))'))
    remote_drift=snapshot(root)
    result=subprocess.run([sys.executable,str(KIT/'patches/0010-preview-proximity-state-fix.py'),str(root)],capture_output=True)
    assert result.returncode != 0 and snapshot(root)==remote_drift
    # All files are preflighted before the first patch touches source.
    control=tmp/'control';shutil.copytree(KIT/'patches',control/'patches')
    (control/'patches/0010-preview-proximity-state-fix.py').unlink()
    apply(root,control,success=False);assert remote_drift==snapshot(root)
print('PASS: ten patches on real source; only approved fixed failure logs; swap source integration; safe repeat refusal; late-failure rollback; remote-renderer preflight; missing-file preflight')
