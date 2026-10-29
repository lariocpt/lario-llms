#!/usr/bin/env python3
"""Deploy the tested Flash profile through the existing idle Geekom owner only."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared import modelctl
from shared.serving.catalog import profiles
from shared.serving.control import operate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('256k','512k'),default='256k')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--already-paused',action='store_true')
    args=parser.parse_args()
    context,slots=(524288,2) if args.mode=='512k' else (262144,4)
    model='qwen38-flash-strata'+('-512k' if args.mode=='512k' else '')
    if args.mode=='512k' and not args.report:
        parser.error('--report is required for the new mode')
    reg = json.loads((ROOT/'geekom/models.json').read_text())
    modelctl.load_runtime(reg)
    modelctl.assert_not_held(reg)
    report = args.report or ROOT/'research/benchmarks/20261027-geekom-strata/smoke-256k-4/result.json'
    receipt = json.loads(report.read_text())
    if receipt['status'] != 'passed' or receipt['actual_context'] != context or receipt['actual_slots'] != slots:
        raise RuntimeError('requested native geometry validation receipt missing')
    if receipt['engine_info']['kv'] != 'q4_0':
        raise RuntimeError('KV4 was not validated')
    flash = next(p for p in profiles(reg).values() if p['model'] == model)
    before = operate('geekom', 'status')
    if before['busy'] or before['requests'] or before['uncertain'] or (before['draining'] and not args.already_paused):
        raise RuntimeError('owner must be confirmed idle and unpaused')
    previous = next((p['id'] for p in profiles(reg).values() if p['model'] == before.get('model')), None)
    if previous is None and args.already_paused:
        previous=next((p['id'] for p in profiles(reg).values() if p['model']=='qwen38-flash-strata'),None)
    modelctl.assert_idle(reg)
    operate('geekom', 'pause')
    try:
        state = operate('geekom', 'status')
        if state['busy'] or state['requests'] or state['uncertain']:
            raise RuntimeError('work arrived; deployment stopped')
        modelctl.assert_idle(reg)
        if previous:
            operate('geekom', 'unload', previous)
        subprocess.run(['systemctl', '--user', 'restart', 'llama-swap.service'], check=True)
        subprocess.run(['systemctl', '--user', 'restart', 'lario-admission@geekom.service'], check=True)
        for attempt in range(60):
            try:
                operate('geekom', 'status')
                break
            except Exception:
                if attempt == 59:
                    raise
                time.sleep(1)
        operate('geekom', 'resume')
        operate('geekom', 'enable', flash['id'])
        operate('geekom', 'activate', flash['id'])
        def check(_):
            body = {'model': flash['id'], 'messages': [{'role': 'user', 'content': 'Return exactly 7'}],
                    'temperature': 0, 'max_tokens': 32, 'cache_prompt': True,
                    'chat_template_kwargs': {'enable_thinking': False}}
            req = urllib.request.Request('http://127.0.0.1:11434/v1/chat/completions',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Authorization': 'Bearer '+os.environ['LARIO_AUXILIARY_KEY']})
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.load(response)
            if result['choices'][0]['message']['content'].strip() != '7':
                raise RuntimeError('public gateway inference failed')
            return {'correct': True, 'usage': result.get('usage')}
        with concurrent.futures.ThreadPoolExecutor(max_workers=slots) as pool:
            checks = list(pool.map(check, range(slots)))
        result = {'profile_id': flash['id'], 'backend_id': flash['backend_id'],
                  'gateway_checks': checks, 'status': 'passed', 'state': operate('geekom', 'status')}
        (report.parent.parent/'deployed.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({'status': 'passed', 'profile': flash['id'], 'gateway_correct': len(checks)}))
    except BaseException:
        try:
            operate('geekom', 'resume')
            state = operate('geekom', 'status')
            if previous and not state['busy'] and not state['requests'] and not state['uncertain']:
                operate('geekom', 'activate', previous)
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
