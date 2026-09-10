#!/usr/bin/env python3
"""Add a persistent toggle that hides the local camera preview only in Android system PiP.

Layering:
  0001..0005 existing call patches
  0006-hq-call-gain-10db-compressed.py
  0007-hide-self-camera-system-pip.py  (this file)

The camera remains enabled/transmitting. This changes only the local self-preview that Signal
normally overlays in the bottom-right of PictureInPictureCallScreen. When hidden, the large
self-preview tile is removed and only Signal's existing AudioIndicator may appear, at 24 dp,
when muted or speaking.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
POPUP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt"
SYSTEM_PIP = ROOT / "app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/PictureInPictureCallScreen.kt"
PREF = ROOT / "app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SystemPipSelfPreviewPreference.kt"
STRINGS = ROOT / "app/src/main/res/values/strings.xml"


def die(message: str) -> None:
    raise RuntimeError(f"0007-hide-self-camera-system-pip: {message}")


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


def add_imports(text: str, imports: list[str], label: str) -> str:
    lines = text.splitlines()
    import_indexes = [i for i, line in enumerate(lines) if line.startswith("import ")]
    if not import_indexes:
        die(f"{label}: import block not found")

    start = import_indexes[0]
    end = import_indexes[-1] + 1
    current = {line for line in lines[start:end] if line.startswith("import ")}
    current |= {f"import {item}" for item in imports}

    def import_order(line: str) -> tuple[int, str]:
        path = line.removeprefix("import ")
        if " as " in path:
            return (4, path)
        if path.startswith("java."):
            return (1, path)
        if path.startswith("javax."):
            return (2, path)
        if path.startswith("kotlin."):
            return (3, path)
        return (0, path)

    lines[start:end] = sorted(current, key=import_order)
    return "\n".join(lines) + "\n"


def patch_popup(text: str) -> str:
    if "StrongNoiseSuppressionToggle()" not in text or "HqCallGainSlider()" not in text:
        die("AdditionalActionsPopup.kt does not look like patches 0004+0005 were applied")
    if "SystemPipSelfPreviewToggle" in text or "SystemPipSelfPreviewPreference" in text:
        die("AdditionalActionsPopup.kt already appears to contain patch 0007")

    text = add_imports(
        text,
        ["org.thoughtcrime.securesms.service.webrtc.SystemPipSelfPreviewPreference"],
        "AdditionalActionsPopup.kt",
    )

    text = replace_once(
        text,
        "    StrongNoiseSuppressionToggle()\n",
        "    StrongNoiseSuppressionToggle()\n    SystemPipSelfPreviewToggle()\n",
        "strong-NS menu anchor",
    )

    marker = "@Composable\nprivate fun StrongNoiseSuppressionToggle() {\n"
    toggle = '''@Composable
private fun SystemPipSelfPreviewToggle() {
  var hidden by remember {
    mutableStateOf(SystemPipSelfPreviewPreference.isHidden())
  }

  CallScreenMenuToggle(
    title = stringResource(R.string.CallOverflowPopupWindow__hide_self_camera_in_pip),
    checked = hidden,
    onCheckedChange = { value ->
      SystemPipSelfPreviewPreference.setHidden(value)
      hidden = value
    }
  )
}

@Composable
private fun StrongNoiseSuppressionToggle() {
'''
    return replace_once(text, marker, toggle, "StrongNoiseSuppressionToggle insertion point")


def patch_system_pip(text: str) -> str:
    if "PictureInPictureSelfPip(" not in text or "PIP_METRICS_SELF_PORTRAIT_WIDTH" not in text:
        die("PictureInPictureCallScreen.kt is not the expected v8.25.2 shape")
    if "hideSelfPreviewInSystemPip" in text or "SystemPipSelfPreviewPreference" in text:
        die("PictureInPictureCallScreen.kt already appears to contain patch 0007")

    text = add_imports(
        text,
        ["org.thoughtcrime.securesms.service.webrtc.SystemPipSelfPreviewPreference"],
        "PictureInPictureCallScreen.kt",
    )

    old_head = '''  Box(
    modifier = Modifier.fillMaxSize()
  ) {
    val remoteParticipant = callParticipantsPagerState.focusedParticipant ?: callParticipantsPagerState.callParticipants.first()
'''
    new_head = '''  Box(
    modifier = Modifier.fillMaxSize()
  ) {
    val hideSelfPreviewInSystemPip = remember {
      SystemPipSelfPreviewPreference.isHidden()
    }
    val remoteParticipant = callParticipantsPagerState.focusedParticipant ?: callParticipantsPagerState.callParticipants.first()
'''
    text = replace_once(text, old_head, new_head, "system PiP preference read")

    old_main = '''    val isFullScreenLocalParticipant = localParticipant.callParticipantId == fullScreenParticipant.callParticipantId

    RemoteParticipantContent(
      participant = fullScreenParticipant,
      renderInPip = true,
      raiseHandAllowed = false,
      onInfoMoreInfoClick = null,
      mirrorVideo = isFullScreenLocalParticipant && !fullScreenParticipant.isScreenSharing,
      modifier = Modifier.fillMaxSize()
    )

'''
    new_main = '''    val isFullScreenLocalParticipant = localParticipant.callParticipantId == fullScreenParticipant.callParticipantId

    if (hideSelfPreviewInSystemPip && isFullScreenLocalParticipant) {
      Box(
        modifier = Modifier
          .fillMaxSize()
          .background(Color.Black)
      )
      AudioIndicator(
        participant = localParticipant,
        modifier = Modifier
          .padding(10.dp)
          .size(24.dp)
          .background(color = MaterialTheme.colorScheme.surface.copy(alpha = 0.7f), shape = CircleShape)
          .padding(5.dp)
          .align(Alignment.BottomEnd)
      )
    } else {
      RemoteParticipantContent(
        participant = fullScreenParticipant,
        renderInPip = true,
        raiseHandAllowed = false,
        onInfoMoreInfoClick = null,
        mirrorVideo = isFullScreenLocalParticipant && !fullScreenParticipant.isScreenSharing,
        modifier = Modifier.fillMaxSize()
      )
    }

'''
    text = replace_once(text, old_main, new_main, "system PiP main local-preview block")

    old_preview = '''    if (!isFullScreenLocalParticipant) {
      val localAspectRatio = rememberParticipantAspectRatio(localParticipant.videoSink)
      val isLocalLandscape = localAspectRatio?.let { it > 1f } ?: savedLocalParticipantLandscape
      val (selfPipWidth, selfPipHeight) = if (isLocalLandscape) {
        PIP_METRICS_SELF_LANDSCAPE_WIDTH to PIP_METRICS_SELF_LANDSCAPE_HEIGHT
      } else {
        PIP_METRICS_SELF_PORTRAIT_WIDTH to PIP_METRICS_SELF_PORTRAIT_HEIGHT
      }

      PictureInPictureSelfPip(
        localParticipant = localParticipant,
        modifier = Modifier
          .padding(10.dp)
          .size(
            width = selfPipWidth,
            height = selfPipHeight
          )
          .align(Alignment.BottomEnd)
      )

      val handRaiseCount = (callParticipantsPagerState.callParticipants + localParticipant).count { it.isHandRaised }
'''
    new_preview = '''    if (!isFullScreenLocalParticipant) {
      if (hideSelfPreviewInSystemPip) {
        AudioIndicator(
          participant = localParticipant,
          modifier = Modifier
            .padding(10.dp)
            .size(24.dp)
            .background(color = MaterialTheme.colorScheme.surface.copy(alpha = 0.7f), shape = CircleShape)
            .padding(5.dp)
            .align(Alignment.BottomEnd)
        )
      } else {
        val localAspectRatio = rememberParticipantAspectRatio(localParticipant.videoSink)
        val isLocalLandscape = localAspectRatio?.let { it > 1f } ?: savedLocalParticipantLandscape
        val (selfPipWidth, selfPipHeight) = if (isLocalLandscape) {
          PIP_METRICS_SELF_LANDSCAPE_WIDTH to PIP_METRICS_SELF_LANDSCAPE_HEIGHT
        } else {
          PIP_METRICS_SELF_PORTRAIT_WIDTH to PIP_METRICS_SELF_PORTRAIT_HEIGHT
        }

        PictureInPictureSelfPip(
          localParticipant = localParticipant,
          modifier = Modifier
            .padding(10.dp)
            .size(
              width = selfPipWidth,
              height = selfPipHeight
            )
            .align(Alignment.BottomEnd)
        )
      }

      val handRaiseCount = (callParticipantsPagerState.callParticipants + localParticipant).count { it.isHandRaised }
'''
    return replace_once(text, old_preview, new_preview, "system PiP self-preview block")


def patch_strings(text: str) -> str:
    if "CallOverflowPopupWindow__hide_self_camera_in_pip" in text:
        die("strings.xml already appears to contain patch 0007")
    old = '    <string name="CallOverflowPopupWindow__strong_noise_suppression">Strong noise suppression</string>\n'
    new = old + '    <string name="CallOverflowPopupWindow__hide_self_camera_in_pip">Hide self camera in PiP</string>\n'
    return replace_once(text, old, new, "system PiP string anchor")


PREF_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.service.webrtc

import android.content.Context
import org.thoughtcrime.securesms.dependencies.AppDependencies

/** Persistent display-only preference for the Android system-PiP self preview. */
object SystemPipSelfPreviewPreference {
  private const val PREFS_NAME = "system_pip_self_preview"
  private const val PREF_HIDDEN = "hidden"

  @JvmStatic
  fun isHidden(): Boolean {
    return preferences().getBoolean(PREF_HIDDEN, false)
  }

  @JvmStatic
  fun setHidden(hidden: Boolean) {
    preferences()
      .edit()
      .putBoolean(PREF_HIDDEN, hidden)
      .apply()
  }

  private fun preferences() = AppDependencies.application
    .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}
'''

if PREF.exists():
    die(f"preference file already exists: {PREF}")

patched_popup = patch_popup(read(POPUP))
patched_system_pip = patch_system_pip(read(SYSTEM_PIP))
patched_strings = patch_strings(read(STRINGS))

write(POPUP, patched_popup)
write(SYSTEM_PIP, patched_system_pip)
write(STRINGS, patched_strings)
write(PREF, PREF_SOURCE)

print("0007-hide-self-camera-system-pip: added persistent Hide self camera in PiP toggle")
print("0007-hide-self-camera-system-pip: camera transmission is unchanged; only system-PiP self preview is hidden")
print("0007-hide-self-camera-system-pip: compact 24dp AudioIndicator remains when muted/speaking")
