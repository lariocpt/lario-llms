#!/usr/bin/env python3
"""Render fixed OpenCode entries and migrate Geekom sessions using its supported API."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared.serving.catalog import opencode, profiles


def renderer():
    path=ROOT.parent/'machine-setup/scripts/render-agent-configs.py'
    spec=importlib.util.spec_from_file_location('renderer',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def smart_profile():
    reg=json.loads((ROOT/'geekom/models.json').read_text())
    return next(p['id'] for p in profiles(reg).values() if p['model']=='qwen3.8-smart' and p['preset']=='capacity')


def source():
    setup=ROOT.parent/'machine-setup'
    r=renderer()
    fragment=opencode()
    for machine in ('bigcachy','mini-mobile','l-dev-ai'):
        path=setup/'machines'/machine/'config/opencode.jsonc'
        old=path.read_text();data=r.load_jsonc(str(path))
        for hardware,entry in fragment['provider'].items():
            data['provider'][hardware]['models']=entry['models']
        data['model']='geekom/'+smart_profile()
        for agent in data.get('agent',{}).values():
            if isinstance(agent,dict) and str(agent.get('model','')).startswith('geekom/'):
                agent['model']=data['model']
        text=json.dumps(data,indent=2)+'\n'
        comments='\n'.join(line for line in old.splitlines() if line.lstrip().startswith('//'))
        if comments:text=comments+'\n'+text
        path.write_text(text)
    (setup/'shared/agents/opencode_fixed_models.json').write_text(json.dumps(fragment,indent=2)+'\n')
    print('Updated source overlays for all three clients; default is regular Geekom Smart large context')


def live(machine):
    setup=ROOT.parent/'machine-setup'
    directory=Path.home()/'.config/opencode'
    path=directory/'opencode.json'
    if not path.exists():path=path.with_suffix('.jsonc')
    backup=path.with_name(path.name+'.before-fixed-'+str(time.time_ns()))
    shutil.copy2(path,backup);backup.chmod(0o600)
    private=Path.home()/'.config/lario-admission/clients.json'
    if private.exists():
        shutil.copy2(private,private.with_name(private.name+'.before-fixed-'+str(time.time_ns())))
        data=json.loads(private.read_text())
        for hardware in ('geekom','7900xt','rtx5080'):
            if hardware in data:data[hardware].pop('context_limits',None)
        private.write_text(json.dumps(data,indent=2)+'\n');private.chmod(0o600)
    subprocess.run([sys.executable,str(setup/'scripts/render-agent-configs.py'),'--machine',machine,
                    '--base-dir',str(setup/'shared/agents'),'--overlay-dir',str(setup/'machines'/machine/'config')],check=True)
    subprocess.run(['opencode','reload'],check=True)
    r=renderer();actual=r.load_jsonc(str(path))
    for hardware,entry in opencode()['provider'].items():
        installed=actual['provider'][hardware]['models']
        for key,model in entry['models'].items():
            if installed[key]['limit']!=model['limit']:raise RuntimeError('effective model limits differ')
    print('Verified fixed profile limits for all three providers on '+machine)


def api(*args):
    result=subprocess.run(['opencode','api',*args],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('OpenCode API operation failed: '+result.stderr[:120])
    return json.loads(result.stdout) if result.stdout.strip() else None


def sessions():
    from urllib.parse import urlencode
    entries=opencode()['provider']
    target={'providerID':'geekom','id':smart_profile()}
    catalogues={h:profiles(json.loads((ROOT/h/'models.json').read_text())) for h in entries}
    candidates=[];cursor=None;seen=set()
    for _ in range(500):
        params={'limit':100}
        if cursor:params['cursor']=cursor
        page=api('GET','/api/session?'+urlencode(params))
        candidates.extend(page.get('data',[]))
        cursor=page.get('cursor',{}).get('next')
        if not cursor:break
        if cursor in seen:raise RuntimeError('session cursor repeated')
        seen.add(cursor)
    else:raise RuntimeError('session pagination limit exceeded')
    changed={h:0 for h in entries};failed=[];missing=[]
    for item in candidates:
        if item.get('time',{}).get('archived'):continue
        model=item.get('model') or {};hardware=model.get('providerID')
        if hardware not in entries:continue
        previous=model.get('id',model.get('modelID',''))
        if hardware=='geekom':replacement=target['id']
        elif previous in catalogues[hardware]:continue
        else:
            name,preset=(previous.split('@',1)+[None])[:2] if '@' in previous else (previous,None)
            if name in ('7900xt','rtx5080'):name='qwen3.8'
            matches=[p for p in catalogues[hardware].values() if p['model']==name and (preset is None or p['preset']==preset)]
            if len(matches)!=1:
                failed.append({'id':item['id'],'reason':'ambiguous legacy model'});continue
            replacement=matches[0]['id']
        if previous==replacement:continue
        payload={'model':{'providerID':hardware,'id':replacement}}
        result=subprocess.run(['opencode','api','POST','/api/session/'+item['id']+'/model',
                               '--data',json.dumps(payload)],capture_output=True,text=True,timeout=30)
        if result.returncode:
            if 'LocationNotFoundError' in result.stdout+result.stderr or (item.get('location',{}).get('directory','').startswith('/tmp/') and item.get('outcome')!='running'):
                missing.append(item['id'])
            else:failed.append({'id':item['id'],'reason':'API refused migration'})
        else:changed[hardware]+=1
    print(json.dumps({'changed_sessions':changed,'skipped_missing_locations':missing,
                      'failed':failed,'geekom_profile':target['id']}))
    if failed:raise SystemExit(1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['source','live','sessions'])
    p.add_argument('--machine',choices=['bigcachy','mini-mobile','l-dev-ai'])
    args=p.parse_args()
    if args.action=='source':source()
    elif args.action=='live':
        if not args.machine:p.error('--machine required')
        live(args.machine)
    else:sessions()
