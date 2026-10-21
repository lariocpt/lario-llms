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
    # Read-only session IDs from the local projection allow migration across all
    # projects, including sessions absent from the current-location list page.
    # All mutations go through OpenCode; never update its database directly.
    import sqlite3
    path=Path.home()/'.local/share/opencode/opencode.db'
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    rows=db.execute('SELECT id,model,time_archived FROM session WHERE model IS NOT NULL').fetchall()
    target={'providerID':'geekom','id':smart_profile()}
    changed,failed=0,[]
    for identifier,raw,archived in rows:
        if archived:continue
        try:model=json.loads(raw)
        except ValueError:continue
        if not isinstance(model,dict) or model.get('providerID')!='geekom':continue
        if model.get('id',model.get('modelID'))==target['id']:continue
        try:
            api('POST','/api/session/'+identifier+'/model','--data',json.dumps({'model':target}))
            changed+=1
        except RuntimeError:failed.append(identifier)
    db.close()
    print(json.dumps({'changed_geekom_sessions':changed,'failed_session_ids':failed,'profile':target['id']}))
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
