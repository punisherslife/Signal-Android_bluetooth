#!/usr/bin/env python3
'''Use Signal's SECOND-stage maximize button as a true 1:1 local/remote visual swap.

Layering:
  0001..0007
  0008-one-to-one-video-swap.py  (this file)

Signal's original local-preview flow is intentionally preserved:
- initial small self preview is unchanged
- camera-switch control/behavior is unchanged
- tapping the small self preview still performs Signal's normal first expansion
- only the maximize/focus button that appears AFTER expansion becomes the 1:1 swap action
- when swapped, the remote participant is the small draggable PiP; its compact maximize button swaps back
- swapping back returns the local preview to the expanded state
- group calls keep Signal's original expand/focus behavior
'''
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CALL_SCREEN = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt"
VIEW_MODEL = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/WebRtcCallViewModel.kt"
REMOTE_PIP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableRemoteVideoRenderer.kt"
STRINGS = ROOT / "app/src/main/res/values/strings.xml"


def die(message: str) -> None:
    raise RuntimeError(f"0008-one-to-one-video-swap: {message}")


def read(path: Path) -> str:
    if not path.exists():
        die(f"missing expected Signal source file: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_call_screen(text: str) -> str:
    if "MoveableLocalVideoRenderer(" not in text or "CallParticipantsPager(" not in text:
        die("CallScreen.kt is not the expected v8.25.2 shape")
    if "oneToOneSwapActive" in text or "MoveableRemoteVideoRenderer(" in text:
        die("CallScreen.kt already appears to contain patch 0008")

    old_before_layout = '''        val contextMenuAnchorOffset = remember(longPressWindowOffset, anchorWindowOrigin, density) {
          val local = longPressWindowOffset - anchorWindowOrigin
          with(density) { IntOffset(local.x.toInt(), local.y.toInt()) }
        }

        CallElementsLayout(
'''
    new_before_layout = '''        val contextMenuAnchorOffset = remember(longPressWindowOffset, anchorWindowOrigin, density) {
          val local = longPressWindowOffset - anchorWindowOrigin
          with(density) { IntOffset(local.x.toInt(), local.y.toInt()) }
        }
        val oneToOneSwapEligible = !callControlsState.isGroupCall &&
          localParticipant.isVideoEnabled &&
          callParticipantsPagerState.callParticipants.size == 1
        val oneToOneSwapActive = oneToOneSwapEligible &&
          localRenderState == WebRtcLocalRenderState.FOCUSED
        val oneToOneRemoteParticipant = if (oneToOneSwapActive) {
          callParticipantsPagerState.callParticipants.first()
        } else {
          null
        }
        val layoutLocalRenderState = if (oneToOneSwapActive) {
          WebRtcLocalRenderState.SMALL_RECTANGLE
        } else {
          localRenderState
        }

        CallElementsLayout(
'''
    text = replace_once(text, old_before_layout, new_before_layout, "CallElementsLayout prelude")

    old_pager = '''              CallParticipantsPager(
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
    new_pager = '''              if (oneToOneSwapActive) {
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
    text = replace_once(text, old_pager, new_pager, "1:1 main renderer")

    old_pip = '''          pictureInPictureSlot = {
            MoveableLocalVideoRenderer(
              localParticipant = localParticipant,
              localRenderState = localRenderState,
              savedLocalParticipantLandscape = savedLocalParticipantLandscape,
              onClick = onLocalPictureInPictureClicked,
              onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged,
              onFocusLocalParticipantClick = onLocalPictureInPictureFocusClicked,
              modifier = Modifier.fillMaxSize()
            )
          },
'''
    new_pip = '''          pictureInPictureSlot = {
            val swappedRemote = oneToOneRemoteParticipant
            if (swappedRemote != null) {
              MoveableRemoteVideoRenderer(
                remoteParticipant = swappedRemote,
                onSwapClick = onLocalPictureInPictureFocusClicked,
                modifier = Modifier.fillMaxSize()
              )
            } else {
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
          },
'''
    text = replace_once(text, old_pip, new_pip, "PiP renderer swap")

    old_audio = '''          audioIndicatorSlot = {
            if (callParticipantsPagerState.callParticipants.size == 1) {
              val participant = callParticipantsPagerState.callParticipants.first()
              ParticipantAudioIndicator(
                participant = participant,
                selfPipMode = SelfPipMode.NOT_SELF_PIP
              )
            }
          },
'''
    new_audio = '''          audioIndicatorSlot = {
            if (!oneToOneSwapActive && callParticipantsPagerState.callParticipants.size == 1) {
              val participant = callParticipantsPagerState.callParticipants.first()
              ParticipantAudioIndicator(
                participant = participant,
                selfPipMode = SelfPipMode.NOT_SELF_PIP
              )
            }
          },
'''
    text = replace_once(text, old_audio, new_audio, "remote audio indicator")

    old_layout_state = '''          bottomInset = padding,
          bottomSheetWidth = CallScreenMetrics.SheetMaxWidth,
          localRenderState = localRenderState,
          modifier = Modifier.fillMaxSize()
'''
    new_layout_state = '''          bottomInset = padding,
          bottomSheetWidth = CallScreenMetrics.SheetMaxWidth,
          localRenderState = layoutLocalRenderState,
          modifier = Modifier.fillMaxSize()
'''
    return replace_once(text, old_layout_state, new_layout_state, "CallElementsLayout localRenderState")


def patch_view_model(text: str) -> str:
    if "returnOneToOneSwapToExpanded" in text:
        die("WebRtcCallViewModel.kt already appears to contain patch 0008")
    old = '''  fun onLocalPictureInPictureFocusClicked() {
    participantsState.update {
      CallParticipantsState.setFocusLocalParticipant(it, it.localRenderState != WebRtcLocalRenderState.FOCUSED)
    }
  }
'''
    new = '''  fun onLocalPictureInPictureFocusClicked() {
    participantsState.update {
      val returnOneToOneSwapToExpanded = it.groupCallState == WebRtcViewModel.GroupCallState.IDLE &&
        it.allRemoteParticipants.size == 1 &&
        it.localParticipant.isVideoEnabled &&
        it.localRenderState == WebRtcLocalRenderState.FOCUSED

      if (returnOneToOneSwapToExpanded) {
        val unfocused = CallParticipantsState.setFocusLocalParticipant(it, false)
        CallParticipantsState.setExpanded(unfocused, true)
      } else {
        CallParticipantsState.setFocusLocalParticipant(it, it.localRenderState != WebRtcLocalRenderState.FOCUSED)
      }
    }
  }
'''
    return replace_once(text, old, new, "1:1 swap-back state")


def patch_strings(text: str) -> str:
    if "MoveableLocalVideoRenderer__swap_video" in text:
        die("strings.xml already appears to contain patch 0008")
    old = '''    <!-- Content description for button to expand local video to focused/full-screen mode -->
    <string name="MoveableLocalVideoRenderer__expand_local_video">Expand local video</string>
'''
    new = old + '''    <!-- Content description for the second-stage button that swaps main and small video views in a one-to-one call -->
    <string name="MoveableLocalVideoRenderer__swap_video">Swap video views</string>
'''
    return replace_once(text, old, new, "swap-video accessibility string")


REMOTE_PIP_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.components.webrtc.v2

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.displayCutoutPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import org.thoughtcrime.securesms.R
import org.thoughtcrime.securesms.components.webrtc.WebRtcLocalRenderState
import org.thoughtcrime.securesms.events.CallParticipant
import org.signal.core.ui.R as CoreUiR

/** Small draggable remote view shown while local video is the main view in a 1:1 call. */
@Composable
fun MoveableRemoteVideoRenderer(
  remoteParticipant: CallParticipant,
  onSwapClick: () -> Unit,
  modifier: Modifier = Modifier
) {
  val baseSize = rememberSelfPipSize(WebRtcLocalRenderState.SMALL_RECTANGLE)
  val remoteAspectRatio = rememberParticipantAspectRatio(remoteParticipant.videoSink)
  val configurationLandscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
  val isVideoLandscape = remoteAspectRatio?.let { it > 1f } ?: configurationLandscape
  val targetSize = remember(baseSize, isVideoLandscape) {
    if (isVideoLandscape) {
      DpSize(baseSize.height, baseSize.width)
    } else {
      baseSize
    }
  }
  val state = remember { PictureInPictureState(initialContentSize = targetSize) }
  state.animateTo(targetSize)

  PictureInPicture(
    state = state,
    modifier = Modifier
      .fillMaxSize()
      .then(modifier)
      .statusBarsPadding()
      .displayCutoutPadding()
      .padding(16.dp)
  ) {
    Box(
      modifier = Modifier
        .fillMaxSize()
        .clip(RoundedCornerShape(16.dp))
    ) {
      RemoteParticipantContent(
        participant = remoteParticipant,
        renderInPip = true,
        raiseHandAllowed = false,
        onInfoMoreInfoClick = null,
        modifier = Modifier.fillMaxSize()
      )

      Box(
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
    }
  }
}
'''

if REMOTE_PIP.exists():
    die(f"remote PiP renderer already exists: {REMOTE_PIP}")

patched_call_screen = patch_call_screen(read(CALL_SCREEN))
patched_view_model = patch_view_model(read(VIEW_MODEL))
patched_strings = patch_strings(read(STRINGS))

write(CALL_SCREEN, patched_call_screen)
write(VIEW_MODEL, patched_view_model)
write(REMOTE_PIP, REMOTE_PIP_SOURCE)
write(STRINGS, patched_strings)

print("0008-one-to-one-video-swap: stock small preview/camera-switch/first expansion behavior preserved")
print("0008-one-to-one-video-swap: second-stage maximize button performs 1:1 local/remote visual swap")
print("0008-one-to-one-video-swap: compact remote PiP button swaps back to the expanded local preview")
