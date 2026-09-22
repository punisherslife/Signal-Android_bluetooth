#!/usr/bin/env python3
"""Check the four-job dependency graph and shell syntax. Requires PyYAML."""
from pathlib import Path
import subprocess
import yaml

ROOT=Path(__file__).resolve().parents[1]
workflow=yaml.load((ROOT/'.github/workflows/hq-gain10-rnnoise-little-resilient-4job.yml').read_text(),Loader=yaml.BaseLoader)
assert set(workflow['on'])=={'workflow_dispatch'}
assert workflow['permissions']=={'contents':'read'}
assert 'concurrency' not in workflow
jobs=workflow['jobs'];assert list(jobs)==['native_ringrtc','signal_ci','screenshots','release_apk']
assert set(jobs['release_apk']['needs'])=={'native_ringrtc','signal_ci','screenshots'}
assert jobs['signal_ci']['needs']==jobs['screenshots']['needs']=='native_ringrtc'
assert any(s.get('uses','').startswith('actions/upload-artifact@') and s.get('with',{}).get('name')=='rnnoise-little-native-${{ github.run_id }}' for s in jobs['native_ringrtc']['steps'])
blocks=0
for name,job in jobs.items():
    assert any(s.get('uses')=='./.github/actions/prepare-signal' for s in job['steps'])
    if name!='native_ringrtc':
        assert any('native-handoff.py install' in s.get('run','') for s in job['steps'])
    for s in job['steps']:
        if 'run' in s:
            assert '${{' not in s['run'], 'Pass workflow inputs through env, not shell interpolation'
            assert 'ciRemote' not in s['run']
            subprocess.run(['bash','-n'],input=s['run'],text=True,check=True);blocks+=1
composite=yaml.load((ROOT/'.github/actions/prepare-signal/action.yml').read_text(),Loader=yaml.BaseLoader)
for s in composite['runs']['steps']:
    if 'run' in s:
        subprocess.run(['bash','-n'],input=s['run'],text=True,check=True);blocks+=1
    if 'uses' in s and s['uses'].startswith('actions/checkout@'):
        assert s['with']['repository']=='signalapp/Signal-Android'
        assert s['with']['ref']=='${{ inputs.commit }}'
print(f'PASS: four jobs; both release gates; manual only; pinned checkout; {blocks} shell blocks')
