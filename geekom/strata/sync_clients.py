#!/usr/bin/env python3
"""Publish current Flash Next choices, retire old Geekom choices, without restarting active clients."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared.serving.catalog import opencode, profiles

CODE=r'''
import importlib.util,json,shutil,socket,subprocess,sys,time
from pathlib import Path
d=json.load(sys.stdin)
assert socket.gethostname().split('.')[0]==d['host']
root=Path.home()/'Projects/personal/machine-setup'
renderer=root/'scripts/render-agent-configs.py'
spec=importlib.util.spec_from_file_location('renderer',renderer)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
backup=Path.home()/'.cache/lario-llms/config-backups';backup.mkdir(parents=True,exist_ok=True)
def update(config, selected):
 for provider,entries in d['entries'].items():
  if provider not in selected:continue
  target=config.setdefault('provider',{}).setdefault(provider,{}).setdefault('models',{})
  retired=[key for key in target if provider=='geekom' and 'qwen38-flash' in key and key not in entries]
  for key in retired:target.pop(key)
  target.update(entries)
  allowed=config['provider'][provider].get('whitelist')
  if allowed is not None:
   config['provider'][provider]['whitelist']=[key for key in allowed if key not in retired]
   for key in entries:
    if key not in config['provider'][provider]['whitelist']:config['provider'][provider]['whitelist'].append(key)
paths=[root/'shared/agents/opencode_fixed_models.json',root/'shared/agents/opencode.prepared.json']
paths += [root/'machines'/machine/'config/opencode.jsonc' for machine in ('bigcachy','l-dev-ai','mini-mobile')]
for path in paths:
 old=path.read_text();config=r.load_jsonc(str(path));update(config, ['arcB70'] if path.name=='opencode.prepared.json' else ['geekom'])
 comments='\n'.join(line for line in old.splitlines() if line.lstrip().startswith('//'))
 text=(comments+'\n' if comments else '')+json.dumps(config,indent=2)+'\n'
 if old!=text:
  shutil.copy2(path,backup/(path.parent.name+'-'+path.name+'.'+str(time.time_ns())))
  path.write_text(text)
live=Path.home()/'.config/opencode/opencode.json'
if not live.exists():live=live.with_suffix('.jsonc')
before=r.load_jsonc(str(live));default=before.get('model')
subprocess.run([sys.executable,str(renderer),'--machine',d['machine'],
 '--base-dir',str(root/'shared/agents'),'--overlay-dir',str(root/'machines'/d['machine']/'config')],check=True)
# Active workspace runtimes must not be disposed by a fleet-wide reload.
# OpenCode reads the saved settings on its next config refresh/start.
after=r.load_jsonc(str(live));assert after.get('model')==default
for provider,entries in d['entries'].items():
 installed=after['provider'][provider]['models']
 for key,entry in entries.items():
  assert installed[key]['name']==entry['name'] and installed[key]['limit']==entry['limit']
  assert not installed[key]['name'].startswith('provisional-')
 if provider=='geekom':
  assert {key for key in installed if 'qwen38-flash' in key}==set(entries)
 assert before['provider'][provider].get('options')==after['provider'][provider].get('options')
print(d['host']+': new Flash names verified; obsolete Geekom entries removed; defaults and provider options preserved')
'''

def main():
    catalog=opencode()['provider']
    reg=json.loads((ROOT/'arcB70/models.json').read_text())
    catalog['arcB70']={'models':{key:{'name':p['name'],'limit':{'context':p['context']-4096,'output':8192},'tool_call':True,'modalities':{'input':['text'],'output':['text']}} for key,p in profiles(reg).items()}}
    entries={provider:{key:entry for key,entry in catalog[provider]['models'].items()
                      if marker in key}
             for provider,marker in [('geekom','.qwen38-flash-strata'),('arcB70','.qwen38-flash-q4-')]}
    prepared=json.loads((ROOT/'arcB70/opencode.prepared.json').read_text())['provider']['arcB70']
    entries['arcB70']={key:entry for key,entry in entries['arcB70'].items() if key in prepared['whitelist']}
    assert all(models for models in entries.values())
    for machine,host in [('bigcachy','bigcachy'),('l-dev-ai','l-dev-ai'),('mini-mobile','cachyos-mini-mobile')]:
        cmd=[sys.executable,'-c',CODE] if host=='bigcachy' else [
            'ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8',host,'python3 -c '+shlex.quote(CODE)]
        subprocess.run(cmd,input=json.dumps({'host':host,'machine':machine,'entries':entries}),
                       text=True,check=True,timeout=60)

if __name__=='__main__':main()
