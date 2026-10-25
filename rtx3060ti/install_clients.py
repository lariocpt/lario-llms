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
# Deploy the canonical renderer and merge only this provider into the source catalog.
renderer=setup/'scripts/render-agent-configs.py'
if renderer.read_text()!=body['renderer']:renderer.write_text(body['renderer'])
prepared=setup/'shared/agents/opencode.prepared.json'
fragment=json.loads(prepared.read_text()) if prepared.exists() else {}
fragment.setdefault('provider',{})['rtx3060ti']=body['provider']
prepared.write_text(json.dumps(fragment,indent=2)+'\n')
image_tools=setup/'shared/agents/image_tools.py'
if image_tools.read_text()!=body['image_tools']:image_tools.write_text(body['image_tools'])
spec=importlib.util.spec_from_file_location('renderer',renderer)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
overlay=setup/'machines'/machine/'config/opencode.jsonc'
old=overlay.read_text();data=r.load_jsonc(str(overlay))
data['mcp']['lario_images']['environment']['LARIO_IMAGES_VISION_ENDPOINTS']=json.dumps({
    'rtx3060ti':'@RTX3060TI_ENDPOINT@',
    'rtx5080':'http://127.0.0.1:11435/v1' if machine=='bigcachy' else 'http://100.127.91.5:11435/v1'})
comments='\n'.join(line for line in old.splitlines() if line.lstrip().startswith('//'))
overlay.write_text((comments+'\n' if comments else '')+json.dumps(data,indent=2)+'\n')
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
    renderer = (ROOT.parent/'machine-setup/scripts/render-agent-configs.py').read_text()
    for machine in machines:
        endpoint = 'http://'+('127.0.0.1' if machine == 'mini-mobile' else IPS['mini-mobile'])+':11438/v1'
        body = dict(machine=machine, key=info['clients'][machine], endpoint=endpoint,
                    provider=provider, renderer=renderer,
                    image_tools=(ROOT.parent/'machine-setup/shared/agents/image_tools.py').read_text())
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
