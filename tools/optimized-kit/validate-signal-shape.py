#!/usr/bin/env python3
"""Cheap source integration guards, not a replacement for compilation/device QA."""
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path

BASE = 'app/src/main/java/org/thoughtcrime/securesms/'
CHECKS = {
 'webrtc/audio/SignalAudioManager.kt': ['hqBluetoothAudioEnabled', 'HqCallGainBridge.setHqEnabled'],
 'webrtc/audio/HqCallGainBridge.kt': ['private const val MAX_BOOST_DB = 10f', 'gainAboveUnityDb',
     'fun registerAudioTrack(track: AudioTrack)', 'fun unregisterAudioTrack(track: AudioTrack)'],
 'service/webrtc/StrongNoiseSuppressionPreference.kt': ['object StrongNoiseSuppressionPreference'],
 'service/webrtc/SignalCallManager.java': ['setStrongNoiseSuppressionEnabled'],
 'components/webrtc/v2/AdditionalActionsPopup.kt': [
     'AppDependencies.signalCallManager.setStrongNoiseSuppressionEnabled', 'SelfPreviewMenu()',
     'CallOverflowPopupWindow__strong_noise_suppression'],
 'service/webrtc/SystemPipSelfPreviewPreference.kt': ['object SystemPipSelfPreviewPreference'],
 'service/webrtc/InCallSelfPreviewPreference.kt': ['object InCallSelfPreviewPreference'],
 'components/webrtc/v2/PictureInPictureCallScreen.kt': ['hideSelfPreviewInSystemPip', 'CompactSystemPipAudioIndicator'],
 'components/webrtc/v2/MoveableRemoteVideoRenderer.kt': ['onSwapClick', 'RemoteParticipantContent'],
 'components/webrtc/v2/CallScreen.kt': ['oneToOneSwapActive', 'onClick = onLocalPictureInPictureClicked',
     'onSwapClick = onLocalPictureInPictureFocusClicked',
     'showSelfPreviewInCall by InCallSelfPreviewPreference.shown.collectAsState()'],
 'components/webrtc/v2/WebRtcCallViewModel.kt': ['MediaProjection continues independently', 'returnOneToOneSwapToExpanded'],
}
RNNOISE = {
 'webrtc/audio/SignalAudioManager.kt': ['fun isHighQualityBluetoothAudioEnabled(): Boolean', '@Volatile'],
 'webrtc/locks/LockManager.java': ['public synchronized Boolean getProximityOverride()'],
 'service/webrtc/SignalCallManager.java': ['public Boolean getProximityOverride()', 'RNNoise Little'],
 'components/webrtc/v2/ComposeCallScreenMediator.kt': [
     'highQualityBluetoothAudioEnabled = ActiveCallManager.isHighQualityBluetoothAudioEnabled()',
     'proximityOverride = AppDependencies.signalCallManager.proximityOverride'],
 'components/webrtc/v2/CallScreen.kt': ['signalCallManager.proximityOverride',
     'var swappedRemoteExpanded by remember(oneToOneSwapActive, oneToOneRemoteParticipant?.callParticipantId)',
     'val oneToOneSwapActive = showSelfPreviewInCall &&',
     '!callScreenState.isLocalScreenSharing', '!singleRemoteParticipant.isScreenSharing',
     'expanded = swappedRemoteExpanded',
     'onToggleCameraDirectionClick = callScreenControlsListener::onCameraDirectionChanged'],
 'components/webrtc/v2/MoveableRemoteVideoRenderer.kt': ['expanded: Boolean',
     '.clickable(onClick = onClick)', 'if (expanded)', 'onClick = onToggleCameraDirectionClick'],
 'service/webrtc/ActiveCallManager.kt': ['callManager.lockManager.clearProximityOverride()',
     'fun isHighQualityBluetoothAudioEnabled(): Boolean'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path('.'))
    parser.add_argument('--rnnoise', action='store_true', help='Require all ten RNNoise-kit patches')
    args = parser.parse_args()
    checks = {p: list(v) for p, v in CHECKS.items()}
    if args.rnnoise:
        for p, markers in RNNOISE.items():
            checks.setdefault(p, []).extend(markers)
    errors = []
    for rel, markers in checks.items():
        p = args.root / BASE / rel
        if not p.is_file():
            errors.append(f'Missing {p}')
            continue
        text = p.read_text(encoding='utf-8')
        for marker in markers:
            if marker not in text:
                errors.append(f'{rel}: missing {marker!r}')
        forbidden = ['SystemPipSelfPreviewToggle()'] if rel.endswith('AdditionalActionsPopup.kt') else []
        if args.rnnoise and rel.endswith('CallScreen.kt'):
            forbidden += ['oneToOneSwapActive -> WebRtcLocalRenderState.SMALL_RECTANGLE']
        for marker in forbidden:
            if marker in text:
                errors.append(f'{rel}: obsolete code {marker!r}')
    if errors:
        raise SystemExit('\n'.join(errors))
    subprocess.run(['git', '-C', str(args.root), 'diff', '--check'], check=True)
    print('Signal source shape passed (' + ('RNNoise + all ten patches' if args.rnnoise else 'legacy-compatible checks') + ').')


if __name__ == '__main__':
    main()
