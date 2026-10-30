"""Publish validated GPU choices and image routing without restarting OpenCode."""
import argparse
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.serving.catalog import profiles
from shared.model_tools.export_choices import export

RECEIVE = r'''
import importlib.util,json,shutil,sys,time
from pathlib import Path
payload=json.load(sys.stdin)
setup=Path.home()/'Projects/personal/machine-setup'
module=setup/'scripts/render-agent-configs.py'
spec=importlib.util.spec_from_file_location('renderer',module);renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
backup=Path.home()/'.cache/lario-llms/config-backups';backup.mkdir(parents=True,exist_ok=True)
paths=[setup/'shared/agents/opencode.prepared.json',setup/'shared/agents/opencode_fixed_models.json',setup/'shared/agents/opencode_profile_models.json']
paths += [setup/'shared/agents/model_choices.json']
paths += [setup/'machines'/machine/'config/opencode.jsonc' for machine in ('bigcachy','l-dev-ai','mini-mobile')]
for path in paths:
    old=path.read_text();data=renderer.load_jsonc(str(path))
    if path.name == 'model_choices.json':
        for hardware,choice in payload['choices'].items():
            data.setdefault('hardware',{})[hardware]=choice
            data.setdefault('prepared',{}).pop(hardware,None)
    for hardware,models in payload['models'].items():
        target=data.get('provider',{}).get(hardware)
        if target is not None:
            target['models']=models
            if hardware=='arcB70' or 'whitelist' in target:target['whitelist']=list(models)
        previous=data.get('model','')
        if previous.startswith(hardware+'/') and previous.split('/',1)[1] not in models:
            data['model']=hardware+'/'+payload['defaults'][hardware]
    def route(value):
        if isinstance(value,dict):
            # Agent-specific pins and small_model can override the top-level
            # choice; retire stale ids there as well as in provider.models.
            for key,child in list(value.items()):
                if key not in ('model','small_model') or not isinstance(child,str):continue
                for hardware,models in payload['models'].items():
                    if child.startswith(hardware+'/') and child.split('/',1)[1] not in models:
                        value[key]=hardware+'/'+payload['defaults'][hardware]
            env=value.get('environment',{})
            if payload['route_images'] and 'LARIO_IMAGES_VISION_ENDPOINTS' in env:
                endpoints=json.loads(env['LARIO_IMAGES_VISION_ENDPOINTS']);endpoints['gdp7900xt']='@GDP7900XT_ENDPOINT@'
                env['LARIO_IMAGES_VISION_ENDPOINTS']=json.dumps(endpoints,separators=(',',':'))
                env['LARIO_IMAGES_HARDWARE']='gdp7900xt'
            for child in value.values():route(child)
        elif isinstance(value,list):
            for child in value:route(child)
    route(data)
    comments='\n'.join(line for line in old.splitlines() if line.lstrip().startswith('//'))
    text=(comments+'\n' if comments else '')+json.dumps(data,indent=2)+'\n'
    if text!=old:
        shutil.copy2(path,backup/(path.parent.name+'-'+path.name+'.'+str(time.time_ns())))
        path.write_text(text)
subprocess=__import__('subprocess')
subprocess.run([sys.executable,str(module),'--machine',payload['machine'],'--base-dir',str(setup/'shared/agents'),'--overlay-dir',str(setup/'machines'/payload['machine']/'config')],check=True)
print(payload['machine']+': GPU source choices and live settings rendered; active OpenCode workspaces left running')
'''


def publish(hardware):
    models = {}
    defaults = {}
    for name in hardware:
        reg = json.loads((ROOT/name/'models.json').read_text())
        entries = profiles(reg)
        if name == 'arcB70' and (len(entries) != 1 or not next(iter(entries.values()))['vision']):
            raise RuntimeError('B70 must have the validated single vision profile before publishing')
        if name == 'rtx5080' and not any(p['model']=='qwen38-flash-nvfp4' for p in entries.values()):
            raise RuntimeError('RTX Flash Next must be installed before publishing')
        models[name] = {key: {'name':p['name'], 'tool_call':True,
            'limit':{'context':p['context']-4096,'output':8192},
            'modalities':{'input':['text','image'] if p['vision'] else ['text'],'output':['text']}}
            for key,p in entries.items()}
        preferred = 'qwen38-flash-halogen-128k' if name == 'geekom' else 'qwen38-flash-nvfp4'
        defaults[name] = next((key for key,p in entries.items() if p['model']==preferred),next(iter(entries)))
    for machine,host in [('bigcachy','bigcachy'),('l-dev-ai','l-dev-ai'),('mini-mobile','cachyos-mini-mobile')]:
        payload={'machine':machine,'models':models,'defaults':defaults,'route_images':'gdp7900xt' in hardware,
                 'choices':{name:export()['hardware'][name] for name in hardware}}
        command=[sys.executable,'-c',RECEIVE] if host==socket.gethostname().split('.')[0] else ['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',host,'python3 -c '+shlex.quote(RECEIVE)]
        subprocess.run(command,input=json.dumps(payload),text=True,check=True,timeout=60)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware',nargs='+',choices=['geekom','arcB70','gdp7900xt','rtx5080'])
    publish(parser.parse_args().hardware)
