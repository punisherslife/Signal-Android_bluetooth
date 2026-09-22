#!/usr/bin/env python3
"""Fix three UI-state issues on top of patches 0001..0009.

1) 1:1 video swap keeps Signal's stock MoveableLocalVideoRenderer in the
   focused/swapped state so the normal self-preview controls, including the
   switch-camera button, remain available.
2) The proximity switch displays the real call-scoped LockManager override,
   so recreating the Compose/PiP UI cannot visually reset the toggle while the
   sensor override is still active.
3) The HQ Bluetooth switch restores its UI from the live SignalAudioManager
   state when the call UI is recreated, instead of blindly resetting OFF on
   the first LaunchedEffect(audioOutput) after returning from PiP.

The existing reset semantics are preserved:
- proximity override clears on logical audio-route changes (patch 0002)
- HQ Bluetooth clears on real logical audio-route changes (patch 0001)
- both are call-scoped and clear with call/audio-manager shutdown
- no persistence is added to either temporary toggle
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
LOCK_MANAGER = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/locks/LockManager.java"
SIGNAL_CALL_MANAGER = ROOT / "app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java"
CALL_SCREEN = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt"
COMPOSE_MEDIATOR = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/ComposeCallScreenMediator.kt"
ACTIVE_CALL_MANAGER = ROOT / "app/src/main/java/org/thoughtcrime/securesms/service/webrtc/ActiveCallManager.kt"
SIGNAL_AUDIO_MANAGER = ROOT / "app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/SignalAudioManager.kt"


def die(message: str) -> None:
    raise RuntimeError(f"0010-preview-proximity-state-fix: {message}")


def read(path: Path) -> str:
    if not path.exists():
        die(f"missing expected Signal source file: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_lock_manager(text: str) -> str:
    if "getProximityOverride()" in text:
        die("LockManager.java already contains the 0010 proximity getter")

    old = '''  public synchronized void setProximityOverride(boolean enabled) {
    proximityOverride = enabled;
    applyPhoneState(currentPhoneState);
  }

  public synchronized void clearProximityOverride() {
'''
    new = '''  public synchronized void setProximityOverride(boolean enabled) {
    proximityOverride = enabled;
    applyPhoneState(currentPhoneState);
  }

  public synchronized Boolean getProximityOverride() {
    return proximityOverride;
  }

  public synchronized void clearProximityOverride() {
'''
    return replace_once(text, old, new, "LockManager proximity getter")


def patch_signal_call_manager(text: str) -> str:
    if "public Boolean getProximityOverride()" in text:
        die("SignalCallManager.java already contains the 0010 proximity getter")

    old = '''  public void setProximityOverride(boolean enabled) {
    lockManager.setProximityOverride(enabled);
  }

  public void clearProximityOverride() {
'''
    new = '''  public void setProximityOverride(boolean enabled) {
    lockManager.setProximityOverride(enabled);
  }

  public Boolean getProximityOverride() {
    return lockManager.getProximityOverride();
  }

  public void clearProximityOverride() {
'''
    return replace_once(text, old, new, "SignalCallManager proximity getter")

def patch_signal_audio_manager(text: str) -> str:
    if "fun isHighQualityBluetoothAudioEnabled()" in text:
        die("SignalAudioManager.kt already contains the 0010 HQ-state getter")

    # Patch 0004 adds a gain-controller call inside the setter. Match only the
    # declaration so the getter does not depend on an obsolete pre-0004 body.
    old = '''  protected abstract fun selectAudioDevice(recipientId: RecipientId?, device: Int, isId: Boolean)
'''
    new = '''  protected abstract fun selectAudioDevice(recipientId: RecipientId?, device: Int, isId: Boolean)

  fun isHighQualityBluetoothAudioEnabled(): Boolean {
    return hqBluetoothAudioEnabled
  }

'''
    text = replace_once(text, old, new, "SignalAudioManager HQ-state getter")
    return replace_once(text, "  protected var hqBluetoothAudioEnabled = false\n",
                        "  @Volatile\n  protected var hqBluetoothAudioEnabled = false\n",
                        "cross-thread HQ-state visibility")


def patch_active_call_manager(text: str) -> str:
    if "fun isHighQualityBluetoothAudioEnabled(): Boolean" in text:
        die("ActiveCallManager.kt already contains the 0010 HQ-state getter")

    old = '''    @JvmStatic
    fun sendAudioManagerCommand(context: Context, command: AudioManagerCommand) {
      activeCallManagerLock.withLock {
        if (activeCallManager == null) {
          activeCallManager = ActiveCallManager(context)
        }
        activeCallManager!!.sendAudioCommand(command)
      }
    }
'''
    new = '''    @JvmStatic
    fun sendAudioManagerCommand(context: Context, command: AudioManagerCommand) {
      activeCallManagerLock.withLock {
        if (activeCallManager == null) {
          activeCallManager = ActiveCallManager(context)
        }
        activeCallManager!!.sendAudioCommand(command)
      }
    }

    @JvmStatic
    fun isHighQualityBluetoothAudioEnabled(): Boolean {
      return activeCallManagerLock.withLock {
        activeCallManager?.signalAudioManager?.isHighQualityBluetoothAudioEnabled() ?: false
      }
    }
'''
    return replace_once(text, old, new, "ActiveCallManager HQ-state getter")


def patch_compose_mediator(text: str) -> str:
    marker = "highQualityBluetoothAudioEnabled = ActiveCallManager.isHighQualityBluetoothAudioEnabled()"
    if marker in text:
        die("ComposeCallScreenMediator.kt already appears to contain the 0010 HQ-state restore")

    old = '''      LaunchedEffect(callControlsState.audioOutput) {
        callScreenViewModel.callScreenState.update {
          it.copy(
            highQualityBluetoothAudioEnabled = false,
            proximityOverride = null
          )
        }
      }
'''
    new = '''      LaunchedEffect(callControlsState.audioOutput) {
        callScreenViewModel.callScreenState.update {
          it.copy(
            highQualityBluetoothAudioEnabled = ActiveCallManager.isHighQualityBluetoothAudioEnabled(),
            proximityOverride = AppDependencies.signalCallManager.proximityOverride
          )
        }
      }
'''
    return replace_once(text, old, new, "restore live temporary-toggle state after UI recreation")


def patch_call_screen(text: str) -> str:
    required = [
        "showSelfPreviewInCall by InCallSelfPreviewPreference.shown.collectAsState()",
        "oneToOneSwapActive",
        "oneToOneRemoteParticipant",
        "MoveableRemoteVideoRenderer(",
        "LargeLocalVideoRenderer(",
    ]
    for marker in required:
        if marker not in text:
            die(f"CallScreen.kt is missing expected 0008/0009 marker: {marker}")
    if "signalCallManager.proximityOverride" in text:
        die("CallScreen.kt already appears to contain 0010")

    # Display the real LockManager override rather than only the Compose copy.
    old_proximity = '''      isProximitySensorEnabled = callScreenState.proximityOverride ?: (callControlsState.audioOutput == WebRtcAudioOutput.HANDSET),
'''
    new_proximity = '''      isProximitySensorEnabled = org.thoughtcrime.securesms.dependencies.AppDependencies.signalCallManager.proximityOverride
        ?: (callControlsState.audioOutput == WebRtcAudioOutput.HANDSET),
'''
    text = replace_once(text, old_proximity, new_proximity, "proximity UI source of truth")

    # When self preview is visible, let Signal see the real local render state.
    # In particular FOCUSED must remain FOCUSED so Signal's normal focused
    # MoveableLocalVideoRenderer path is used (camera switch included).
    old_layout_state = '''        val layoutLocalRenderState = when {
          oneToOneSwapActive -> WebRtcLocalRenderState.SMALL_RECTANGLE
          !showSelfPreviewInCall -> WebRtcLocalRenderState.GONE
          else -> localRenderState
        }
'''
    new_layout_state = '''        val layoutLocalRenderState = if (showSelfPreviewInCall) {
          localRenderState
        } else {
          WebRtcLocalRenderState.GONE
        }
'''
    text = replace_once(text, old_layout_state, new_layout_state, "focused self-preview layout state")

    # Stop replacing Signal's participant pager with a bare LargeLocalVideoRenderer.
    # CallElementsLayout will blur the pager while FOCUSED, exactly as stock Signal
    # does for the focused self preview.
    old_grid = '''              if (oneToOneSwapActive) {
                LargeLocalVideoRenderer(
                  localParticipant = localParticipant,
                  modifier = Modifier
                    .fillMaxSize()
                    .clickable(
                      onClick = {
                        scope.launch {
                          callScreenController.handleEvent(CallScreenController.Event.TOGGLE_CONTROLS)
                        }
                      },
                      enabled = !callControlsState.skipHiddenState
                    )
                )
              } else {
                CallParticipantsPager(
                  callParticipantsPagerState = callParticipantsPagerState,
                  pagerState = callScreenController.callParticipantsVerticalPagerState,
                  modifier = Modifier
                    .fillMaxSize()
                    .clickable(
                      onClick = {
                        scope.launch {
                          callScreenController.handleEvent(CallScreenController.Event.TOGGLE_CONTROLS)
                        }
                      },
                      enabled = !callControlsState.skipHiddenState
                    ),
                  onTap = {
                    if (!callControlsState.skipHiddenState) {
                      scope.launch {
                        callScreenController.handleEvent(CallScreenController.Event.TOGGLE_CONTROLS)
                      }
                    }
                  },
                  onParticipantLongPress = { participant, windowOffset ->
                    longPressedParticipantId = participant.callParticipantId
                    longPressWindowOffset = windowOffset
                  }
                )
              }
'''
    new_grid = '''              CallParticipantsPager(
                callParticipantsPagerState = callParticipantsPagerState,
                pagerState = callScreenController.callParticipantsVerticalPagerState,
                modifier = Modifier
                  .fillMaxSize()
                  .clickable(
                    onClick = {
                      scope.launch {
                        callScreenController.handleEvent(CallScreenController.Event.TOGGLE_CONTROLS)
                      }
                    },
                    enabled = !callControlsState.skipHiddenState
                  ),
                onTap = {
                  if (!callControlsState.skipHiddenState) {
                    scope.launch {
                      callScreenController.handleEvent(CallScreenController.Event.TOGGLE_CONTROLS)
                    }
                  }
                },
                onParticipantLongPress = { participant, windowOffset ->
                  longPressedParticipantId = participant.callParticipantId
                  longPressWindowOffset = windowOffset
                }
              )
'''
    text = replace_once(text, old_grid, new_grid, "restore stock participant pager during swap")

    # Always use Signal's stock local renderer whenever the self preview is shown.
    # During a swap its FOCUSED state becomes the large self preview, retaining
    # SelfPipContent and therefore the standard switch-camera button. The remote
    # participant is then layered above it as the small draggable PiP.
    old_pip = '''            val swappedRemote = oneToOneRemoteParticipant
            if (swappedRemote != null) {
              MoveableRemoteVideoRenderer(
                remoteParticipant = swappedRemote,
                onSwapClick = onLocalPictureInPictureFocusClicked,
                modifier = Modifier.fillMaxSize()
              )
            } else if (showSelfPreviewInCall) {
              MoveableLocalVideoRenderer(
                localParticipant = localParticipant,
                localRenderState = localRenderState,
                savedLocalParticipantLandscape = savedLocalParticipantLandscape,
                onClick = onLocalPictureInPictureClicked,
                onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged,
                onFocusLocalParticipantClick = onLocalPictureInPictureFocusClicked,
                modifier = Modifier.fillMaxSize()
              )
            }
'''
    new_pip = '''            if (showSelfPreviewInCall) {
              Box(modifier = Modifier.fillMaxSize()) {
                MoveableLocalVideoRenderer(
                  localParticipant = localParticipant,
                  localRenderState = localRenderState,
                  savedLocalParticipantLandscape = savedLocalParticipantLandscape,
                  onClick = onLocalPictureInPictureClicked,
                  onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged,
                  onFocusLocalParticipantClick = onLocalPictureInPictureFocusClicked,
                  modifier = Modifier.fillMaxSize()
                )

                val swappedRemote = oneToOneRemoteParticipant
                if (swappedRemote != null) {
                  MoveableRemoteVideoRenderer(
                    remoteParticipant = swappedRemote,
                    onSwapClick = onLocalPictureInPictureFocusClicked,
                    modifier = Modifier.fillMaxSize()
                  )
                }
              }
            }
'''
    text = replace_once(text, old_pip, new_pip, "stock focused local preview + remote PiP")

    return text


patched_lock = patch_lock_manager(read(LOCK_MANAGER))
patched_manager = patch_signal_call_manager(read(SIGNAL_CALL_MANAGER))
patched_audio = patch_signal_audio_manager(read(SIGNAL_AUDIO_MANAGER))
patched_active = patch_active_call_manager(read(ACTIVE_CALL_MANAGER))
patched_mediator = patch_compose_mediator(read(COMPOSE_MEDIATOR))
patched_call_screen = patch_call_screen(read(CALL_SCREEN))

write(LOCK_MANAGER, patched_lock)
write(SIGNAL_CALL_MANAGER, patched_manager)
write(SIGNAL_AUDIO_MANAGER, patched_audio)
write(ACTIVE_CALL_MANAGER, patched_active)
write(COMPOSE_MEDIATOR, patched_mediator)
write(CALL_SCREEN, patched_call_screen)

print("0010-preview-proximity-state-fix: proximity switch now reflects the live LockManager override")
print("0010-preview-proximity-state-fix: HQ Bluetooth switch now restores from the live SignalAudioManager state")
print("0010-preview-proximity-state-fix: PiP/UI recreation no longer causes visual-only temporary-toggle resets")
print("0010-preview-proximity-state-fix: swapped local video uses Signal's stock focused self-preview renderer")
print("0010-preview-proximity-state-fix: stock switch-camera control remains available while swapped")
