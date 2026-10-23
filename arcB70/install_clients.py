#!/usr/bin/env python3
"""Install only Arc consumer keys and verified profile options; never touch backends."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
HOSTS={'bigcachy':'bigcachy','l-dev-ai':'l-dev-ai','mini-mobile':'cachyos-mini-mobile'}


def install(machine,credential):
    if socket.gethostname().split('.')[0]!=HOSTS[machine]:raise RuntimeError('wrong client host')
    setup=ROOT.parent/'machine-setup'
    source=json.loads((setup/'shared/agents/opencode.prepared.json').read_text())
    options=source['provider']['arcB70']
    if 'arcB70' in source.get('disabled_providers',[]) or not options.get('whitelist'):raise RuntimeError('no verified Arc profiles published in source')
    url='http://'+('127.0.0.1' if machine=='bigcachy' else '100.127.91.5')+':11437/v1/models'
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+credential})
    with urllib.request.urlopen(request,timeout=10) as response:available=json.load(response)
    if not set(options['whitelist'])<={x['id'] for x in available['data']}:raise RuntimeError('Arc catalogue mismatch')
    spec=importlib.util.spec_from_file_location('renderer',setup/'scripts/render-agent-configs.py')
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    from shared.admission.provision import private_write
    private=Path.home()/'.config/lario-admission/clients.json'
    data=json.loads(private.read_text()) if private.exists() else {}
    if private.exists():shutil.copy2(private,private.with_name(private.name+'.before-arc-'+str(time.time_ns())))
    data['arcB70']={'apiKey':credential};private_write(private,json.dumps(data,indent=2)+'\n')
    live=Path.home()/'.config/opencode/opencode.json'
    if not live.exists():live=live.with_suffix('.jsonc')
    shutil.copy2(live,live.with_name(live.name+'.before-arc-'+str(time.time_ns())))
    old=renderer.load_jsonc(str(live));old['disabled_providers']=[x for x in old.get('disabled_providers',[]) if x!='arcB70']
    private_write(live,json.dumps(old,indent=2)+'\n')
    subprocess.run([sys.executable,str(setup/'scripts/render-agent-configs.py'),'--machine',machine,
        '--base-dir',str(setup/'shared/agents'),'--overlay-dir',str(setup/'machines'/machine/'config')],check=True)
    subprocess.run(['opencode','reload'],check=True)
    final=renderer.load_jsonc(str(live))
    assert 'arcB70' not in final.get('disabled_providers',[])
    assert final['provider']['arcB70']['whitelist']==options['whitelist']
    print(machine+': verified Arc profile selectable; private consumer credential installed')


if __name__=='__main__':
    sys.path.insert(0,str(ROOT))
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receive',choices=HOSTS);a=p.parse_args()
    if a.receive:install(a.receive,json.load(sys.stdin)['key'])
    else:
        if socket.gethostname().split('.')[0]!='bigcachy':raise RuntimeError('distribute from owner only')
        keys=json.loads((Path.home()/'.config/lario-admission/arcB70.clients.json').read_text())
        for machine,host in HOSTS.items():
            command=[sys.executable,str(Path(__file__).resolve()),'--receive',machine]
            if host!='bigcachy':command=['ssh','-T',host,'python3 ~/Projects/personal/lario-llms/arcB70/install_clients.py --receive '+machine]
            subprocess.run(command,input=json.dumps({'key':keys[machine]['key']}),text=True,check=True)
