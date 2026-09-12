#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"
cd "$ROOT"

# Core routing / gain lifecycle.
grep -F 'hqBluetoothAudioEnabled' app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/SignalAudioManager.kt >/dev/null
grep -F 'private const val MAX_BOOST_DB = 10f' app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt >/dev/null
grep -F 'gainAboveUnityDb' app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt >/dev/null
grep -F 'fun registerAudioTrack(track: AudioTrack)' app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt >/dev/null
grep -F 'fun unregisterAudioTrack(track: AudioTrack)' app/src/main/java/org/thoughtcrime/securesms/webrtc/audio/HqCallGainBridge.kt >/dev/null

# Live strong noise suppression UI + call-manager bridge.
test -s app/src/main/java/org/thoughtcrime/securesms/service/webrtc/StrongNoiseSuppressionPreference.kt
grep -F 'setStrongNoiseSuppressionEnabled' app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SignalCallManager.java >/dev/null
grep -F 'AppDependencies.signalCallManager.setStrongNoiseSuppressionEnabled' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt >/dev/null
grep -F 'CallOverflowPopupWindow__strong_noise_suppression' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt >/dev/null

# System PiP, 1:1 swap, and independent in-call self-preview behavior.
test -s app/src/main/java/org/thoughtcrime/securesms/service/webrtc/SystemPipSelfPreviewPreference.kt
grep -F 'hideSelfPreviewInSystemPip' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/PictureInPictureCallScreen.kt >/dev/null
grep -F 'CompactSystemPipAudioIndicator' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/PictureInPictureCallScreen.kt >/dev/null
grep -F 'MediaProjection continues independently' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/WebRtcCallViewModel.kt >/dev/null
test -s app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/MoveableRemoteVideoRenderer.kt
grep -F 'oneToOneSwapActive' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt >/dev/null
grep -F 'onClick = onLocalPictureInPictureClicked' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt >/dev/null
grep -F 'onSwapClick = onLocalPictureInPictureFocusClicked' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt >/dev/null
grep -F 'returnOneToOneSwapToExpanded' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/WebRtcCallViewModel.kt >/dev/null
test -s app/src/main/java/org/thoughtcrime/securesms/service/webrtc/InCallSelfPreviewPreference.kt
grep -F 'SelfPreviewMenu()' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt >/dev/null
grep -F 'showSelfPreviewInCall by InCallSelfPreviewPreference.shown.collectAsState()' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/CallScreen.kt >/dev/null
! grep -F 'SystemPipSelfPreviewToggle()' app/src/main/java/org/thoughtcrime/securesms/components/webrtc/v2/AdditionalActionsPopup.kt >/dev/null

git diff --check
echo "optimized-kit: patched Signal source shape validated"
