#!/usr/bin/env python3
"""Compile and execute transformed Java bytecode; test AAR failure atomicity."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
 'android/media/AudioTrack.java': '''package android.media;
public class AudioTrack {
  public boolean failPlay;
  public void play() { if (failPlay) throw new IllegalStateException("fixture"); }
  public void stop() {}
  public void release() {}
}''',
 'org/webrtc/audio/WebRtcAudioTrack.java': '''package org.webrtc.audio;
import android.media.AudioTrack;
public class WebRtcAudioTrack {
  public final AudioTrack track = new AudioTrack();
  public void start() { track.play(); }
  public void end() { track.stop(); track.release(); }
  public void failedStart() { try { track.play(); } catch (RuntimeException e) { track.release(); } }
}''',
 'org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.java': '''package org.thoughtcrime.securesms.webrtc.audio;
import android.media.AudioTrack;
public class HqCallGainBridge {
  public static AudioTrack current;
  public static int registrations;
  public static void registerAudioTrack(AudioTrack t) { current=t; registrations++; }
  public static void unregisterAudioTrack(AudioTrack t) { if(current==t) current=null; }
}''',
 'Harness.java': '''import org.webrtc.audio.WebRtcAudioTrack;
import org.thoughtcrime.securesms.webrtc.audio.HqCallGainBridge;
public class Harness {
  public static void main(String[] args) {
    WebRtcAudioTrack t = new WebRtcAudioTrack(); t.start();
    if (HqCallGainBridge.current != t.track || HqCallGainBridge.registrations != 1) throw new AssertionError("register");
    t.end(); if (HqCallGainBridge.current != null) throw new AssertionError("cleanup");
    t.track.failPlay=true; t.failedStart();
    if (HqCallGainBridge.current != null || HqCallGainBridge.registrations != 2) throw new AssertionError("failed play cleanup");
    System.out.println("PASS: valid gain-hook bytecode; play/stop/release and failed-play cleanup");
  }
}''',
}
with tempfile.TemporaryDirectory() as t:
    tmp=Path(t);src=tmp/'src';classes=tmp/'classes';classes.mkdir()
    for name,content in SOURCES.items():
        p=src/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
    compiler=[shutil.which('javac')] if shutil.which('javac') else ['java','-m','jdk.compiler/com.sun.tools.javac.Main']
    subprocess.run(compiler+['-d',str(classes)]+[str(p) for p in src.rglob('*.java')],check=True)
    original=tmp/'input.aar';jar=tmp/'classes.jar'
    with zipfile.ZipFile(jar,'w') as z:
        for p in classes.rglob('*.class'):z.write(p,p.relative_to(classes).as_posix())
    with zipfile.ZipFile(original,'w') as z:z.write(jar,'classes.jar')
    env=os.environ.copy()
    env['TMPDIR']=str(tmp)
    if not shutil.which('javac'):
        binpath=tmp/'bin';binpath.mkdir();p=binpath/'javac'
        p.write_text('#!/bin/sh\nexec java -m jdk.compiler/com.sun.tools.javac.Main "$@"\n');p.chmod(0o755)
        env['PATH']=str(binpath)+os.pathsep+env['PATH']
    script=ROOT/'tools/hq-gain/patch-ringrtc-aar.sh';out=tmp/'patched.aar'
    subprocess.run(['bash',str(script),str(original),str(out)],check=True,env=env,text=True)
    with zipfile.ZipFile(out) as z:jar.write_bytes(z.read('classes.jar'))
    subprocess.run(['java','-Xverify:all','-cp',str(jar),'Harness'],check=True)
    stable=out.read_bytes()
    r=subprocess.run(['bash',str(script),str(out),str(out)],env=env,capture_output=True)
    assert r.returncode != 0 and out.read_bytes() == stable, 'repeat patch must fail without changing output'
    with zipfile.ZipFile(tmp/'empty.aar','w') as z:z.writestr('not-the-target.txt','fixture')
    r=subprocess.run(['bash',str(script),str(tmp/'empty.aar'),str(out)],env=env,capture_output=True)
    assert r.returncode != 0 and out.read_bytes() == stable, 'missing target must preserve existing output'
    with zipfile.ZipFile(original,'r') as z:origjar=z.read('classes.jar')
    with zipfile.ZipFile(tmp/'duplicate.aar','w') as z:
        z.writestr('classes.jar',origjar);z.writestr('libs/second.jar',origjar)
    r=subprocess.run(['bash',str(script),str(tmp/'duplicate.aar'),str(out)],env=env,capture_output=True)
    assert r.returncode != 0 and out.read_bytes() == stable, 'duplicate target must preserve output'
    print('PASS: repeat/missing/duplicate hooks rejected; existing AAR preserved')
