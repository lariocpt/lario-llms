"""Activate the single-slot registry only after matching native/long validation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arcB70.single_vision import build_registry
from shared import modelctl
from shared.serving.catalog import profiles, render_backend, legacy_routes
from shared.serving.state import Store, state_directory
from shared.serving.control import operate


def migrate(receipt, native_only=False):
    proof = json.loads(receipt.read_text())
    if (proof.get('status') != 'passed-native-allocation-text-vision-tools-smoke'
            or (not native_only and (not (proof.get('long_context') or {}).get('passed')
                or proof['long_context']['prompt_tokens'] < 500000))):
        raise RuntimeError('Native vision/tools and full-window retrieval receipt required')
    old = json.loads((ROOT / 'arcB70/models.json').read_text())
    candidate = build_registry(old)
    model = next(iter(candidate['models'].values()))
    # The tested command must contain every final model argument verbatim.
    tested = proof['command']
    start = tested.index('-m')
    if tested[0] != candidate['binary'] or tested[start:start+len(model['args'])] != model['args']:
        raise RuntimeError('Validation command does not match the candidate')
    state = operate('arcB70', 'status')
    if old == candidate:
        print(json.dumps({'status': 'already-configured', 'state': state['state'], 'profile': next(iter(profiles(candidate)))}))
        return
    if state['busy'] or state['requests'] or state['draining'] or state['loading_profile']:
        raise RuntimeError('B70 must be idle and unpaused')
    backup = Path.home() / '.local/state/gpu-migration' / ('b70-before-' + str(time.time_ns()))
    backup.mkdir(parents=True)
    registry_path = ROOT / 'arcB70/models.json'
    previous = registry_path.read_text()
    (backup / 'models.json').write_text(previous)
    selection = modelctl.selection(old)
    operate('arcB70', 'pause')
    try:
        modelctl.assert_idle(old)
        resident = next((p for p in profiles(old).values() if p['model'] == state['model']), None)
        if resident:
            operate('arcB70', 'unload', resident['id'])
        subprocess.run(['systemctl', '--user', 'stop', 'arcB70.service', 'lario-admission@arcB70.service'], check=True)
        model['validation'] = ('native-allocation-vision-tools-passed; full-window-quality-pending' if native_only
                               else 'native-vision-tools-and-synthetic-500k-retrieval-passed')
        candidate['deployment_status'] = 'active'
        modelctl.atomic(registry_path, json.dumps(candidate, indent=2)+'\n')
        key = next(iter(candidate['models']))
        modelctl.save_selection(candidate, key, 'single-vision-512k')
        modelctl.atomic(ROOT/candidate['config'], render_backend(candidate))
        store = Store(state_directory(candidate), {})
        old_policy = store.get('policy')
        (backup/'policy.json').write_text(json.dumps(old_policy, indent=2))
        store.change(legacy=legacy_routes(candidate, key, 'single-vision-512k'),
                     disabled=[item for item in old_policy['disabled'] if item in profiles(candidate)])
        store.close()
        subprocess.run(['systemctl', '--user', 'start', 'arcB70.service', 'lario-admission@arcB70.service'], check=True)
        for _ in range(30):
            try:
                modelctl.api(candidate, '/health')
                ready = operate('arcB70', 'status')
                if ready['state'] in ('reconciling', 'hardware_unavailable'):
                    time.sleep(1)
                    continue
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('New B70 gateway did not start')
        operate('arcB70', 'resume')
        profile = next(iter(profiles(candidate)))
        operate('arcB70', 'activate', profile)
        for _ in range(180):
            ready = operate('arcB70', 'status')
            if ready['profile_id'] == profile and ready['state'] == 'ready':
                break
            if ready.get('last_error') and not ready.get('loading_profile'):
                raise RuntimeError('B70 profile activation failed')
            time.sleep(1)
        else:
            raise RuntimeError('B70 profile did not become ready')
        print(json.dumps({'status': 'activated', 'profile': profile, 'backup': str(backup)}))
    except BaseException:
        subprocess.run(['systemctl', '--user', 'stop', 'arcB70.service', 'lario-admission@arcB70.service'])
        modelctl.atomic(registry_path, previous)
        modelctl.save_selection(old, *selection)
        modelctl.atomic(ROOT/old['config'], render_backend(old))
        store = Store(state_directory(old), {})
        store.change(legacy=legacy_routes(old, *selection))
        store.close()
        subprocess.run(['systemctl', '--user', 'start', 'arcB70.service', 'lario-admission@arcB70.service'], check=True)
        for _ in range(30):
            try:
                operate('arcB70', 'resume')
                break
            except OSError:
                time.sleep(1)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--native-only', action='store_true', help='Explicitly enable after native smoke, retaining provisional extended-context status')
    args = parser.parse_args()
    migrate(args.receipt, args.native_only)
