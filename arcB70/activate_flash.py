#!/usr/bin/env python3
"""Deploy the tested Flash profile through the existing idle B70 owner only."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles
from shared.serving.control import operate


def main():
    reg = json.loads((ROOT/'arcB70/models.json').read_text())
    modelctl.load_runtime(reg)
    modelctl.assert_not_held(reg)
    report = ROOT/'research/benchmarks/20261027-b70-flash/llama-8k-cpu-experts/result.json'
    receipt = json.loads(report.read_text())
    if receipt['status'] != 'pass' or receipt['verified_context'] != 262144 or receipt['slots'] != 3:
        raise RuntimeError('three-slot validation receipt missing')
    if '--no-op-offload' not in receipt['command']:
        raise RuntimeError('CPU expert computation was not validated')
    flash = next(p for p in profiles(reg).values() if p['model'] == 'qwen38-flash-q4-256k')
    before = operate('arcB70', 'status')
    if before['busy'] or before['requests'] or before['uncertain'] or before['draining']:
        raise RuntimeError('owner must be confirmed idle and unpaused')
    previous = next((p['id'] for p in profiles(reg).values() if p['model'] == before.get('model')), None)
    modelctl.assert_idle(reg)
    operate('arcB70', 'pause')
    try:
        state = operate('arcB70', 'status')
        if state['busy'] or state['requests'] or state['uncertain']:
            raise RuntimeError('work arrived; deployment stopped')
        modelctl.assert_idle(reg)
        if previous:
            operate('arcB70', 'unload', previous)
        subprocess.run(['systemctl', '--user', 'restart', 'arcB70.service'], check=True)
        subprocess.run(['systemctl', '--user', 'restart', 'lario-admission@arcB70.service'], check=True)
        for attempt in range(60):
            try:
                operate('arcB70', 'status')
                break
            except Exception:
                if attempt == 59:
                    raise
                time.sleep(1)
        operate('arcB70', 'resume')
        operate('arcB70', 'enable', flash['id'])
        operate('arcB70', 'activate', flash['id'])
        def check(_):
            body = {'model': flash['id'], 'messages': [{'role': 'user', 'content': 'Return exactly 7'}],
                    'temperature': 0, 'max_tokens': 32, 'cache_prompt': True,
                    'chat_template_kwargs': {'enable_thinking': False}}
            req = urllib.request.Request('http://127.0.0.1:11437/v1/chat/completions',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Authorization': 'Bearer '+os.environ['LARIO_AUXILIARY_KEY']})
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.load(response)
            if result['choices'][0]['message']['content'].strip() != '7':
                raise RuntimeError('public gateway inference failed')
            return {'correct': True, 'usage': result.get('usage')}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            checks = list(pool.map(check, range(3)))
        result = {'profile_id': flash['id'], 'backend_id': flash['backend_id'],
                  'gateway_checks': checks, 'status': 'passed', 'state': operate('arcB70', 'status')}
        (report.parent.parent/'deployed.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({'status': 'passed', 'profile': flash['id'], 'gateway_correct': len(checks)}))
    except BaseException:
        try:
            operate('arcB70', 'resume')
            state = operate('arcB70', 'status')
            if previous and not state['busy'] and not state['requests'] and not state['uncertain']:
                operate('arcB70', 'activate', previous)
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
