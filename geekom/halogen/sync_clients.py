#!/usr/bin/env python3
"""Add Halogen choices without changing defaults or restarting OpenCode."""
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.serving.catalog import opencode

RECEIVE = r'''
import importlib.util,json,shutil,subprocess,sys,time
from pathlib import Path
d=json.load(sys.stdin)
root=Path.home()/'Projects/personal/machine-setup'
script=root/'scripts/render-agent-configs.py'
spec=importlib.util.spec_from_file_location('renderer',script)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
backup=Path.home()/'.cache/lario-llms/config-backups';backup.mkdir(parents=True,exist_ok=True)
live=Path.home()/'.config/opencode/opencode.json'
if not live.exists():live=live.with_suffix('.jsonc')
before=r.load_jsonc(str(live))
paths=[root/'shared/agents'/name for name in ('opencode_fixed_models.json','opencode_profile_models.json','opencode.prepared.json')]
paths += [root/'machines'/m/'config/opencode.jsonc' for m in ('bigcachy','l-dev-ai','mini-mobile')]
for path in paths:
 if not path.exists():continue
 old=path.read_text();config=r.load_jsonc(str(path))
 provider=config.get('provider',{}).get('geekom')
 if provider is None:continue
 provider.setdefault('models',{}).update(d['models'])
 if 'whitelist' in provider:
  provider['whitelist']=list(dict.fromkeys(provider['whitelist']+list(d['models'])))
 comments='\n'.join(line for line in old.splitlines() if line.lstrip().startswith('//'))
 text=(comments+'\n' if comments else '')+json.dumps(config,indent=2)+'\n'
 if old!=text:
  shutil.copy2(path,backup/(path.parent.name+'-'+path.name+'.'+str(time.time_ns())))
  path.write_text(text)
subprocess.run([sys.executable,str(script),'--machine',d['machine'],'--base-dir',str(root/'shared/agents'),'--overlay-dir',str(root/'machines'/d['machine']/'config')],check=True)
after=r.load_jsonc(str(live))
assert before.get('model')==after.get('model')
assert before['provider']['geekom'].get('options')==after['provider']['geekom'].get('options')
assert all(all(after['provider']['geekom']['models'][k][field]==v[field]
               for field in ('name','limit','tool_call')) for k,v in d['models'].items())
print(d['machine']+': Halogen models published; defaults, credentials and active workspaces preserved')
'''


def main():
    models = {k:v for k,v in opencode()['provider']['geekom']['models'].items()
              if '.qwen38-flash-halogen' in k}
    if len(models) != 2:
        raise RuntimeError('expected the two Halogen profiles')
    for machine,host in [('bigcachy','bigcachy'),('l-dev-ai','l-dev-ai'),('mini-mobile','cachyos-mini-mobile')]:
        cmd = [sys.executable,'-c',RECEIVE] if host == socket.gethostname().split('.')[0] else [
            'ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8',host,'python3 -c '+shlex.quote(RECEIVE)]
        subprocess.run(cmd,input=json.dumps({'machine':machine,'models':models}),text=True,check=True,timeout=60)


if __name__ == '__main__':
    main()
