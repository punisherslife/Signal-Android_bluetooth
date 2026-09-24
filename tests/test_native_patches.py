#!/usr/bin/env python3
"""Test strict native transforms on pinned sources, without downloading weights.

Usage: test_native_patches.py <WebRTC-7871f> <RingRTC-2.71.0>
The test uses marked vendor placeholders ONLY to exercise patch construction.
It does not compile RNNoise or claim an Android/native integration build.
"""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

KIT=Path(__file__).resolve().parents[1]
if len(sys.argv)!=3:raise SystemExit(__doc__)
WEBRTC,RINGRTC=map(Path,sys.argv[1:])
FILES=('sdk/android/api/org/webrtc/PeerConnectionFactory.java',
       'sdk/android/api/org/webrtc/AudioFrameProcessor.java',
       'sdk/android/src/jni/pc/peer_connection_factory.cc','sdk/android/BUILD.gn')
patch=KIT/'tools/rnnoise/patch-webrtc-rnnoise.py'
mod=runpy.run_path(str(patch))


def run(script,root,success=True):
    p=subprocess.run([sys.executable,str(script),str(root)],capture_output=True,text=True)
    if (p.returncode==0)!=success:raise AssertionError(p.stdout+p.stderr)


def snapshot(root):
    return {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}


with tempfile.TemporaryDirectory() as t:
    root=Path(t)/'webrtc'
    for rel in FILES:
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WEBRTC/rel,p)
    vendor=root/'third_party/rnnoise_little'
    for rel in ['include/rnnoise.h','src/rnnoise_data.h','COPYING']+['src/'+n for n in mod['C_SOURCES']]:
        p=vendor/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('/* shape fixture only */\n')
    (vendor/'src/vec_neon.h').write_text('/* guard fixture only */\n#if __ARM_FEATURE_DOTPROD\n#endif\n')
    original=snapshot(root);run(patch,root)
    gn=(root/'sdk/android/BUILD.gn').read_text()
    assert 'rtc_library("rnnoise_little")' in gn
    assert '"../../api/audio:audio_frame_api"' in gn
    assert 'src/jni/pc/rnnoise_audio_frame_processor.h' in gn
    assert '#if defined(__ARM_FEATURE_DOTPROD) && __ARM_FEATURE_DOTPROD' in (vendor/'src/vec_neon.h').read_text()
    patched=snapshot(root);run(patch,root,False);assert snapshot(root)==patched
    for rel in set(patched)-set(original):(root/rel).unlink()
    for rel,b in original.items():(root/rel).write_bytes(b)
    p=root/'sdk/android/src/jni/pc/peer_connection_factory.cc'
    p.write_text(p.read_text().replace('JNI_PeerConnectionFactory_FreeFactory','ChangedFactoryAnchor'))
    changed=snapshot(root);run(patch,root,False);assert snapshot(root)==changed
    root=Path(t)/'ringrtc';rel='src/android/api/org/signal/ringrtc/CallManager.java';p=root/rel;p.parent.mkdir(parents=True)
    shutil.copyfile(RINGRTC/rel,p)
    patch=KIT/'tools/rnnoise/patch-ringrtc-rnnoise.py';run(patch,root)
    text=p.read_text();assert 'if (audioConfig.useOboe)' in text
    assert 'setSoftwareNoiseSuppressionEnabled' not in text
    assert 'Log.i(TAG, "RNNoise' not in text
    run(patch,root,False);assert p.read_text()==text
print('PASS: native transforms on pinned sources; explicit GN dependencies; repeated/drifted patch refusal; stock ADM retained')
