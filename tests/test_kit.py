#!/usr/bin/env python3
"""Offline regression checks for packaging and strict dependency installation.

AAR/ELF/class fixtures here are deliberately synthetic, not Android build proof.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CUSTOM = runpy.run_path(str(ROOT / 'tools/optimized-kit/use-custom-ringrtc.py'))
HANDOFF = runpy.run_path(str(ROOT / 'tools/optimized-kit/native-handoff.py'))
APK = runpy.run_path(str(ROOT / 'tools/optimized-kit/select-apk.py'))
CI = runpy.run_path(str(ROOT / 'tools/optimized-kit/configure-ci.py'))
ARCH = runpy.run_path(str(ROOT / 'tools/rnnoise/configure-ringrtc-archs.py'))
MODEL = runpy.run_path(str(ROOT / 'tools/rnnoise/select-rnnoise-model.py'))


def fake_elf(abi):
    cls, machine = {'armeabi-v7a': (1,40), 'arm64-v8a': (2,183), 'x86': (1,3), 'x86_64': (2,62)}[abi]
    return b'\x7fELF' + bytes([cls,1,1]) + bytes(11) + machine.to_bytes(2,'little') + bytes(44)


def fake_aar(path, abis=('arm64-v8a',)):
    path.parent.mkdir(parents=True, exist_ok=True)
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, 'w') as z:
        for p,data in {
            'org/webrtc/PeerConnectionFactory.class': b'nativeCreateRnnoiseAudioFrameProcessor nativeSetRnnoiseAudioFrameProcessorEnabled',
            'org/webrtc/audio/WebRtcAudioTrack.class': b'HqCallGainBridge registerAudioTrack unregisterAudioTrack',
            'org/signal/ringrtc/CallManager.class': b'setStrongNoiseSuppressionEnabled createRnnoiseAudioFrameProcessor',
        }.items(): z.writestr(p, b'\xca\xfe\xba\xbe' + data)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('classes.jar',jar.getvalue())
        for a in abis:
            for lib in ('libringrtc.so','libringrtc_rffi.so'):z.writestr(f'jni/{a}/{lib}',fake_elf(a))


def fake_signal(root, abis=('arm64-v8a',)):
    for p in ('gradle','app/build/hq-gain','app/libs'):(root/p).mkdir(parents=True,exist_ok=True)
    (root/'gradle/libs.versions.toml').write_text('signal-ringrtc = "org.signal:ringrtc-android:2.71.0"\n')
    (root/'app/build/hq-gain/ringrtc-version.txt').write_text('2.71.0\n')
    (root/'app/build/hq-gain/ringrtc-direct-dependencies.txt').write_text('')
    (root/'app/build.gradle.kts').write_text('  implementation(libs.signal.ringrtc)\nabiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")\ninclude("armeabi-v7a", "arm64-v8a", "x86", "x86_64")\n')
    fake_aar(root/'app/libs'/HANDOFF['AAR'], abis)


class KitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_arm64_dependency_and_abi_filter(self):
        fake_signal(self.root)
        CUSTOM['install'](self.root)
        text=(self.root/'app/build.gradle.kts').read_text()
        self.assertIn('abiFilters += listOf("arm64-v8a")',text)
        self.assertIn('include("arm64-v8a")',text)
        self.assertNotIn('libs.signal.ringrtc',text)
        with self.assertRaises(ValueError):CUSTOM['install'](self.root)
        self.assertEqual((self.root/'app/build.gradle.kts').read_text(),text)

    def test_model_include_is_normalized_before_trimming(self):
        for header in ('rnnoise_data.h', 'rnnoise_data_little.h'):
            root=self.root/header;src=root/'src';src.mkdir(parents=True)
            (src/'nnet.h').write_text('fixture')
            (src/header).write_text('the matching model header')
            (src/'rnnoise_data_little.c').write_text('#include "'+header+'"\n/* little weights */\n')
            MODEL['select'](root)
            self.assertIn('#include "rnnoise_data.h"',(src/'rnnoise_data.c').read_text())
            self.assertEqual((src/'rnnoise_data.h').read_text(),'the matching model header')

    def test_missing_model_header_refuses_before_writes(self):
        src=self.root/'src';src.mkdir()
        (src/'nnet.h').write_text('fixture')
        (src/'rnnoise_data_little.c').write_text('#include "rnnoise_data_little.h"\n')
        with self.assertRaises(ValueError):MODEL['select'](self.root)
        self.assertFalse((src/'rnnoise_data.c').exists())

    def test_all_abis_and_direct_dependencies(self):
        fake_signal(self.root,CUSTOM['ABIS'])
        (self.root/'app/build/hq-gain/ringrtc-direct-dependencies.txt').write_text('org.example:audio:1.2.3\norg.example:audio:1.2.3\n')
        CUSTOM['install'](self.root)
        self.assertEqual((self.root/'app/build.gradle.kts').read_text().count('org.example:audio:1.2.3'),1)

    def test_reject_version_mismatch_without_edit(self):
        fake_signal(self.root);p=self.root/'app/build.gradle.kts';before=p.read_bytes()
        (self.root/'app/build/hq-gain/ringrtc-version.txt').write_text('9.0.0')
        with self.assertRaises(ValueError):CUSTOM['install'](self.root)
        self.assertEqual(p.read_bytes(),before)

    def test_reject_dependency_code_without_edit(self):
        fake_signal(self.root);p=self.root/'app/build.gradle.kts';before=p.read_bytes()
        (self.root/'app/build/hq-gain/ringrtc-direct-dependencies.txt').write_text('evil:lib:1"); exec("x')
        with self.assertRaises(ValueError):CUSTOM['install'](self.root)
        self.assertEqual(p.read_bytes(),before)

    def test_missing_native_library_rejected(self):
        p=self.root/'bad.aar'
        with zipfile.ZipFile(p,'w') as z:z.writestr('jni/arm64-v8a/libringrtc.so',fake_elf('arm64-v8a'))
        with self.assertRaises(ValueError):CUSTOM['aar_abis'](p)

    def test_wrong_elf_architecture_rejected(self):
        p=self.root/'bad.aar'
        with zipfile.ZipFile(p,'w') as z:
            for n in ('libringrtc.so','libringrtc_rffi.so'):z.writestr('jni/arm64-v8a/'+n,fake_elf('x86'))
        with self.assertRaises(ValueError):CUSTOM['aar_abis'](p)

    def checkpoint(self):
        d=self.root/'checkpoint';d.mkdir()
        pins=json.loads((ROOT/'tools/rnnoise/versions.json').read_text())
        fake_aar(d/HANDOFF['AAR'])
        (d/'ringrtc-version.txt').write_text(pins['ringrtc_version']+'\n')
        (d/'ringrtc-direct-dependencies.txt').write_text('')
        (d/'provenance.json').write_text(json.dumps({'pins':pins,'archs':'arm64','control_sha256':HANDOFF['control_hash'](ROOT)}))
        self.rehash(d)
        return d

    def rehash(self,d):
        (d/'SHA256SUMS.json').write_text(json.dumps({n:HANDOFF['sha256'](d/n) for n in HANDOFF['FILES']}))

    def test_checkpoint_accepts_empty_direct_deps(self):
        self.assertEqual(HANDOFF['verify'](self.checkpoint(),ROOT)['archs'],'arm64')

    def test_checkpoint_detects_metadata_tampering(self):
        d=self.checkpoint();(d/'ringrtc-version.txt').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):HANDOFF['verify'](d,ROOT)

    def test_checkpoint_rejects_wrong_control_even_with_valid_checksums(self):
        d=self.checkpoint();p=d/'provenance.json';m=json.loads(p.read_text());m['control_sha256']='0'*64;p.write_text(json.dumps(m));self.rehash(d)
        with self.assertRaisesRegex(ValueError,'different source pins'):HANDOFF['verify'](d,ROOT)

    def test_apk_rejects_advertised_abi_without_ringrtc(self):
        folder=self.root/'app/build/outputs/apk/github/prod/release';folder.mkdir(parents=True)
        (folder/'output-metadata.json').write_text(json.dumps({'variantName':'githubProdRelease','elements':[{'filters':[],'outputFile':'universal.apk'}]}))
        p=folder/'universal.apk'
        with zipfile.ZipFile(p,'w') as z:
            for n in ('libringrtc.so','libringrtc_rffi.so'):z.writestr('lib/arm64-v8a/'+n,fake_elf('arm64-v8a'))
            z.writestr('lib/x86/libunrelated.so',fake_elf('x86'))
            z.writestr('assets/rnnoise-LICENSE.txt','notice')
        with self.assertRaises(ValueError):APK['select'](self.root,'arm64')

    def test_ci_caps_preserve_r8_flags(self):
        p=self.root/'gradle.properties'
        p.write_text('org.gradle.jvmargs=-Xmx12g -Xms256m -Dcom.android.tools.r8.deterministicdebugging=true -XX:hashCode=3\nkotlin.daemon.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m\n')
        CI['configure'](self.root,7000)
        text=p.read_text();self.assertIn('-Dcom.android.tools.r8.deterministicdebugging=true',text)
        self.assertIn('-XX:hashCode=3',text);self.assertNotIn('-Xmx12g',text)
        self.assertIn('org.gradle.workers.max=1',text)

    def test_arch_selection_can_be_reapplied_and_restored(self):
        p=self.root/'bin/build-aar.py';p.parent.mkdir()
        p.write_text("ARCHS = ['arm', 'arm64', 'x86', 'x64']\nninja_args = ['third_party/siso/cipd/siso', 'ninja', '-C', webrtc_output_dir] + NINJA_TARGETS\n")
        ARCH['configure'](self.root,'arm64',2);ARCH['configure'](self.root,'arm64',2)
        self.assertEqual(p.read_text().count("'-j', '2'"),1)
        ARCH['configure'](self.root,'all',4)
        self.assertIn("ARCHS = ['arm', 'arm64', 'x86', 'x64']",p.read_text())


if __name__=='__main__':unittest.main(verbosity=2)
