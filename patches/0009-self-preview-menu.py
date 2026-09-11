#!/usr/bin/env python3
'''Consolidate self-preview controls into one lightweight submenu.

Layering:
  0001..0008
  0009-self-preview-menu.py  (this file)

Main call overflow menu:
- replaces the top-level "Hide self camera in PiP" toggle with one "Self preview" row
- that row opens a compact secondary menu with:
    * Show in call
    * Show in Picture-in-Picture

Runtime behavior:
- "Show in call" is persistent and defaults ON
- it suppresses only the local self-preview overlay during an active/in-call screen
- pre-join/outgoing framing remains stock
- if the 1:1 local/remote swap is active, the swapped remote PiP remains usable
- "Show in Picture-in-Picture" reuses patch 0007's persistent system-PiP preference
- no camera capture, transmission, WebRTC sink, decoder, or background service is added/changed
'''
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
POPUP = ROOT / 'app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt'
CALL_SCREEN = ROOT / 'app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt'
IN_CALL_PREF = ROOT / 'app/src/main/java/org/thoughtcrime/securesms/service/webrtc/InCallSelfPreviewPreference.kt'
STRINGS = ROOT / 'app/src/main/res/values/strings.xml'


def die(message: str) -> None:
    raise RuntimeError(f'0009-self-preview-menu: {message}')


def read(path: Path) -> str:
    if not path.exists():
        die(f'missing expected Signal source file: {path}')
    return path.read_text(encoding='utf-8')


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f'{label}: expected exactly one match, found {count}')
    return text.replace(old, new, 1)


def add_imports(text: str, imports: list[str], label: str) -> str:
    lines = text.splitlines()
    import_indexes = [i for i, line in enumerate(lines) if line.startswith('import ')]
    if not import_indexes:
        die(f'{label}: import block not found')

    start = import_indexes[0]
    end = import_indexes[-1] + 1
    current = {line for line in lines[start:end] if line.startswith('import ')}
    current |= {f'import {item}' for item in imports}

    def import_order(line: str) -> tuple[int, str]:
        path = line.removeprefix('import ')
        if ' as ' in path:
            return (4, path)
        if path.startswith('java.'):
            return (1, path)
        if path.startswith('javax.'):
            return (2, path)
        if path.startswith('kotlin.'):
            return (3, path)
        return (0, path)

    lines[start:end] = sorted(current, key=import_order)
    return '\n'.join(lines) + '\n'


def patch_popup(text: str) -> str:
    if 'SystemPipSelfPreviewToggle()' not in text or 'SystemPipSelfPreviewPreference' not in text:
        die('AdditionalActionsPopup.kt does not look like patch 0007 was applied')
    if 'SelfPreviewMenu()' in text or 'InCallSelfPreviewPreference' in text:
        die('AdditionalActionsPopup.kt already appears to contain patch 0009')

    text = add_imports(
        text,
        [
            'androidx.compose.material3.DropdownMenu',
            'androidx.compose.material3.DropdownMenuItem',
            'org.thoughtcrime.securesms.service.webrtc.InCallSelfPreviewPreference',
        ],
        'AdditionalActionsPopup.kt',
    )

    text = replace_once(
        text,
        '    SystemPipSelfPreviewToggle()\n',
        '    SelfPreviewMenu()\n',
        'top-level self-preview row',
    )

    old_toggle = '''@Composable
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
'''
    new_menu = '''@Composable
private fun SelfPreviewMenu() {
  var expanded by remember {
    mutableStateOf(false)
  }
  var showInCall by remember {
    mutableStateOf(InCallSelfPreviewPreference.isShown())
  }
  var showInPip by remember {
    mutableStateOf(!SystemPipSelfPreviewPreference.isHidden())
  }

  Box(
    modifier = Modifier.fillMaxWidth()
  ) {
    Row(
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = spacedBy(16.dp),
      modifier = Modifier
        .fillMaxWidth()
        .clip(RoundedCornerShape(18.dp))
        .clickable { expanded = true }
        .padding(horizontal = 16.dp, vertical = 12.dp)
    ) {
      Icon(
        imageVector = ImageVector.vectorResource(R.drawable.symbol_video_24),
        contentDescription = null,
        tint = MaterialTheme.colorScheme.onSurface
      )

      Text(
        text = stringResource(R.string.CallOverflowPopupWindow__self_preview),
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = Modifier.weight(1f)
      )

      Icon(
        imageVector = ImageVector.vectorResource(org.signal.core.ui.R.drawable.symbol_chevron_right_24),
        contentDescription = null,
        tint = MaterialTheme.colorScheme.onSurface
      )
    }

    DropdownMenu(
      expanded = expanded,
      onDismissRequest = { expanded = false }
    ) {
      DropdownMenuItem(
        text = {
          Text(stringResource(R.string.CallOverflowPopupWindow__show_self_preview_in_call))
        },
        trailingIcon = {
          Switch(
            checked = showInCall,
            onCheckedChange = null
          )
        },
        onClick = {
          showInCall = !showInCall
          InCallSelfPreviewPreference.setShown(showInCall)
        }
      )

      DropdownMenuItem(
        text = {
          Text(stringResource(R.string.CallOverflowPopupWindow__show_self_preview_in_pip))
        },
        trailingIcon = {
          Switch(
            checked = showInPip,
            onCheckedChange = null
          )
        },
        onClick = {
          showInPip = !showInPip
          SystemPipSelfPreviewPreference.setHidden(!showInPip)
        }
      )
    }
  }
}
'''
    return replace_once(text, old_toggle, new_menu, 'system PiP top-level toggle -> self-preview submenu')


def patch_call_screen(text: str) -> str:
    if 'oneToOneSwapEligible' not in text or 'oneToOneSwapActive' not in text:
        die('CallScreen.kt does not look like patch 0008 v3 was applied')
    if 'showSelfPreviewInCall' in text or 'InCallSelfPreviewPreference' in text:
        die('CallScreen.kt already appears to contain patch 0009')

    text = add_imports(
        text,
        [
            'androidx.compose.runtime.collectAsState',
            'org.thoughtcrime.securesms.service.webrtc.InCallSelfPreviewPreference',
        ],
        'CallScreen.kt',
    )

    old_state = '''        val oneToOneSwapEligible = !callControlsState.isGroupCall &&
          localParticipant.isVideoEnabled &&
          callParticipantsPagerState.callParticipants.size == 1
        val oneToOneSwapActive = oneToOneSwapEligible &&
          localRenderState == WebRtcLocalRenderState.FOCUSED
'''
    new_state = '''        val showSelfPreviewInCall by InCallSelfPreviewPreference.shown.collectAsState()
        val oneToOneSwapEligible = showSelfPreviewInCall &&
          !callControlsState.isGroupCall &&
          localParticipant.isVideoEnabled &&
          callParticipantsPagerState.callParticipants.size == 1
        val oneToOneSwapActive = oneToOneSwapEligible &&
          localRenderState == WebRtcLocalRenderState.FOCUSED
'''
    text = replace_once(text, old_state, new_state, 'reactive in-call self-preview state')

    old_layout = '''        val layoutLocalRenderState = if (oneToOneSwapActive) {
          WebRtcLocalRenderState.SMALL_RECTANGLE
        } else {
          localRenderState
        }
'''
    new_layout = '''        val layoutLocalRenderState = when {
          oneToOneSwapActive -> WebRtcLocalRenderState.SMALL_RECTANGLE
          !showSelfPreviewInCall -> WebRtcLocalRenderState.GONE
          else -> localRenderState
        }
'''
    text = replace_once(text, old_layout, new_layout, 'hidden-preview layout state')

    old_pip = '''            if (swappedRemote != null) {
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
'''
    new_pip = '''            if (swappedRemote != null) {
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
    return replace_once(text, old_pip, new_pip, 'in-call self-preview renderer suppression')


def patch_strings(text: str) -> str:
    if 'CallOverflowPopupWindow__self_preview' in text:
        die('strings.xml already appears to contain patch 0009')

    old = '    <string name="CallOverflowPopupWindow__hide_self_camera_in_pip">Hide self camera in PiP</string>\n'
    new = '''    <string name="CallOverflowPopupWindow__self_preview">Self preview</string>
    <string name="CallOverflowPopupWindow__show_self_preview_in_call">Show in call</string>
    <string name="CallOverflowPopupWindow__show_self_preview_in_pip">Show in Picture-in-Picture</string>
'''
    return replace_once(text, old, new, 'self-preview strings')


IN_CALL_PREF_SOURCE = r'''/*
 * SPDX-License-Identifier: AGPL-3.0-only
 */

package org.thoughtcrime.securesms.service.webrtc

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.thoughtcrime.securesms.dependencies.AppDependencies

/** Persistent, reactive display-only preference for the in-call local self preview. */
object InCallSelfPreviewPreference {
  private const val PREFS_NAME = "in_call_self_preview"
  private const val PREF_SHOWN = "shown"

  private val mutableShown = MutableStateFlow(
    preferences().getBoolean(PREF_SHOWN, true)
  )

  val shown: StateFlow<Boolean> = mutableShown.asStateFlow()

  @JvmStatic
  fun isShown(): Boolean {
    return mutableShown.value
  }

  @JvmStatic
  fun setShown(shown: Boolean) {
    preferences()
      .edit()
      .putBoolean(PREF_SHOWN, shown)
      .apply()

    mutableShown.value = shown
  }

  private fun preferences() = AppDependencies.application
    .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}
'''

if IN_CALL_PREF.exists():
    die(f'preference file already exists: {IN_CALL_PREF}')

patched_popup = patch_popup(read(POPUP))
patched_call_screen = patch_call_screen(read(CALL_SCREEN))
patched_strings = patch_strings(read(STRINGS))

write(POPUP, patched_popup)
write(CALL_SCREEN, patched_call_screen)
write(STRINGS, patched_strings)
write(IN_CALL_PREF, IN_CALL_PREF_SOURCE)

print('0009-self-preview-menu: one top-level Self preview row replaces the PiP-only toggle')
print('0009-self-preview-menu: submenu contains Show in call + Show in Picture-in-Picture')
print('0009-self-preview-menu: in-call preview hiding is persistent, reactive, and display-only')
print('0009-self-preview-menu: pre-join/outgoing camera framing remains stock')
