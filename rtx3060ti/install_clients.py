#!/usr/bin/env python3
"""Register vision clients, verify gateway access, then render machine-setup OpenCode config."""
import argparse
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.serving.catalog import opencode
from shared.serving.provision_control import HOSTS, IPS, owner

# Credentials travel only on stdin over authenticated SSH and are never source files.
INSTALL = r'''
import importlib.util,json,os,pathlib,subprocess,sys,time,urllib.request
body=json.load(sys.stdin)
machine=body['machine']
request=urllib.request.Request(body['endpoint']+'/models',headers={'Authorization':'Bearer '+body['key']})
with urllib.request.urlopen(request,timeout=15) as response:catalog=json.load(response)
assert {m['id'] for m in catalog['data']}==set(body['provider']['models']), 'unexpected gateway catalog'
setup=pathlib.Path.home()/'Projects/personal/machine-setup'
private=pathlib.Path.home()/'.config/lario-admission/clients.json'
private.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
clients=json.loads(private.read_text()) if private.exists() else {}
if private.exists():
    backup=private.with_name(private.name+'.before-rtx3060ti-'+str(time.time_ns()))
    backup.write_text(private.read_text());backup.chmod(0o600)
clients['rtx3060ti']={'apiKey':body['key'],'enabled':True}
fd=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as stream:json.dump(clients,stream,indent=2)
private.chmod(0o600)
# Consume the committed machine-setup sources; repo sync owns source deployment.
renderer=setup/'scripts/render-agent-configs.py'
spec=importlib.util.spec_from_file_location('renderer',renderer)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
prepared=json.loads((setup/'shared/agents/opencode.prepared.json').read_text())
assert set(prepared['provider']['rtx3060ti']['models'])==set(body['provider']['models']), 'sync machine-setup catalog first'
overlay=r.load_jsonc(str(setup/'machines'/machine/'config/opencode.jsonc'))
assert 'rtx3060ti' in json.loads(overlay['mcp']['lario_images']['environment']['LARIO_IMAGES_VISION_ENDPOINTS']), 'sync machine-setup vision endpoints first'
subprocess.run([sys.executable,str(renderer),'--machine',machine,'--base-dir',str(setup/'shared/agents'),
                '--overlay-dir',str(setup/'machines'/machine/'config')],check=True)
spec=importlib.util.spec_from_file_location('renderer',renderer)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
live=pathlib.Path.home()/'.config/opencode/opencode.json'
if not live.exists():live=live.with_suffix('.jsonc')
data=r.load_jsonc(str(live))
assert 'rtx3060ti' not in data.get('disabled_providers',[])
assert data['provider']['rtx3060ti']['options']['apiKey']==body['key']
assert data['provider']['rtx3060ti']['options']['baseURL']==body['endpoint']
print(machine+': verified vision credential, catalog and rendered provider; current sessions preserved')
'''


def install(machines):
    info = owner('rtx3060ti', register=True)
    provider = json.loads((ROOT.parent/'machine-setup/shared/agents/opencode.prepared.json').read_text())['provider']['rtx3060ti']
    provider['models'] = opencode()['provider']['rtx3060ti']['models']
    for machine in machines:
        endpoint = 'http://'+('127.0.0.1' if machine == 'mini-mobile' else IPS['mini-mobile'])+':11438/v1'
        body = dict(machine=machine, key=info['clients'][machine], endpoint=endpoint,
                    provider=provider)
        args = [sys.executable, '-c', INSTALL]
        if socket.gethostname().split('.')[0] != HOSTS[machine]:
            args = ['ssh', '-F', str(Path.home()/'.ssh/config'), '-o', 'BatchMode=yes',
                    HOSTS[machine], shlex.join(args)]
        subprocess.run(args, input=json.dumps(body), text=True, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine', choices=HOSTS, action='append')
    args = parser.parse_args()
    install(args.machine or list(HOSTS))
