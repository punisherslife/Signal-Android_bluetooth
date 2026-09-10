#!/usr/bin/env python3
'''Make Signal's existing maximize/zoom button perform a true 1:1 visual swap.

Layering:
  0001..0007
  0008-one-to-one-video-swap.py  (this file)

Behavior in a normal one-to-one call:
- the small self-view exposes Signal's existing maximize/zoom button
- pressing that button makes local video the main view
- the remote participant becomes the small draggable PiP
- pressing the maximize/zoom button on the remote PiP swaps back
- tapping the small video tile itself does not expand/swap in 1:1 calls
- group calls retain Signal's existing expand/focus behavior
- this changes presentation only; it does not switch front/back capture cameras or media tracks
'''
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CALL_SCREEN = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt"
LOCAL_PIP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableLocalVideoRenderer.kt"
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
                onClick = {
                  if (!oneToOneSwapEligible) {
                    onLocalPictureInPictureClicked()
                  }
                },
                onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged,
                onFocusLocalParticipantClick = onLocalPictureInPictureFocusClicked,
                oneToOneSwapEnabled = oneToOneSwapEligible,
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


def patch_local_pip(text: str) -> str:
    if "fun MoveableLocalVideoRenderer(" not in text or "val showFocusButton =" not in text:
        die("MoveableLocalVideoRenderer.kt is not the expected v8.25.2 shape")
    if "oneToOneSwapEnabled" in text:
        die("MoveableLocalVideoRenderer.kt already appears to contain patch 0008")

    old_signature = '''  onClick: () -> Unit,
  onToggleCameraDirectionClick: () -> Unit,
  onFocusLocalParticipantClick: () -> Unit,
  modifier: Modifier = Modifier
) {
'''
    new_signature = '''  onClick: () -> Unit,
  onToggleCameraDirectionClick: () -> Unit,
  onFocusLocalParticipantClick: () -> Unit,
  oneToOneSwapEnabled: Boolean = false,
  modifier: Modifier = Modifier
) {
'''
    text = replace_once(text, old_signature, new_signature, "local PiP signature")

    old_show = '''    val clip by animateClip(localRenderState)
    val showFocusButton = localRenderState == WebRtcLocalRenderState.EXPANDED || isFocused
'''
    new_show = '''    val clip by animateClip(localRenderState)
    val showFocusButton = oneToOneSwapEnabled ||
      localRenderState == WebRtcLocalRenderState.EXPANDED ||
      isFocused
'''
    text = replace_once(text, old_show, new_show, "local PiP maximize visibility")

    old_description = '''            contentDescription = stringResource(
              if (isFocused) {
                R.string.MoveableLocalVideoRenderer__shrink_local_video
              } else {
                R.string.MoveableLocalVideoRenderer__expand_local_video
              }
            )
'''
    new_description = '''            contentDescription = stringResource(
              if (oneToOneSwapEnabled) {
                R.string.MoveableLocalVideoRenderer__swap_video
              } else if (isFocused) {
                R.string.MoveableLocalVideoRenderer__shrink_local_video
              } else {
                R.string.MoveableLocalVideoRenderer__expand_local_video
              }
            )
'''
    return replace_once(text, old_description, new_description, "local PiP accessibility label")


def patch_strings(text: str) -> str:
    if "MoveableLocalVideoRenderer__swap_video" in text:
        die("strings.xml already appears to contain patch 0008")
    old = '''    <!-- Content description for button to expand local video to focused/full-screen mode -->
    <string name="MoveableLocalVideoRenderer__expand_local_video">Expand local video</string>
'''
    new = old + '''    <!-- Content description for button that swaps the main and small video views in a one-to-one call -->
    <string name="MoveableLocalVideoRenderer__swap_video">Swap video views</string>
'''
    return replace_once(text, old, new, "swap-video accessibility string")


REMOTE_PIP_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.components.webrtc.v2

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.displayCutoutPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
          contentDescription = stringResource(R.string.MoveableLocalVideoRenderer__swap_video)
        )
      }
    }
  }
}
'''

if REMOTE_PIP.exists():
    die(f"remote PiP renderer already exists: {REMOTE_PIP}")

patched_call_screen = patch_call_screen(read(CALL_SCREEN))
patched_local_pip = patch_local_pip(read(LOCAL_PIP))
patched_strings = patch_strings(read(STRINGS))

write(CALL_SCREEN, patched_call_screen)
write(LOCAL_PIP, patched_local_pip)
write(REMOTE_PIP, REMOTE_PIP_SOURCE)
write(STRINGS, patched_strings)

print("0008-one-to-one-video-swap: 1:1 maximize/zoom button now swaps local and remote presentation")
print("0008-one-to-one-video-swap: remote PiP gets the same maximize/swap control to swap back")
print("0008-one-to-one-video-swap: tile taps no longer expand/swap in 1:1; group-call behavior is unchanged")
