#!/usr/bin/env python3
"""Repair scoped Geekom/Radeon access on the three development clients.

Run on l-dev-ai from an unrestricted host shell. Reuses existing owner keys,
backs up private client files, renders machine-setup configs and authenticates
from each client. Never restarts a service or edits an OpenCode database.
"""
import argparse
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.serving.catalog import profiles
from shared.serving.provision_control import HOSTS

HARDWARE = ('geekom', 'geekom7900xt')

WORKER = r'''
import importlib.util, json, os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
def completion_allowed(budget, profile):
    availability = budget.get('profile_availability', {}).get(profile, {})
    same_resident = (budget.get('profile_id') == profile
                     or availability.get('resident') is True)
    return not budget.get('draining') and (
        not budget.get('busy') or (same_resident and budget.get('available', 0) > 0))
body = json.load(sys.stdin)
machine = body['machine']
if socket.gethostname().split('.')[0] != body['host']:
    raise RuntimeError('wrong client host')
root = Path.home()/'Projects/personal'
setup = root/'machine-setup'
spec = importlib.util.spec_from_file_location('renderer', setup/'scripts/render-agent-configs.py')
renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
overlay = renderer.resolve_fleet_endpoints(
    renderer.load_jsonc(str(setup/'machines'/machine/'config/opencode.jsonc')), machine)
def request(base, key, path, data=None):
    req = urllib.request.Request(base.removesuffix('/v1')+path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+key, 'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=1800 if data else 20) as response:
        return json.load(response)
for hardware, key in body['keys'].items():
    base = overlay['provider'][hardware]['options']['baseURL']
    models = request(base, key, '/v1/models')
    if body['profiles'][hardware] not in {item['id'] for item in models['data']}:
        raise RuntimeError(hardware+': expected Qwen profile is not advertised')
# Validate every replacement before modifying private state.
private = Path.home()/'.config/lario-admission/clients.json'
if private.exists():
    backup = private.with_name(private.name+'.before-access-repair-'+str(time.time_ns()))
    fd = os.open(backup, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream: stream.write(private.read_text())
spec = importlib.util.spec_from_file_location('installer', root/'lario-llms/shared/admission/install_client.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
installer.install({h:{'apiKey':k} for h,k in body['keys'].items()}, machine)
live = Path.home()/'.config/opencode/opencode.jsonc'
if not live.exists(): live = live.with_name('opencode.json')
config = renderer.load_jsonc(str(live))
for hardware, key in body['keys'].items():
    provider = config['provider'][hardware]
    if provider['options'].get('apiKey') != key:
        raise RuntimeError(hardware+': rendered credential mismatch')
    if body['profiles'][hardware] not in provider['models']:
        raise RuntimeError(hardware+': rendered Qwen profile missing')
    if hardware in config.get('disabled_providers', []):
        raise RuntimeError(hardware+': provider is disabled')
    request(provider['options']['baseURL'], key, '/v1/models')
    print(machine+': '+hardware+' authentication and rendered config PASS', flush=True)
if body['complete']:
    for hardware, key in body['keys'].items():
        base = config['provider'][hardware]['options']['baseURL']
        budget = request(base, key, '/budget')
        if not completion_allowed(budget, body['profiles'][hardware]):
            raise RuntimeError(hardware+': busy or draining; completion deferred')
        reply = request(base, key, '/v1/chat/completions', {
            'model':body['profiles'][hardware],
            'messages':[{'role':'user','content':'Reply with OK.'}],
            'max_tokens':256, 'temperature':0})
        choices = reply.get('choices') or []
        if not choices or not choices[0].get('message', {}).get('content', '').strip():
            raise RuntimeError(hardware+': no visible completion returned')
        print(machine+': '+hardware+' Qwen completion PASS', flush=True)
print(machine+': reopen OpenCode to load the repaired configuration', flush=True)
'''


def payloads(complete=False):
    private = Path.home()/'.config/lario-admission'
    keys, selected = {}, {}
    for hardware in HARDWARE:
        reg = json.loads((ROOT/hardware/'models.json').read_text())
        if socket.gethostname().split('.')[0] != reg['host']:
            raise RuntimeError('run on the Geekom owner, l-dev-ai')
        entries = json.loads((private/(hardware+'.clients.json')).read_text())
        keys[hardware] = {}
        for machine in HOSTS:
            entry = entries[machine]
            if entry['role'] != 'interactive' or len(entry['key']) < 24:
                raise ValueError('invalid registered interactive credential')
            keys[hardware][machine] = entry['key']
        model = 'qwen3.8-smart' if hardware == 'geekom' else 'qwen3.8'
        preset = 'capacity' if hardware == 'geekom' else 'fast-128k'
        matches = [key for key, p in profiles(reg).items()
                   if p['model'] == model and p['preset'] == preset]
        if len(matches) != 1:
            raise ValueError('expected one canonical Qwen profile for '+hardware)
        selected[hardware] = matches[0]
    return [{
        'machine':machine, 'host':HOSTS[machine],
        'keys':{h:keys[h][machine] for h in HARDWARE}, 'profiles':selected,
        'complete':complete and machine == 'l-dev-ai',
    } for machine in ('mini-mobile', 'bigcachy', 'l-dev-ai')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete', action='store_true',
                        help='also request one Qwen completion per GPU on the owner')
    args = parser.parse_args()
    failed = []
    for body in payloads(args.complete):
        host = body['host']
        command = [sys.executable, '-c', WORKER]
        if host != socket.gethostname().split('.')[0]:
            command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                       host, shlex.join(['python3', '-c', WORKER])]
        # Keys travel only over stdin/SSH, never argv, logs or source.
        try:
            result = subprocess.run(command, input=json.dumps(body), text=True,
                                    capture_output=True, timeout=3700)
        except (OSError, subprocess.TimeoutExpired):
            failed.append(body['machine'])
            print(body['machine']+': connection or execution failed', flush=True)
            continue
        output = result.stdout
        for key in body['keys'].values(): output = output.replace(key, '[redacted]')
        print(output, end='', flush=True)
        if result.returncode:
            failed.append(body['machine'])
            # A dependency could include request headers in an exception: redact
            # known credentials before displaying diagnostic output.
            detail = result.stderr[-2000:]
            for key in body['keys'].values(): detail = detail.replace(key, '[redacted]')
            print(body['machine']+': repair/check FAILED\n'+detail, flush=True)
    if failed:
        raise SystemExit('Some checks did not finish on: '+', '.join(failed)+
                         '. Any authentication PASS results above remain valid.')
    print('All three clients authenticated to Geekom and Radeon.')


if __name__ == '__main__':
    main()
