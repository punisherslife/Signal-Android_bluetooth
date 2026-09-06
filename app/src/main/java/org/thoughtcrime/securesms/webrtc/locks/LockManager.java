package org.thoughtcrime.securesms.webrtc.locks;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.PowerManager;

import org.signal.core.util.logging.Log;

/**
 * Maintains wake lock state.
 *
 * @author Stuart O. Anderson
 */
public class LockManager {

  private static final String TAG = Log.tag(LockManager.class);

  private final PowerManager.WakeLock fullLock;
  private final PowerManager.WakeLock partialLock;
  private final WifiManager.WifiLock  wifiLock;
  private final ProximityLock         proximityLock;

  private boolean     proximityDisabled = false;
  private Boolean     proximityOverride = null;
  private PhoneState  currentPhoneState = PhoneState.IDLE;

  public enum PhoneState {
    IDLE,
    PROCESSING,  //used when the phone is active but before the user should be alerted.
    INTERACTIVE,
    IN_CALL,
    IN_HANDS_FREE_CALL,
    IN_VIDEO
  }

  private enum LockState {
    FULL,
    PARTIAL,
    SLEEP,
    PROXIMITY
  }

  public LockManager(Context context) {
    PowerManager pm = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
    fullLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP, "signal:full");
    partialLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "signal:partial");
    proximityLock = new ProximityLock(pm);

    WifiManager wm = (WifiManager) context.getSystemService(Context.WIFI_SERVICE);
    wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "signal:wifi");

    fullLock.setReferenceCounted(false);
    partialLock.setReferenceCounted(false);
    wifiLock.setReferenceCounted(false);
  }

  private void updateInCallLockState() {
    if (!proximityDisabled) {
      setLockState(LockState.PROXIMITY);
    } else {
      setLockState(LockState.FULL);
    }
  }

  public synchronized void setProximityOverride(boolean enabled) {
    proximityOverride = enabled;
    applyPhoneState(currentPhoneState);
  }

  public synchronized void clearProximityOverride() {
    proximityOverride = null;
    applyPhoneState(currentPhoneState);
  }

  public synchronized void updatePhoneState(PhoneState state) {
    currentPhoneState = state;
    applyPhoneState(state);
  }

  private void applyPhoneState(PhoneState state) {
    switch(state) {
      case IDLE:
        proximityOverride = null;
        proximityDisabled = false;
        setLockState(LockState.SLEEP);
        break;
      case PROCESSING:
        setLockState(LockState.PARTIAL);
        break;
      case INTERACTIVE:
        setLockState(LockState.FULL);
        break;
      case IN_HANDS_FREE_CALL:
        if (Boolean.TRUE.equals(proximityOverride)) {
          proximityDisabled = false;
          updateInCallLockState();
        } else {
          proximityDisabled = true;
          setLockState(LockState.PARTIAL);
        }
        break;
      case IN_VIDEO:
        proximityDisabled = !Boolean.TRUE.equals(proximityOverride);
        updateInCallLockState();
        break;
      case IN_CALL:
        proximityDisabled = Boolean.FALSE.equals(proximityOverride);
        updateInCallLockState();
        break;
    }
  }

  private synchronized void setLockState(LockState newState) {
    switch(newState) {
      case FULL:
        fullLock.acquire();
        partialLock.acquire();
        wifiLock.acquire();
        proximityLock.release();
        break;
      case PARTIAL:
        partialLock.acquire();
        wifiLock.acquire();
        fullLock.release();
        proximityLock.release();
        break;
      case SLEEP:
        fullLock.release();
        partialLock.release();
        wifiLock.release();
        proximityLock.release();
        break;
      case PROXIMITY:
        partialLock.acquire();
        proximityLock.acquire();
        wifiLock.acquire();
        fullLock.release();
        break;
      default:
        throw new IllegalArgumentException("Unhandled Mode: " + newState);
    }
    Log.d(TAG, "Entered Lock State: " + newState);
  }
}
