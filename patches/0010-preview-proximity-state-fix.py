#!/usr/bin/env python3
"""Fix three UI-state issues on top of patches 0001..0009.

1) 1:1 maximize swaps the main and small video views. Both small previews
   support tap-to-expand; the expanded remote preview can swap back or switch
   the local camera. Stock focused/blurred presentation is bypassed for swaps.
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
REMOTE_PIP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableRemoteVideoRenderer.kt"


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
                        "\n  @Volatile\n  protected var hqBluetoothAudioEnabled = false\n",
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
    if "signalCallManager.proximityOverride" in text or "swappedRemoteExpanded" in text:
        die("CallScreen.kt already appears to contain 0010")

    text = replace_once(text,
        "      isProximitySensorEnabled = callScreenState.proximityOverride ?: (callControlsState.audioOutput == WebRtcAudioOutput.HANDSET),\n",
        "      isProximitySensorEnabled = org.thoughtcrime.securesms.dependencies.AppDependencies.signalCallManager.proximityOverride\n"
        "        ?: (callControlsState.audioOutput == WebRtcAudioOutput.HANDSET),\n",
        "proximity UI source of truth")

    old = '''        val oneToOneSwapEligible = showSelfPreviewInCall &&
          !callControlsState.isGroupCall &&
          localParticipant.isVideoEnabled &&
          callParticipantsPagerState.callParticipants.size == 1
        val oneToOneSwapActive = oneToOneSwapEligible &&
          localRenderState == WebRtcLocalRenderState.FOCUSED
        val oneToOneRemoteParticipant = if (oneToOneSwapActive) {
          callParticipantsPagerState.callParticipants.first()
        } else {
          null
        }
        val layoutLocalRenderState = when {
          oneToOneSwapActive -> WebRtcLocalRenderState.SMALL_RECTANGLE
          !showSelfPreviewInCall -> WebRtcLocalRenderState.GONE
          else -> localRenderState
        }
'''
    new = '''        val singleRemoteParticipant = callParticipantsPagerState.callParticipants.singleOrNull()
        val oneToOneSwapEligible = !callControlsState.isGroupCall &&
          !callScreenState.isLocalScreenSharing &&
          !localParticipant.isScreenSharing &&
          localParticipant.isVideoEnabled &&
          singleRemoteParticipant != null &&
          !singleRemoteParticipant.isScreenSharing
        val oneToOneSwapActive = showSelfPreviewInCall &&
          oneToOneSwapEligible &&
          localRenderState == WebRtcLocalRenderState.FOCUSED
        val oneToOneRemoteParticipant = if (oneToOneSwapActive) {
          singleRemoteParticipant
        } else {
          null
        }
        var swappedRemoteExpanded by remember(oneToOneSwapActive, oneToOneRemoteParticipant?.callParticipantId) {
          mutableStateOf(false)
        }
        val layoutLocalRenderState = when {
          oneToOneSwapActive -> {
            if (swappedRemoteExpanded) {
              WebRtcLocalRenderState.EXPANDED
            } else {
              WebRtcLocalRenderState.SMALL_RECTANGLE
            }
          }

          !showSelfPreviewInCall -> WebRtcLocalRenderState.GONE
          else -> localRenderState
        }
'''
    text = replace_once(text, old, new, "true swap layout with expandable remote preview")

    # 0008 already puts the local video in the main slot during a swap. Keep
    # that renderer: mapping FOCUSED to a preview size prevents stock focus blur.
    old = '''              MoveableRemoteVideoRenderer(
                remoteParticipant = swappedRemote,
                onSwapClick = onLocalPictureInPictureFocusClicked,
                modifier = Modifier.fillMaxSize()
              )
'''
    new = '''              MoveableRemoteVideoRenderer(
                remoteParticipant = swappedRemote,
                expanded = swappedRemoteExpanded,
                onClick = { swappedRemoteExpanded = !swappedRemoteExpanded },
                isMoreThanOneCameraAvailable = localParticipant.isMoreThanOneCameraAvailable,
                onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged,
                onSwapClick = onLocalPictureInPictureFocusClicked,
                modifier = Modifier.fillMaxSize()
              )
'''
    return replace_once(text, old, new, "remote preview controls act on the local camera")


def patch_remote_renderer(text: str) -> str:
    text = replace_once(text, "import androidx.compose.material3.Icon\n",
                        "import androidx.compose.material3.Icon\nimport androidx.compose.material3.IconButton\n",
                        "remote preview IconButton import")
    text = replace_once(text, "import androidx.compose.ui.res.stringResource\n",
                        "import androidx.compose.ui.res.painterResource\nimport androidx.compose.ui.res.stringResource\n",
                        "remote preview camera icon import")
    text = replace_once(text, "  remoteParticipant: CallParticipant,\n",
                        "  remoteParticipant: CallParticipant,\n"
                        "  expanded: Boolean,\n"
                        "  onClick: () -> Unit,\n"
                        "  isMoreThanOneCameraAvailable: Boolean,\n"
                        "  onToggleCameraDirectionClick: () -> Unit,\n",
                        "remote preview controls")
    text = replace_once(text,
                        "  val baseSize = rememberSelfPipSize(WebRtcLocalRenderState.SMALL_RECTANGLE)\n",
                        "  val previewRenderState = if (expanded) {\n"
                        "    WebRtcLocalRenderState.EXPANDED\n"
                        "  } else {\n"
                        "    WebRtcLocalRenderState.SMALL_RECTANGLE\n"
                        "  }\n"
                        "  val cornerSize = if (expanded) {\n"
                        "    CallScreenMetrics.ExpandedRendererCornerSize\n"
                        "  } else {\n"
                        "    CallScreenMetrics.OverflowParticipantRendererCornerSize\n"
                        "  }\n"
                        "  val baseSize = rememberSelfPipSize(previewRenderState)\n",
                        "stock compact and expanded preview sizes")
    text = replace_once(text,
                        "        .clip(RoundedCornerShape(16.dp))\n",
                        "        .clip(RoundedCornerShape(cornerSize))\n"
                        "        .clickable(onClick = onClick)\n",
                        "tap to expand or collapse remote preview")
    old = '''      Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier
          .align(Alignment.TopEnd)
          .padding(8.dp)
          .size(36.dp)
          .background(color = MaterialTheme.colorScheme.secondaryContainer, shape = CircleShape)
          .clickable(onClick = onSwapClick)
      ) {
        Icon(
          imageVector = ImageVector.vectorResource(CoreUiR.drawable.symbol_maximize_24),
          tint = MaterialTheme.colorScheme.onSecondaryContainer,
          contentDescription = stringResource(R.string.MoveableLocalVideoRenderer__swap_video),
          modifier = Modifier.size(20.dp)
        )
      }
'''
    new = '''      if (expanded) {
        IconButton(
          onClick = onSwapClick,
          modifier = Modifier
            .align(Alignment.TopEnd)
            .padding(8.dp)
            .size(48.dp)
            .background(color = MaterialTheme.colorScheme.secondaryContainer, shape = CircleShape)
        ) {
          Icon(
            imageVector = ImageVector.vectorResource(CoreUiR.drawable.symbol_maximize_24),
            tint = MaterialTheme.colorScheme.onSecondaryContainer,
            contentDescription = stringResource(R.string.MoveableLocalVideoRenderer__swap_video),
            modifier = Modifier.size(24.dp)
          )
        }

        if (isMoreThanOneCameraAvailable) {
          IconButton(
            onClick = onToggleCameraDirectionClick,
            modifier = Modifier
              .align(Alignment.BottomEnd)
              .padding(10.dp)
              .size(48.dp)
              .background(color = MaterialTheme.colorScheme.secondaryContainer, shape = CircleShape)
          ) {
            Icon(
              painter = painterResource(R.drawable.symbol_switch_24),
              tint = MaterialTheme.colorScheme.onSecondaryContainer,
              contentDescription = stringResource(R.string.SwitchCameraButton__switch_camera_direction),
              modifier = Modifier.size(24.dp)
            )
          }
        }
      }
'''
    return replace_once(text, old, new, "expanded swap-back and local camera buttons")



patched_lock = patch_lock_manager(read(LOCK_MANAGER))
patched_manager = patch_signal_call_manager(read(SIGNAL_CALL_MANAGER))
patched_audio = patch_signal_audio_manager(read(SIGNAL_AUDIO_MANAGER))
patched_active = patch_active_call_manager(read(ACTIVE_CALL_MANAGER))
patched_mediator = patch_compose_mediator(read(COMPOSE_MEDIATOR))
patched_call_screen = patch_call_screen(read(CALL_SCREEN))
patched_remote_pip = patch_remote_renderer(read(REMOTE_PIP))

write(LOCK_MANAGER, patched_lock)
write(SIGNAL_CALL_MANAGER, patched_manager)
write(SIGNAL_AUDIO_MANAGER, patched_audio)
write(ACTIVE_CALL_MANAGER, patched_active)
write(COMPOSE_MEDIATOR, patched_mediator)
write(CALL_SCREEN, patched_call_screen)
write(REMOTE_PIP, patched_remote_pip)

print("0010-preview-proximity-state-fix: proximity switch now reflects the live LockManager override")
print("0010-preview-proximity-state-fix: HQ Bluetooth switch now restores from the live SignalAudioManager state")
print("0010-preview-proximity-state-fix: PiP/UI recreation no longer causes visual-only temporary-toggle resets")
print("0010-preview-proximity-state-fix: 1:1 maximize now fully swaps main and small video views")
print("0010-preview-proximity-state-fix: remote preview expands with swap-back and local camera controls")
