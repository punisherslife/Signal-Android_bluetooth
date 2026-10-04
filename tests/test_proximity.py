#!/usr/bin/env python3
"""Compile the generated LockManager/ProximityLock against explicit Android fakes.

Usage: python3 tests/test_proximity.py <patched-Signal-root>
Checks lock flags and route/override transitions; real device sensor QA is separate.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
SOURCE = Path(sys.argv[1]) / 'app/src/main/java'
BASE = 'org/thoughtcrime/securesms/webrtc/locks/'
FAKES = {
'android/content/Context.java': '''package android.content;
public class Context {
  public static final String POWER_SERVICE="power", WIFI_SERVICE="wifi";
  public final android.os.PowerManager pm = new android.os.PowerManager();
  public final android.net.wifi.WifiManager wm = new android.net.wifi.WifiManager();
  public Object getSystemService(String name) { return name.equals(POWER_SERVICE) ? pm : wm; }
}''',
'android/os/PowerManager.java': '''package android.os;
public class PowerManager {
  public static final int SCREEN_BRIGHT_WAKE_LOCK=1, ACQUIRE_CAUSES_WAKEUP=2,
      PARTIAL_WAKE_LOCK=4, PROXIMITY_SCREEN_OFF_WAKE_LOCK=8, RELEASE_FLAG_WAIT_FOR_NO_PROXIMITY=16;
  public final java.util.Map<String, WakeLock> locks = new java.util.HashMap<>();
  public boolean supported = true;
  public boolean isWakeLockLevelSupported(int level) { return supported; }
  public WakeLock newWakeLock(int flags, String tag) {
    WakeLock lock = new WakeLock(flags); locks.put(tag, lock); return lock;
  }
  public static class WakeLock {
    public final int flags;
    public int releaseFlags=-1;
    public boolean held;
    public WakeLock(int flags) { this.flags=flags; }
    public void setReferenceCounted(boolean counted) {}
    public void acquire() { held=true; }
    public void release() { release(0); }
    public void release(int flags) { held=false; releaseFlags=flags; }
    public boolean isHeld() { return held; }
  }
}''',
'android/net/wifi/WifiManager.java': '''package android.net.wifi;
public class WifiManager {
  public static final int WIFI_MODE_FULL_HIGH_PERF=1;
  public WifiLock createWifiLock(int mode, String tag) { return new WifiLock(); }
  public static class WifiLock {
    public void setReferenceCounted(boolean counted) {}
    public void acquire() {}
    public void release() {}
  }
}''',
'androidx/annotation/Nullable.java': 'package androidx.annotation; public @interface Nullable {}',
'org/signal/core/util/logging/Log.java': '''package org.signal.core.util.logging;
public class Log {
  public static String tag(Class<?> type) { return type.getSimpleName(); }
  public static void d(String tag, String text) {}
}''',
'ProximityTest.java': '''import android.content.Context;
import android.os.PowerManager;
import org.thoughtcrime.securesms.webrtc.locks.LockManager;
import static org.thoughtcrime.securesms.webrtc.locks.LockManager.PhoneState.*;
public class ProximityTest {
  static void check(boolean ok, String what) { if (!ok) throw new AssertionError(what); }
  public static void main(String[] args) {
    Context c = new Context(); LockManager m = new LockManager(c);
    PowerManager.WakeLock p = c.pm.locks.get("signal:proximity");
    m.onAudioRouteChanged(true, false); m.updatePhoneState(IN_CALL);
    check(p.held && m.isProximityEnabled(), "handset automatic on");
    m.onAudioRouteChanged(false, true);
    check(!p.held && !m.isProximityEnabled() && p.releaseFlags==0, "headphones release immediately");
    m.updatePhoneState(IN_CALL);
    check(!p.held && !m.isProximityEnabled(), "late handset state must not reactivate sensor");
    m.updatePhoneState(IN_HANDS_FREE_CALL);
    check(!p.held, "hands-free automatic off");
    m.setProximityOverride(true);
    check(p.held && m.isProximityEnabled(), "manual headphone override on");
    m.onAudioRouteChanged(false, false);
    check(p.held && Boolean.TRUE.equals(m.getProximityOverride()), "same route preserves manual choice");
    m.setProximityOverride(false);
    check(!p.held && p.releaseFlags==0 && !m.isProximityEnabled(), "manual off immediate");
    m.setProximityOverride(true); m.onAudioRouteChanged(false, true);
    check(!p.held && m.getProximityOverride()==null, "wired to Bluetooth resets override");
    m.updatePhoneState(IN_CALL); m.onAudioRouteChanged(true, true);
    check(p.held && m.isProximityEnabled(), "return to handset");
    m.updatePhoneState(IN_VIDEO);
    check(!p.held && p.releaseFlags==0 && !m.isProximityEnabled(), "video automatic off");
    m.setProximityOverride(true);
    check(p.held, "manual video override on");
    m.updatePhoneState(IDLE);
    check(!p.held && p.releaseFlags==PowerManager.RELEASE_FLAG_WAIT_FOR_NO_PROXIMITY,
          "stock hangup wait-for-far retained");
    check(m.getProximityOverride()==null && !m.isProximityEnabled(), "hangup clears override");
    m.updatePhoneState(INTERACTIVE);
    check(c.pm.locks.get("signal:full-wakeup").held, "upstream interactive wake-up retained");
    m.onAudioRouteChanged(false, true); m.updatePhoneState(IN_CALL);
    check(c.pm.locks.get("signal:full").held && !c.pm.locks.get("signal:full-wakeup").held,
          "in-call full lock must not acquire wake-up lock");
    m.updatePhoneState(IDLE);
    Context unsupported = new Context(); unsupported.pm.supported=false;
    LockManager noSensor = new LockManager(unsupported);
    noSensor.updatePhoneState(IN_CALL); noSensor.setProximityOverride(false); noSensor.updatePhoneState(IDLE);
    System.out.println("PASS: real lock classes; route/late-state/manual/video/hangup flags; upstream wake-up behavior; unsupported sensor");
  }
}''',
}
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    for rel, text in FAKES.items():
        p=root/rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(text)
    for name in ('LockManager.java', 'ProximityLock.java'):
        p=root/BASE/name;p.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(SOURCE/BASE/name,p)
    java = shutil.which('java')
    compiler = [shutil.which('javac')] if shutil.which('javac') else [java, '-m', 'jdk.compiler/com.sun.tools.javac.Main']
    subprocess.run(compiler + ['-d',str(root/'classes')] + [str(p) for p in root.rglob('*.java')], check=True)
    subprocess.run([java,'-cp',str(root/'classes'),'ProximityTest'],check=True)
